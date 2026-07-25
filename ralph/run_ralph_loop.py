from __future__ import annotations

import argparse
import copy
import datetime as dt
import json
import os
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

if __name__ == "__main__":
    _package_root = Path(__file__).resolve().parent.parent
    if str(_package_root) not in sys.path:
        sys.path.insert(0, str(_package_root))

import yaml

from ralph.agent_backends import (
    AgentBackend,
    AgentResult,
    extract_agent_result_text,
    prepare_agent_backend_for_worker,
    run_command_and_save_agent_transcripts,
    select_agent_backend,
)
from ralph.claude_backend import build_direct_claude_command
from ralph.codex_backend import build_direct_codex_command
from ralph.cursor_backend import build_direct_cursor_command
from ralph.notion import (
    complete_notion_task_after_accepting_worker,
    materialise_and_validate_notion_task_graph,
)
from ralph.plan_selection import (
    TaskSelection,
    read_tasks_from_ledger,
    select_next_task_from_plan_and_ledger,
)
from ralph.prompt import render_agent_prompt
from ralph.sandbox import (
    agent_permission_setup,
    build_bwrap_agent_command,
    reject_worker_visible_path_that_overlaps_hidden_state,
    resolve_python_venv_path,
    run_agent_visibility_smoke_test,
)


DEFAULT_MAX_ITERATIONS = 10
PROMISE_PATTERN = re.compile(r"<promise>(DONE|BLOCKED|ABORT)</promise>")
PROMISE_LINE_PATTERN = re.compile(r"^<promise>(DONE|BLOCKED|ABORT)</promise>$")
WORKER_COMMIT_LINE_PATTERN = re.compile(r"^RALPH_COMMIT (?P<commit_hash>[0-9a-f]{40})$", re.MULTILINE)

PRIVATE_CONTROL_PATH_NAMES = frozenset({"ledger.yaml", ".ralph"})


@dataclass(frozen=True)
class RalphJob:
    job_name: str
    job_path: Path
    plan_path: Path
    ledger_path: Path
    tasks_path: Path


def main(argv: list[str] | None = None) -> None:
    arguments = _parse_arguments(argv)
    if arguments.command == "run":
        _run_ralph_loop(arguments)
        return
    if arguments.command == "validate":
        _validate_ralph_job(arguments)
        return
    if arguments.command == "smoke-test":
        run_agent_visibility_smoke_test(
            repo_path=_resolve_repo_path(arguments.repo_path),
            agent_backend_name=arguments.agent_backend,
            agent_command=arguments.agent_command,
            python_venv_path=resolve_python_venv_path(arguments.python_venv),
        )
        print(f"Ralph {arguments.agent_backend} smoke test passed.")
        return
    raise SystemExit(f"Unknown command: {arguments.command}")


