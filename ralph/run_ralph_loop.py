from __future__ import annotations

import argparse
import datetime as dt
import re
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
    build_worker_allowed_bash_commands,
    extract_agent_result_text,
    run_command_and_tee_output,
    select_agent_backend_config,
)
from ralph.codex_backend import recover_interrupted_codex_rules
from ralph.notion import (
    log_completed_worker_to_notion,
    log_failed_verification_to_notion,
    log_worker_promise_to_notion,
    prepare_notion_task_before_worker_runs_task,
)
from ralph.plan_selection import (
    TaskSelection,
    read_tasks_from_ledger,
    select_next_task_from_plan_and_ledger,
)
from ralph.prompt import render_agent_prompt
from ralph.sandbox import (
    backend_permission_setup,
    build_bwrap_agent_command,
    reject_worker_visible_path_that_overlaps_hidden_state,
    resolve_python_venv_path,
    resolve_ralph_home_path,
    run_agent_visibility_smoke_test,
)


DEFAULT_MAX_ITERATIONS = 10
PROMISE_PATTERN = re.compile(r"<promise>(DONE|BLOCKED|ABORT)</promise>")
PROMISE_LINE_PATTERN = re.compile(r"^<promise>(DONE|BLOCKED|ABORT)</promise>$")
WORKER_VERIFICATION_BLOCK_PATTERN = re.compile(
    r"^RALPH_VERIFICATION_BEGIN\n(?P<verification_output>.*?)^RALPH_VERIFICATION_END$",
    re.DOTALL | re.MULTILINE,
)
WORKER_COMMIT_LINE_PATTERN = re.compile(r"^RALPH_COMMIT (?P<commit_hash>[0-9a-f]{40})$", re.MULTILINE)

PRIVATE_CONTROL_PATH_NAMES = frozenset({"PLAN.md", "ledger.yaml", ".ralph"})


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
    if arguments.command == "smoke-test":
        run_agent_visibility_smoke_test(
            repo_path=_resolve_repo_path(arguments.repo_path),
            agent_backend=arguments.agent_backend,
            agent_command=arguments.agent_command,
            python_venv_path=resolve_python_venv_path(arguments.python_venv),
        )
        return
    raise SystemExit(f"Unknown command: {arguments.command}")