def _run_ralph_loop(arguments: argparse.Namespace) -> None:
    tool_virtual_environment_path = _require_controller_tool_virtual_environment()
    controller_path = os.environ["PATH"]
    repo_path = _resolve_repo_path(arguments.repo_path)
    python_venv_path = resolve_python_venv_path(arguments.python_venv)
    job = _find_ralph_job(
        job_name=arguments.job_name,
        ralph_home_path=_resolve_ralph_home_path(arguments.ralph_home_path),
    )
    _prepare_job_directories(job)
    _refuse_unsafe_starting_state(
        repo_path,
        job,
        allow_dirty_start=arguments.allow_dirty_start,
    )
    ledger = materialise_and_validate_notion_task_graph(
        job=job,
        ledger=_read_yaml_file(job.ledger_path),
    )
    if not arguments.skip_ralph_sandbox:
        run_agent_visibility_smoke_test(
            repo_path=repo_path,
            agent_backend_name=arguments.agent_backend,
            agent_command=arguments.agent_command,
            python_venv_path=python_venv_path,
        )
    for _ in range(arguments.max_iterations):
        ledger = _read_yaml_file(job.ledger_path)
        plan_text = job.plan_path.read_text()
        selection = select_next_task_from_plan_and_ledger(ledger, plan_text)
        if selection is None:
            print("No runnable Ralph tasks remain.")
            return

        task_path = _create_task_directory(
            job.tasks_path,
            selection.task["ralph_task_id"],
        )
        print(f"Ralph task: {task_path}")
        prompt = render_agent_prompt(
            repo_path=repo_path,
            selection=selection,
        )
        _save_worker_prompt_before_launch(task_path=task_path, prompt=prompt)
        agent_result = _run_agent(
            repo_path=repo_path,
            task=selection.task,
            prompt=prompt,
            agent_backend_name=arguments.agent_backend,
            agent_command=arguments.agent_command,
            python_venv_path=python_venv_path,
            output_path=task_path / "agent-output.txt",
            tee_output=arguments.tee_agent_output,
            task_path=task_path,
            skip_ralph_sandbox=arguments.skip_ralph_sandbox,
            tool_virtual_environment_path=tool_virtual_environment_path,
            controller_path=controller_path,
        )
        _write_text(task_path / "promise.txt", agent_result.promise)

        if agent_result.promise != "DONE":
            stopped_ledger = _mark_task_stopped(
                ledger=ledger,
                task_id=selection.task["ralph_task_id"],
                promise=agent_result.promise,
            )
            _write_yaml_file(job.ledger_path, stopped_ledger)
            print(f"Agent stopped with {agent_result.promise}. See {task_path}")
            return

        commit_hash = _accept_worker_completed_task(
            repo_path=repo_path,
            selection=selection,
            task_path=task_path,
            agent_output=agent_result.output,
        )
        if arguments.ask_for_review:
            commit_hash = _pause_for_human_review_after_accepting_worker_completed_task(
                repo_path=repo_path,
                task=selection.task,
                task_path=task_path,
                accepted_commit_hash=commit_hash,
            )
        complete_notion_task_after_accepting_worker(
            selection=selection,
            task_path=task_path,
            commit_hash=commit_hash,
        )
        _write_yaml_file(
            job.ledger_path,
            _mark_task_done(ledger, selection.task["ralph_task_id"]),
        )
        print(f"Completed {selection.task['ralph_task_id']}: {commit_hash}")

    _finish_when_iteration_limit_reaches_complete_job(
        job=job,
        max_iterations=arguments.max_iterations,
    )


def _require_controller_tool_virtual_environment() -> Path:
    virtual_environment = os.environ.get("VIRTUAL_ENV")
    ntt_command_path = shutil.which("ntt")
    if virtual_environment is not None:
        virtual_environment_bin_path = Path(virtual_environment).expanduser().absolute() / "bin"
        python_runs_from_virtual_environment = (
            Path(sys.executable).absolute().parent == virtual_environment_bin_path
        )
        ntt_runs_from_virtual_environment = (
            ntt_command_path is not None
            and Path(ntt_command_path).absolute().parent == virtual_environment_bin_path
        )
        if python_runs_from_virtual_environment and ntt_runs_from_virtual_environment:
            return Path(virtual_environment).expanduser().absolute()

    raise RuntimeError(
        "Ralph must run from the tool virtual environment that provides NTT. "
        "Launch it with `source /path/to/tool-venv/bin/activate && "
        "python -m ralph.run_ralph_loop run ...`."
    )


def _finish_when_iteration_limit_reaches_complete_job(
    job: RalphJob,
    max_iterations: int,
) -> None:
    ledger = _read_yaml_file(job.ledger_path)
    plan_text = job.plan_path.read_text()
    if select_next_task_from_plan_and_ledger(ledger, plan_text) is None:
        print("No runnable Ralph tasks remain.")
        return

    raise SystemExit(f"Reached max iterations: {max_iterations}")


def _validate_ralph_job(arguments: argparse.Namespace) -> None:
    job = _find_ralph_job(
        job_name=arguments.job_name,
        ralph_home_path=_resolve_ralph_home_path(arguments.ralph_home_path),
    )
    _require_ralph_job_files(job)

    ledger = _read_yaml_file(job.ledger_path)
    plan_text = job.plan_path.read_text()
    selection = select_next_task_from_plan_and_ledger(ledger, plan_text)

    if arguments.repo_path is not None:
        _refuse_unsafe_starting_state(
            _resolve_repo_path(arguments.repo_path),
            job,
            allow_dirty_start=arguments.allow_dirty_start,
        )

    if selection is None:
        print(f"Ralph job {job.job_name} is valid. No runnable tasks remain.")
        return
    print(
        f"Ralph job {job.job_name} is valid. "
        f"Next runnable task: {selection.task['ralph_task_id']}"
    )


def _save_worker_prompt_before_launch(task_path: Path, prompt: str) -> None:
    _write_text(task_path / "PROMPT.md", prompt)


def _pause_for_human_review_after_accepting_worker_completed_task(
    repo_path: Path,
    task: dict[str, Any],
    task_path: Path,
    accepted_commit_hash: str,
) -> str:
    _run_git(repo_path, "reset", "--mixed", "HEAD^")
    input(
        "\n".join([
            f"Review uncommitted Ralph task {task['ralph_task_id']}: {task['title']}",
            f"Task artefacts: {task_path}",
            "Review the worktree diff now.",
            "Press Enter to commit this task and continue, or interrupt to stop.",
            "",
        ])
    )
    _run_git(repo_path, "add", "--all")
    _run_git(
        repo_path,
        "commit",
        "--no-verify",
        "-m",
        f"Ralph: {task['ralph_task_id']} {task['title']}",
    )
    reviewed_commit_hash = _run_git(repo_path, "rev-parse", "HEAD").strip()
    _write_text(task_path / "commit.txt", reviewed_commit_hash)
    _validate_worker_commit_matches_repo_state(
        repo_path=repo_path,
        task=task,
        commit_hash=reviewed_commit_hash,
    )
    print(f"Reviewed {accepted_commit_hash}; recommitted as {reviewed_commit_hash}")
    return reviewed_commit_hash


def _accept_worker_completed_task(
    repo_path: Path,
    selection: TaskSelection,
    task_path: Path,
    agent_output: str,
) -> str:
    commit_hash = _extract_worker_commit_hash(agent_output)

    _write_text(task_path / "commit.txt", commit_hash)
    _validate_worker_commit_matches_repo_state(
        repo_path=repo_path,
        task=selection.task,
        commit_hash=commit_hash,
    )

    return commit_hash


def _extract_worker_commit_hash(agent_output: str) -> str:
    matches = WORKER_COMMIT_LINE_PATTERN.findall(agent_output)
    if not matches:
        raise RuntimeError("Worker DONE must include exactly one RALPH_COMMIT line with the committed HEAD.")
    return matches[-1]


def _validate_worker_commit_matches_repo_state(
    repo_path: Path,
    task: dict[str, Any],
    commit_hash: str,
) -> None:
    actual_head_commit_hash = _run_git(repo_path, "rev-parse", "HEAD").strip()
    if commit_hash != actual_head_commit_hash:
        raise RuntimeError(
            f"Worker reported commit {commit_hash}, but target repo HEAD is {actual_head_commit_hash}."
        )

    expected_commit_subject = f"Ralph: {task['ralph_task_id']} {task['title']}"
    actual_commit_subject = _run_git(repo_path, "log", "--format=%s", "-1", commit_hash).strip()
    if actual_commit_subject != expected_commit_subject:
        raise RuntimeError(
            f"Worker commit subject must be {expected_commit_subject!r}, got {actual_commit_subject!r}."
        )

    if _read_git_status(repo_path):
        raise RuntimeError(
            f"Task {task['ralph_task_id']} returned DONE but left uncommitted target repo changes."
        )