def _run_ralph_loop(arguments: argparse.Namespace) -> None:
    repo_path = _resolve_repo_path(arguments.repo_path)
    python_venv_path = resolve_python_venv_path(arguments.python_venv)
    job = _find_ralph_job(arguments.job_name)
    _prepare_job_directories(job)
    _refuse_unsafe_starting_state(repo_path, job)
    recover_interrupted_codex_rules(job)
    run_agent_visibility_smoke_test(
        repo_path=repo_path,
        agent_backend=arguments.agent_backend,
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

        task_path = _create_task_directory(job.tasks_path, selection.task["id"])
        print(f"Ralph task: {task_path}")
        ledger, selection = prepare_notion_task_before_worker_runs_task(
            job=job,
            ledger=ledger,
            selection=selection,
            task_path=task_path,
        )
        prompt = render_agent_prompt(
            repo_path=repo_path,
            ledger=ledger,
            selection=selection,
            python_venv_path=python_venv_path,
        )
        agent_result = _run_agent(
            repo_path=repo_path,
            task=selection.task,
            prompt=prompt,
            agent_backend=arguments.agent_backend,
            agent_command=arguments.agent_command,
            python_venv_path=python_venv_path,
            output_path=task_path / "agent-output.txt",
            tee_output=arguments.tee_agent_output,
            task_path=task_path,
        )
        _write_text(task_path / "promise.txt", agent_result.promise)

        if agent_result.promise != "DONE":
            log_worker_promise_to_notion(
                selection=selection,
                task_path=task_path,
                promise=agent_result.promise,
                agent_output=agent_result.output,
            )
            print(f"Agent stopped with {agent_result.promise}. See {task_path}")
            return

        try:
            commit_hash = _accept_worker_completed_task(
                repo_path=repo_path,
                job=job,
                ledger=ledger,
                selection=selection,
                task_path=task_path,
                agent_output=agent_result.output,
            )
        except Exception:
            log_failed_verification_to_notion(selection=selection, task_path=task_path)
            raise
        log_completed_worker_to_notion(
            selection=selection,
            task_path=task_path,
            changed_files=_read_committed_files(repo_path=repo_path, commit_hash=commit_hash),
            commit_hash=commit_hash,
        )
        print(f"Completed {selection.task['id']}: {commit_hash}")

    raise SystemExit(f"Reached max iterations: {arguments.max_iterations}")


def _accept_worker_completed_task(
    repo_path: Path,
    job: RalphJob,
    ledger: dict[str, Any],
    selection: TaskSelection,
    task_path: Path,
    agent_output: str,
) -> str:
    verification_output = _extract_worker_verification_output(
        task=selection.task,
        agent_output=agent_output,
    )
    commit_hash = _extract_worker_commit_hash(agent_output)

    _write_text(task_path / "verification-output.txt", verification_output)
    _write_text(task_path / "commit.txt", commit_hash)
    _validate_worker_commit_matches_repo_state(
        repo_path=repo_path,
        task=selection.task,
        commit_hash=commit_hash,
    )

    advanced_ledger = _mark_task_done(ledger, selection.task["id"])
    _write_yaml_file(job.ledger_path, advanced_ledger)
    return commit_hash


def _extract_worker_verification_output(task: dict[str, Any], agent_output: str) -> str:
    matches = WORKER_VERIFICATION_BLOCK_PATTERN.findall(agent_output)
    if len(matches) != 1:
        raise RuntimeError("Worker DONE must include one RALPH_VERIFICATION_BEGIN block.")

    verification_output = matches[0].strip()
    _validate_worker_verification_output_mentions_required_commands(
        task=task,
        verification_output=verification_output,
    )
    return verification_output


def _validate_worker_verification_output_mentions_required_commands(
    task: dict[str, Any],
    verification_output: str,
) -> None:
    missing_commands = [
        command
        for command in task.get("verification_commands") or []
        if f"$ {command}" not in verification_output
    ]
    if missing_commands:
        raise RuntimeError(
            f"Worker DONE did not include verification transcript entries for: {missing_commands}"
        )


def _extract_worker_commit_hash(agent_output: str) -> str:
    matches = WORKER_COMMIT_LINE_PATTERN.findall(agent_output)
    if len(matches) != 1:
        raise RuntimeError("Worker DONE must include exactly one RALPH_COMMIT line with the committed HEAD.")
    return matches[0]


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

    expected_commit_subject = f"Ralph: {task['id']} {task['title']}"
    actual_commit_subject = _run_git(repo_path, "log", "--format=%s", "-1", commit_hash).strip()
    if actual_commit_subject != expected_commit_subject:
        raise RuntimeError(
            f"Worker commit subject must be {expected_commit_subject!r}, got {actual_commit_subject!r}."
        )

    if _read_git_status(repo_path):
        raise RuntimeError(f"Task {task['id']} returned DONE but left uncommitted target repo changes.")


def _parse_arguments(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run Ralph task loops with sliced plan context.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    run_parser = subparsers.add_parser("run", help="Run the Ralph loop for one job.")
    run_parser.add_argument("--repo-path", required=True)
    run_parser.add_argument("--job-name", required=True)
    run_parser.add_argument("--max-iterations", type=int, default=DEFAULT_MAX_ITERATIONS)
    run_parser.add_argument("--agent-backend", choices=["codex", "claude"], default="codex")
    run_parser.add_argument("--agent-command")
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
    run_parser.set_defaults(tee_agent_output=True)

    smoke_parser = subparsers.add_parser("smoke-test", help="Verify the agent sandbox contract.")
    smoke_parser.add_argument("--repo-path", required=True)
    smoke_parser.add_argument("--agent-backend", choices=["codex", "claude"], default="codex")
    smoke_parser.add_argument("--agent-command")
    smoke_parser.add_argument("--python-venv")

    return parser.parse_args(argv)


def _resolve_repo_path(repo_path: str) -> Path:
    return Path(repo_path).expanduser().resolve()


def _find_ralph_job(job_name: str) -> RalphJob:
    job_path = resolve_ralph_home_path() / "jobs" / job_name
    return RalphJob(
        job_name=job_name,
        job_path=job_path,
        plan_path=job_path / "PLAN.md",
        ledger_path=job_path / "ledger.yaml",
        tasks_path=job_path / "tasks",
    )


def _prepare_job_directories(job: RalphJob) -> None:
    job.tasks_path.mkdir(parents=True, exist_ok=True)
    if not job.plan_path.is_file():
        raise FileNotFoundError(f"Missing Ralph plan: {job.plan_path}")
    if not job.ledger_path.is_file():
        raise FileNotFoundError(f"Missing Ralph ledger: {job.ledger_path}")


def _refuse_unsafe_starting_state(repo_path: Path, job: RalphJob) -> None:
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
    if _read_git_status(repo_path):
        raise RuntimeError("Refusing to run because the target repo is dirty.")


def _run_agent(
    repo_path: Path,
    task: dict[str, Any],
    prompt: str,
    agent_backend: str,
    agent_command: str | None,
    python_venv_path: Path | None,
    output_path: Path,
    tee_output: bool,
    task_path: Path | None = None,
) -> AgentResult:
    _write_text(output_path, "")
    backend_config = select_agent_backend_config(
        agent_backend=agent_backend,
        agent_command=agent_command,
    )
    allowed_bash_commands = build_worker_allowed_bash_commands(task)
    command = build_bwrap_agent_command(
        repo_path=repo_path,
        backend_config=backend_config,
        python_venv_path=python_venv_path,
        allowed_bash_commands=allowed_bash_commands,
    )

    with backend_permission_setup(
        backend_config=backend_config,
        allowed_bash_commands=allowed_bash_commands,
        task_path=task_path,
    ):
        return _run_agent_command(
            command=command,
            prompt=prompt,
            output_path=output_path,
            tee_output=tee_output,
            backend_config=backend_config,
        )


def _run_agent_command(
    command: list[str],
    prompt: str,
    output_path: Path,
    tee_output: bool,
    backend_config: AgentBackend,
) -> AgentResult:
    if tee_output:
        completed_process = run_command_and_tee_output(
            command=command,
            input_text=prompt,
            output_path=output_path,
        )
    else:
        completed_process = subprocess.run(
            command,
            input=prompt,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            check=False,
        )
        _write_text(output_path, completed_process.stdout)

    output = extract_agent_result_text(
        backend_config=backend_config,
        raw_output=completed_process.stdout or "",
    )
    if completed_process.returncode != 0:
        raise RuntimeError(f"Agent failed with exit code {completed_process.returncode}. See {output_path}")
    promise = _parse_agent_promise(output)
    return AgentResult(promise=promise, output=output)


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
        if updated_task["id"] == task_id:
            updated_task["status"] = "done"
            updated_task["completed_at"] = dt.datetime.now(dt.timezone.utc).isoformat()
        updated_tasks.append(updated_task)
    updated_ledger["tasks"] = updated_tasks
    return updated_ledger


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


if __name__ == "__main__":
    main()