def _parse_arguments(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run Ralph task loops with sliced plan context.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    run_parser = subparsers.add_parser("run", help="Run the Ralph loop for one job.")
    run_parser.add_argument("--repo-path", required=True)
    run_parser.add_argument("--ralph-home-path", required=True)
    run_parser.add_argument("--job-name", required=True)
    run_parser.add_argument("--max-iterations", type=int, default=DEFAULT_MAX_ITERATIONS)
    run_parser.add_argument("--agent-backend", choices=["codex", "claude", "cursor"], default="codex")
    run_parser.add_argument("--agent-command")
    run_parser.add_argument(
        "--skip-ralph-sandbox",
        action="store_true",
        help=(
            "Run the agent directly with writable Git metadata and the existing "
            "config directory instead of Ralph's Bubblewrap sandbox."
        ),
    )
    run_parser.add_argument(
        "--python-venv",
        help="Python venv mounted into agents with its bin directory first on PATH. Defaults to $VIRTUAL_ENV.",
    )
    run_parser.add_argument(
        "--no-tee-agent-output",
        action="store_false",
        dest="tee_agent_output",
        help="Stream the agent transcript to this terminal while also saving agent-output.txt.",
    )
    run_parser.add_argument(
        "--ask-for-review",
        action="store_true",
        help="Pause after each completed task so a human can review before Ralph selects the next task.",
    )
    run_parser.add_argument(
        "--allow-dirty-start",
        action="store_true",
        help="Resume work from existing uncommitted target repository changes.",
    )
    run_parser.set_defaults(tee_agent_output=True)

    validate_parser = subparsers.add_parser("validate", help="Validate one Ralph job without launching workers.")
    validate_parser.add_argument("--ralph-home-path", required=True)
    validate_parser.add_argument("--job-name", required=True)
    validate_parser.add_argument("--repo-path")
    validate_parser.add_argument(
        "--allow-dirty-start",
        action="store_true",
        help="Accept existing uncommitted target repository changes during validation.",
    )

    smoke_parser = subparsers.add_parser("smoke-test", help="Verify the agent sandbox contract.")
    smoke_parser.add_argument("--repo-path", required=True)
    smoke_parser.add_argument("--agent-backend", choices=["codex", "claude", "cursor"], default="codex")
    smoke_parser.add_argument("--agent-command")
    smoke_parser.add_argument("--python-venv")

    return parser.parse_args(argv)


def _resolve_repo_path(repo_path: str) -> Path:
    return Path(repo_path).expanduser().resolve()


def _resolve_ralph_home_path(ralph_home_path: str) -> Path:
    return Path(ralph_home_path).expanduser().resolve()


def _find_ralph_job(job_name: str, ralph_home_path: Path) -> RalphJob:
    job_path = ralph_home_path / "jobs" / job_name
    return RalphJob(
        job_name=job_name,
        job_path=job_path,
        plan_path=job_path / "PLAN.md",
        ledger_path=job_path / "ledger.yaml",
        tasks_path=job_path / "tasks",
    )


def _prepare_job_directories(job: RalphJob) -> None:
    job.tasks_path.mkdir(parents=True, exist_ok=True)
    _require_ralph_job_files(job)


def _require_ralph_job_files(job: RalphJob) -> None:
    if not job.plan_path.is_file():
        raise FileNotFoundError(f"Missing Ralph plan: {job.plan_path}")
    if not job.ledger_path.is_file():
        raise FileNotFoundError(f"Missing Ralph ledger: {job.ledger_path}")


def _refuse_unsafe_starting_state(
    repo_path: Path,
    job: RalphJob,
    *,
    allow_dirty_start: bool = False,
) -> None:
    if not repo_path.is_dir():
        raise FileNotFoundError(f"Target repo does not exist: {repo_path}")
    if _is_path_inside(child_path=job.job_path, parent_path=repo_path):
        raise RuntimeError(f"Ralph job path must not be inside target repo: {job.job_path}")
    reject_worker_visible_path_that_overlaps_hidden_state(
        path=repo_path,
        role="Target repo",
    )
    for control_path_name in PRIVATE_CONTROL_PATH_NAMES:
        if _repo_contains_private_control_path(repo_path, control_path_name):
            raise RuntimeError(f"Refusing to run because {control_path_name} exists under the target repo.")
    if _repo_contains_private_plan_path(repo_path):
        raise RuntimeError("Refusing to run because Ralph PLAN.md and ledger.yaml exist under the target repo.")
    if not allow_dirty_start and _read_git_status(repo_path):
        raise RuntimeError("Refusing to run because the target repo is dirty.")


def _run_agent(
    repo_path: Path,
    task: dict[str, Any],
    prompt: str,
    agent_backend_name: str,
    agent_command: str | None,
    python_venv_path: Path | None,
    output_path: Path,
    tee_output: bool,
    task_path: Path | None = None,
    skip_ralph_sandbox: bool = False,
    tool_virtual_environment_path: Path | None = None,
    controller_path: str | None = None,
) -> AgentResult:
    _write_text(output_path, "")
    agent_backend = select_agent_backend(
        agent_backend_name=agent_backend_name,
        agent_command=agent_command,
    )
    if skip_ralph_sandbox:
        return _run_direct_agent(
            repo_path=repo_path,
            prompt=prompt,
            output_path=output_path,
            tee_output=tee_output,
            agent_backend=agent_backend,
            tool_virtual_environment_path=tool_virtual_environment_path,
            controller_path=controller_path,
        )
    return _run_sandboxed_agent(
        repo_path=repo_path,
        prompt=prompt,
        output_path=output_path,
        tee_output=tee_output,
        agent_backend=agent_backend,
        python_venv_path=python_venv_path,
        task_path=task_path,
    )


def _run_sandboxed_agent(
    repo_path: Path,
    prompt: str,
    output_path: Path,
    tee_output: bool,
    agent_backend: AgentBackend,
    python_venv_path: Path | None,
    task_path: Path | None,
) -> AgentResult:
    with prepare_agent_backend_for_worker(agent_backend) as worker_agent_backend:
        command = build_bwrap_agent_command(
            repo_path=repo_path,
            agent_backend=worker_agent_backend,
            python_venv_path=python_venv_path,
        )
        with agent_permission_setup(
            agent_backend=worker_agent_backend,
            task_path=task_path,
        ):
            return _run_agent_command(
                command=command,
                prompt=prompt,
                output_path=output_path,
                tee_output=tee_output,
                agent_backend=worker_agent_backend,
            )


def _run_direct_agent(
    repo_path: Path,
    prompt: str,
    output_path: Path,
    tee_output: bool,
    agent_backend: AgentBackend,
    tool_virtual_environment_path: Path | None,
    controller_path: str | None,
) -> AgentResult:
    command = _build_direct_agent_command(
        repo_path=repo_path,
        agent_backend=agent_backend,
        tool_virtual_environment_path=tool_virtual_environment_path,
        controller_path=controller_path,
    )
    return _run_agent_command(
        command=command,
        prompt=prompt,
        output_path=output_path,
        tee_output=tee_output,
        agent_backend=agent_backend,
    )


def _build_direct_agent_command(
    repo_path: Path,
    agent_backend: AgentBackend,
    tool_virtual_environment_path: Path | None,
    controller_path: str | None,
) -> list[str]:
    if agent_backend.backend_name == "codex":
        if tool_virtual_environment_path is None or controller_path is None:
            raise ValueError(
                "Direct Codex workers require the controller tool environment."
            )
        return build_direct_codex_command(
            agent_backend=agent_backend,
            repo_path=repo_path,
            tool_virtual_environment_path=tool_virtual_environment_path,
            controller_path=controller_path,
        )
    if agent_backend.backend_name == "claude":
        return build_direct_claude_command(
            agent_backend=agent_backend,
            repo_path=repo_path,
        )
    if agent_backend.backend_name == "cursor":
        return build_direct_cursor_command(
            agent_backend=agent_backend,
            repo_path=repo_path,
        )
    raise ValueError(f"--skip-ralph-sandbox is not supported for backend: {agent_backend.backend_name}")
def _run_agent_command(
    command: list[str],
    prompt: str,
    output_path: Path,
    tee_output: bool,
    agent_backend: AgentBackend,
) -> AgentResult:
    completed_process = run_command_and_save_agent_transcripts(
        command=command,
        input_text=prompt,
        output_path=output_path,
        agent_backend=agent_backend,
        tee_output=tee_output,
    )

    if completed_process.returncode != 0:
        raise RuntimeError(_build_agent_failure_message(
            exit_code=completed_process.returncode,
            output_path=output_path,
            agent_backend_name=agent_backend.backend_name,
        ))
    output = extract_agent_result_text(
        agent_backend=agent_backend,
        raw_output=completed_process.stdout or "",
    )
    promise = _parse_agent_promise(output)
    return AgentResult(promise=promise, output=output)


def _build_agent_failure_message(exit_code: int, output_path: Path, agent_backend_name: str) -> str:
    message = f"Agent failed with exit code {exit_code}. See readable transcript: {output_path}"
    if agent_backend_name == "claude":
        message += f"\nRaw Claude stream: {output_path.with_suffix('.raw.jsonl')}"
    return message


def _read_committed_files(repo_path: Path, commit_hash: str) -> list[str]:
    changed_files_output = _run_git(repo_path, "show", "--name-status", "--format=", commit_hash).strip()
    if not changed_files_output:
        return []
    return changed_files_output.splitlines()


def _read_yaml_file(yaml_path: Path) -> dict[str, Any]:
    value = yaml.safe_load(yaml_path.read_text())
    if not isinstance(value, dict):
        raise ValueError(f"Expected YAML mapping in {yaml_path}")
    return value


def _write_yaml_file(yaml_path: Path, value: dict[str, Any]) -> None:
    yaml_path.write_text(_dump_yaml(value))


def _dump_yaml(value: Any) -> str:
    return yaml.safe_dump(value, sort_keys=False)


def _mark_task_done(ledger: dict[str, Any], task_id: str) -> dict[str, Any]:
    updated_ledger = dict(ledger)
    updated_tasks = []
    for task in read_tasks_from_ledger(ledger):
        updated_task = dict(task)
        if updated_task["ralph_task_id"] == task_id:
            updated_task["status"] = "done"
            updated_task["completed_at"] = dt.datetime.now(dt.timezone.utc).isoformat()
        updated_tasks.append(updated_task)
    updated_ledger["tasks"] = updated_tasks
    return updated_ledger


def _mark_task_stopped(
    ledger: dict[str, Any],
    task_id: str,
    promise: str,
) -> dict[str, Any]:
    status_by_promise = {
        "BLOCKED": "blocked",
        "ABORT": "aborted",
    }
    updated_ledger = copy.deepcopy(ledger)
    for task in read_tasks_from_ledger(updated_ledger):
        if task["ralph_task_id"] == task_id:
            task["status"] = status_by_promise[promise]
            return updated_ledger
    raise ValueError(f"Unknown Ralph task id: {task_id}")


def _parse_agent_promise(output: str) -> str:
    for raw_line in reversed(output.splitlines()):
        match = PROMISE_LINE_PATTERN.match(raw_line.strip())
        if match:
            return match.group(1)

    promises = PROMISE_PATTERN.findall(output)
    raise RuntimeError(f"Expected one final agent promise line, found {len(promises)} promise tag(s).")


def _create_task_directory(tasks_path: Path, task_id: str) -> Path:
    timestamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    task_path = tasks_path / f"{_build_safe_dirname(task_id)}_{timestamp}"
    task_path.mkdir(parents=True, exist_ok=False)
    return task_path


def _build_safe_dirname(value: str) -> str:
    safe_value = re.sub(r"[^A-Za-z0-9_.-]+", "-", value).strip("-")
    if not safe_value:
        raise ValueError("Directory name cannot be empty after sanitization.")
    return safe_value


def _repo_contains_private_control_path(repo_path: Path, name: str) -> bool:
    return any(
        path.name == name and not _is_public_ralph_example_path(repo_path=repo_path, path=path)
        for path in repo_path.rglob(name)
    )


def _repo_contains_private_plan_path(repo_path: Path) -> bool:
    return any(
        path.name == "PLAN.md"
        and path.with_name("ledger.yaml").exists()
        and not _is_public_ralph_example_path(repo_path=repo_path, path=path)
        for path in repo_path.rglob("PLAN.md")
    )


def _is_public_ralph_example_path(repo_path: Path, path: Path) -> bool:
    public_examples_path = repo_path / "ralph" / "examples"
    return path.resolve().is_relative_to(public_examples_path.resolve())


def _is_path_inside(child_path: Path, parent_path: Path) -> bool:
    return child_path.resolve().is_relative_to(parent_path.resolve())


def _read_git_status(repo_path: Path) -> str:
    return _run_git(repo_path, "status", "--short").strip()


def _run_git(repo_path: Path, *arguments: str) -> str:
    completed_process = subprocess.run(
        ["git", *arguments],
        cwd=repo_path,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )
    if completed_process.returncode != 0:
        raise RuntimeError(f"git {' '.join(arguments)} failed:\n{completed_process.stdout}")
    return completed_process.stdout


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


def _write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
