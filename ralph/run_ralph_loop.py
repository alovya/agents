from __future__ import annotations

import argparse
import copy
import datetime as dt
import json
import os
import re
import shlex
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


DEFAULT_RALPH_HOME_PATH = Path("/workspace/.ralph")
DEFAULT_NOTION_TRACKER_STATE_PATH = Path("/workspace/.notion-task-tracker/notion_tasks_tree.json")
WORKER_HOME_PATH = Path("/tmp/ralph-worker-home")
WORKER_TEMP_PATH = Path("/tmp/ralph-worker-tmp")
WORKER_AGENT_BINARY_PATH = Path("/tmp/ralph-agent-bin/agent")
DEFAULT_MAX_ITERATIONS = 10
PROMISE_PATTERN = re.compile(r"<promise>(DONE|BLOCKED|ABORT)</promise>")
PROMISE_LINE_PATTERN = re.compile(r"^<promise>(DONE|BLOCKED|ABORT)</promise>$")
WORKER_VERIFICATION_BLOCK_PATTERN = re.compile(
    r"^RALPH_VERIFICATION_BEGIN\n(?P<verification_output>.*?)^RALPH_VERIFICATION_END$",
    re.DOTALL | re.MULTILINE,
)
WORKER_COMMIT_LINE_PATTERN = re.compile(r"^RALPH_COMMIT (?P<commit_hash>[0-9a-f]{40})$", re.MULTILINE)
ALOVYA_TASK_ID_PATTERN = re.compile(r"^ALOVYA-(?P<ticket_number>\d+)$")
PLAN_COMMAND_ITEM_PATTERN = re.compile(r"^\s*-\s+(?P<command>.+?)\s*$")
TASK_BLOCK_PATTERN = re.compile(
    r"<!--\s*ralph-task:start\s+(?P<task_id>[A-Za-z0-9_.-]+)\s*-->\n"
    r"(?P<body>.*?)"
    r"<!--\s*ralph-task:end\s+(?P=task_id)\s*-->",
    re.DOTALL,
)
SHARED_BLOCK_PATTERN = re.compile(
    r"<!--\s*ralph-shared:start\s*-->\n"
    r"(?P<body>.*?)"
    r"<!--\s*ralph-shared:end\s*-->",
    re.DOTALL,
)
ALWAYS_ALLOWED_WORKER_BASH_COMMANDS = [
    "git status",
    "git status --short",
    "git diff",
    "git diff --staged",
    "git ls-files",
    "git add .",
    "git commit --no-verify -m *",
    "git rev-parse HEAD",
]


@dataclass(frozen=True)
class RalphJob:
    job_name: str
    job_path: Path
    plan_path: Path
    ledger_path: Path
    tasks_path: Path


@dataclass(frozen=True)
class TaskSelection:
    task: dict[str, Any]
    shared_plan_context: str
    active_task_plan_context: str


@dataclass(frozen=True)
class AgentResult:
    promise: str
    output: str


@dataclass(frozen=True)
class AgentBackendConfig:
    backend_name: str
    command_name: str
    agent_home_path: Path
    agent_home_environment_variable: str


def main(argv: list[str] | None = None) -> None:
    arguments = _parse_arguments(argv)
    if arguments.command == "run":
        _run_ralph_loop(arguments)
        return
    if arguments.command == "smoke-test":
        _run_agent_visibility_smoke_test(
            repo_path=_resolve_repo_path(arguments.repo_path),
            agent_backend=arguments.agent_backend,
            agent_command=arguments.agent_command,
            python_venv_path=_resolve_python_venv_path(arguments.python_venv),
        )
        return
    raise SystemExit(f"Unknown command: {arguments.command}")


def _run_ralph_loop(arguments: argparse.Namespace) -> None:
    repo_path = _resolve_repo_path(arguments.repo_path)
    python_venv_path = _resolve_python_venv_path(arguments.python_venv)
    job = _find_ralph_job(arguments.job_name)
    _prepare_job_directories(job)
    _refuse_unsafe_starting_state(repo_path, job)
    _run_agent_visibility_smoke_test(
        repo_path=repo_path,
        agent_backend=arguments.agent_backend,
        agent_command=arguments.agent_command,
        python_venv_path=python_venv_path,
    )

    for _ in range(arguments.max_iterations):
        ledger = _read_yaml_file(job.ledger_path)
        plan_text = job.plan_path.read_text()
        selection = _select_next_task_from_plan_and_ledger(ledger, plan_text)
        if selection is None:
            print("No runnable Ralph tasks remain.")
            return

        task_path = _create_task_directory(job.tasks_path, selection.task["id"])
        print(f"Ralph task: {task_path}")
        ledger, selection = _prepare_notion_task_for_worker_launch(
            job=job,
            ledger=ledger,
            selection=selection,
            task_path=task_path,
        )
        prompt = _render_agent_prompt(
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
        )
        _write_text(task_path / "promise.txt", agent_result.promise)

        if agent_result.promise != "DONE":
            _log_worker_promise_to_notion(
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
            _log_failed_verification_to_notion(selection=selection, task_path=task_path)
            raise
        _log_completed_worker_to_notion(
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


def _prepare_notion_task_for_worker_launch(
    job: RalphJob,
    ledger: dict[str, Any],
    selection: TaskSelection,
    task_path: Path,
) -> tuple[dict[str, Any], TaskSelection]:
    if not _task_has_planned_notion_pairing(selection.task):
        return ledger, selection

    ledger_with_materialised_task = _materialise_planned_notion_task_before_worker_launch(
        job=job,
        ledger=ledger,
        task=selection.task,
        task_path=task_path,
    )
    refreshed_selection = _refresh_task_selection_from_ledger(
        ledger=ledger_with_materialised_task,
        selection=selection,
    )
    _log_slice_start_to_notion(selection=refreshed_selection, task_path=task_path)
    return ledger_with_materialised_task, refreshed_selection


def _materialise_planned_notion_task_before_worker_launch(
    job: RalphJob,
    ledger: dict[str, Any],
    task: dict[str, Any],
    task_path: Path,
) -> dict[str, Any]:
    notion_task = task["notion_task"]
    if notion_task.get("materialized_task_id"):
        return ledger

    related_notion_task_id = _resolve_related_notion_task_id(
        tasks=_read_tasks_from_ledger(ledger),
        related_to=notion_task["related_to"],
    )
    materialised_task_id = _create_planned_notion_task(
        relationship=notion_task["relationship"],
        related_notion_task_id=related_notion_task_id,
        title=notion_task["title"],
        task_path=task_path,
    )
    updated_ledger = _record_materialised_notion_task_id(
        ledger=ledger,
        task_id=task["id"],
        materialised_task_id=materialised_task_id,
    )
    _write_yaml_file(job.ledger_path, updated_ledger)
    return updated_ledger


def _log_slice_start_to_notion(selection: TaskSelection, task_path: Path) -> None:
    notion_task_id = _materialised_notion_task_id_from_task(selection.task)
    if notion_task_id is None:
        return

    _append_notion_task_log(
        notion_task_id=notion_task_id,
        task_path=task_path,
        log_name="slice-start",
        content={
            "subheading": f"Ralph {selection.task['id']} started",
            "blocks": [
                {"type": "paragraph", "text": f"Goal: {selection.task['title']}"},
                {"type": "code", "language": "yaml", "text": _dump_yaml({
                    "ralph_task_id": selection.task["id"],
                    "touchable_paths": selection.task.get("touchable_paths") or [],
                    "verification_commands": selection.task.get("verification_commands") or [],
                    "constraints": _worker_launch_constraints(),
                })},
            ],
        },
    )


def _log_worker_promise_to_notion(
    selection: TaskSelection,
    task_path: Path,
    promise: str,
    agent_output: str,
) -> None:
    notion_task_id = _materialised_notion_task_id_from_task(selection.task)
    if notion_task_id is None:
        return

    _append_notion_task_log(
        notion_task_id=notion_task_id,
        task_path=task_path,
        log_name=f"worker-{promise.lower()}",
        content={
            "subheading": f"Worker returned {promise}",
            "blocks": [
                {"type": "paragraph", "text": f"Ralph task {selection.task['id']} stopped before verification."},
                {"type": "code", "language": "text", "text": agent_output},
                {"type": "paragraph", "text": f"Transcript path: {task_path / 'agent-output.txt'}"},
            ],
        },
    )


def _log_failed_verification_to_notion(selection: TaskSelection, task_path: Path) -> None:
    notion_task_id = _materialised_notion_task_id_from_task(selection.task)
    if notion_task_id is None:
        return

    _append_notion_task_log(
        notion_task_id=notion_task_id,
        task_path=task_path,
        log_name="verification-failed",
        content={
            "subheading": "Verification failed",
            "blocks": [
                {"type": "paragraph", "text": f"Ralph task {selection.task['id']} returned DONE, then verification failed."},
                {
                    "type": "code",
                    "language": "text",
                    "text": _read_text_if_file_exists(task_path / "verification-output.txt"),
                },
                {"type": "paragraph", "text": f"Transcript path: {task_path / 'agent-output.txt'}"},
            ],
        },
    )


def _log_completed_worker_to_notion(
    selection: TaskSelection,
    task_path: Path,
    changed_files: list[str],
    commit_hash: str,
) -> None:
    notion_task_id = _materialised_notion_task_id_from_task(selection.task)
    if notion_task_id is None:
        return

    _append_notion_task_log(
        notion_task_id=notion_task_id,
        task_path=task_path,
        log_name="worker-completed",
        content={
            "subheading": f"Ralph {selection.task['id']} completed",
            "blocks": [
                {"type": "paragraph", "text": f"Worker promise: {_read_text_if_file_exists(task_path / 'promise.txt').strip()}"},
                {"type": "code", "language": "text", "text": "\n".join(changed_files) or "No changed files were captured before commit."},
                {
                    "type": "code",
                    "language": "text",
                    "text": _read_text_if_file_exists(task_path / "verification-output.txt"),
                },
                {"type": "paragraph", "text": f"Commit hash: {commit_hash}"},
                {"type": "paragraph", "text": f"Transcript path: {task_path / 'agent-output.txt'}"},
                {"type": "paragraph", "text": "Unresolved risks: none recorded by the controller."},
            ],
        },
    )


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


def _resolve_ralph_home_path() -> Path:
    configured_path = os.environ.get("RALPH_HOME")
    if configured_path:
        return Path(configured_path).expanduser().resolve()
    return DEFAULT_RALPH_HOME_PATH


def _find_ralph_job(job_name: str) -> RalphJob:
    job_path = _resolve_ralph_home_path() / "jobs" / job_name
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
    _refuse_explicit_worker_mount_that_overlaps_sensitive_hidden_paths(
        path=repo_path,
        role="Target repo",
    )
    if _contains_private_control_path_named_under_repo(repo_path, "PLAN.md"):
        raise RuntimeError("Refusing to run because PLAN.md exists under the target repo.")
    if _contains_private_control_path_named_under_repo(repo_path, "ledger.yaml"):
        raise RuntimeError("Refusing to run because ledger.yaml exists under the target repo.")
    if _contains_private_control_path_named_under_repo(repo_path, ".ralph"):
        raise RuntimeError("Refusing to run because .ralph exists under the target repo.")
    if _read_git_status(repo_path):
        raise RuntimeError("Refusing to run because the target repo is dirty.")


def _select_next_task_from_plan_and_ledger(
    ledger: dict[str, Any],
    plan_text: str,
) -> TaskSelection | None:
    tasks = _read_tasks_from_ledger(ledger)
    shared_plan_context = _extract_shared_plan_context(plan_text)
    task_plan_contexts = _extract_task_plan_contexts(plan_text)
    task_command_contracts = _derive_task_command_contracts_from_plan(task_plan_contexts)
    _validate_plan_and_ledger_match(tasks, task_plan_contexts)

    completed_task_ids = {task["id"] for task in tasks if task.get("status") == "done"}
    for task in tasks:
        if task.get("status") != "pending":
            continue
        depends_on = task.get("depends_on") or []
        if all(task_id in completed_task_ids for task_id in depends_on):
            task_with_plan_commands = _attach_plan_command_contract_to_task(
                task=task,
                allowed_bash_commands=task_command_contracts[task["id"]]["allowed_bash_commands"],
                verification_commands=task_command_contracts[task["id"]]["verification_commands"],
            )
            return TaskSelection(
                task=task_with_plan_commands,
                shared_plan_context=shared_plan_context,
                active_task_plan_context=task_plan_contexts[task["id"]],
            )
    return None


def _render_agent_prompt(
    repo_path: Path,
    ledger: dict[str, Any],
    selection: TaskSelection,
    python_venv_path: Path | None,
) -> str:
    prompt_template_path = Path(__file__).resolve().parent / "PROMPT.md"
    prompt_template = prompt_template_path.read_text()
    visible_ledger = _remove_plan_like_fields(ledger)
    active_task = _remove_plan_like_fields(selection.task)

    return prompt_template.format(
        repo_path=repo_path,
        tool_environment_context=_describe_tool_environment(python_venv_path),
        active_task_yaml=_dump_yaml(active_task),
        visible_ledger_yaml=_dump_yaml(visible_ledger),
        shared_plan_context=selection.shared_plan_context.strip(),
        active_task_plan_context=selection.active_task_plan_context.strip(),
    )


def _run_agent(
    repo_path: Path,
    task: dict[str, Any],
    prompt: str,
    agent_backend: str,
    agent_command: str | None,
    python_venv_path: Path | None,
    output_path: Path,
    tee_output: bool,
) -> AgentResult:
    _write_text(output_path, "")
    backend_config = _select_agent_backend_config(
        agent_backend=agent_backend,
        agent_command=agent_command,
    )
    command = _build_bwrap_agent_command(
        repo_path=repo_path,
        backend_config=backend_config,
        python_venv_path=python_venv_path,
        allowed_bash_commands=_build_worker_allowed_bash_commands(task),
    )
    if tee_output:
        completed_process = _run_command_and_tee_output(
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

    output = completed_process.stdout or ""
    if completed_process.returncode != 0:
        raise RuntimeError(f"Agent failed with exit code {completed_process.returncode}. See {output_path}")
    promise = _parse_agent_promise(output)
    return AgentResult(promise=promise, output=output)


def _run_command_and_tee_output(
    command: list[str],
    input_text: str,
    output_path: Path,
) -> subprocess.CompletedProcess[str]:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_chunks: list[str] = []
    with output_path.open("w", encoding="utf-8") as output_file:
        process = subprocess.Popen(
            command,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )

        if process.stdin is None or process.stdout is None:
            raise RuntimeError("Could not open agent stdin/stdout pipes.")

        process.stdin.write(input_text)
        process.stdin.close()

        for line in process.stdout:
            print(line, end="", flush=True)
            output_file.write(line)
            output_file.flush()
            output_chunks.append(line)

    return_code = process.wait()
    output = "".join(output_chunks)
    return subprocess.CompletedProcess(
        args=command,
        returncode=return_code,
        stdout=output,
    )


def _run_agent_visibility_smoke_test(
    repo_path: Path,
    agent_backend: str,
    agent_command: str | None,
    python_venv_path: Path | None,
) -> None:
    if not repo_path.is_dir():
        raise FileNotFoundError(f"Target repo does not exist: {repo_path}")
    _refuse_explicit_worker_mount_that_overlaps_sensitive_hidden_paths(
        path=repo_path,
        role="Target repo",
    )
    backend_config = _select_agent_backend_config(
        agent_backend=agent_backend,
        agent_command=agent_command,
    )
    prompt = _build_agent_visibility_smoke_test_prompt(
        repo_path=repo_path,
        backend_config=backend_config,
        python_venv_path=python_venv_path,
    )
    allowed_bash_commands = [_build_agent_visibility_smoke_test_agent_command(
        repo_path=repo_path,
        backend_config=backend_config,
        python_venv_path=python_venv_path,
    )]
    command = _build_bwrap_agent_command(
        repo_path=repo_path,
        backend_config=backend_config,
        python_venv_path=python_venv_path,
        allowed_bash_commands=allowed_bash_commands,
    )
    completed_process = subprocess.run(
        command,
        input=prompt,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )
    if completed_process.returncode != 0:
        raise RuntimeError(f"Ralph agent sandbox smoke test failed:\n{completed_process.stdout}")
    if _find_last_non_empty_line(completed_process.stdout) != "RALPH_SANDBOX_OK":
        raise RuntimeError(f"Ralph agent sandbox smoke test did not prove isolation:\n{completed_process.stdout}")


def _build_agent_visibility_smoke_test_prompt(
    repo_path: Path,
    backend_config: AgentBackendConfig,
    python_venv_path: Path | None,
) -> str:
    shell_command = _build_agent_visibility_smoke_test_agent_command(
        repo_path=repo_path,
        backend_config=backend_config,
        python_venv_path=python_venv_path,
    )
    return "\n".join(
        [
            "Run exactly this shell command:",
            shell_command,
            "Then answer only the final line it prints.",
        ]
    )


def _build_agent_visibility_smoke_test_agent_command(
    repo_path: Path,
    backend_config: AgentBackendConfig,
    python_venv_path: Path | None,
) -> str:
    shell_command = _build_agent_visibility_smoke_test_shell_command(
        repo_path=repo_path,
        backend_config=backend_config,
        python_venv_path=python_venv_path,
    )
    return f"bash -lc {_quote_shell_value(shell_command)}"


def _build_agent_visibility_smoke_test_shell_command(
    repo_path: Path,
    backend_config: AgentBackendConfig,
    python_venv_path: Path | None,
) -> str:
    hidden_paths = _remove_paths_that_overlap_explicit_mounts(
        hidden_paths=_build_sensitive_paths_that_workers_must_not_see(),
        explicitly_visible_paths=_build_explicit_worker_mount_paths(
            repo_path=repo_path,
            agent_home_path=backend_config.agent_home_path,
            python_venv_path=python_venv_path,
        ),
    )
    command_parts = ["set -eu"]
    command_parts += _build_shell_assertions_that_paths_are_hidden(hidden_paths)
    command_parts += _build_shell_assertions_that_environment_variables_are_absent(
        _build_credential_environment_variables_that_workers_must_not_receive()
    )
    command_parts += _build_shell_assertions_that_unselected_backend_environment_variables_are_absent(
        selected_agent_home_environment_variable=backend_config.agent_home_environment_variable,
    )
    command_parts += _build_shell_assertions_that_worker_environment_matches_bwrap_setenv_options(
        _build_backend_state_environment_variables_to_verify_exactly(
            agent_home_environment_variable=backend_config.agent_home_environment_variable,
            agent_home_path=backend_config.agent_home_path,
            python_venv_path=python_venv_path,
        )
    )
    command_parts += _build_shell_assertions_that_repo_is_writable(repo_path)
    if python_venv_path is not None:
        command_parts += _build_shell_assertions_that_python_venv_is_read_only(python_venv_path)
    command_parts += ["echo RALPH_SANDBOX_OK"]
    return " && ".join(command_parts)


def _build_explicit_worker_mount_paths(
    repo_path: Path,
    agent_home_path: Path,
    python_venv_path: Path | None,
) -> list[Path]:
    explicitly_visible_paths = [repo_path, agent_home_path]
    if python_venv_path is not None:
        explicitly_visible_paths.append(python_venv_path)
    return explicitly_visible_paths


def _build_sensitive_paths_that_workers_must_not_see() -> list[Path]:
    return [
        _resolve_ralph_home_path(),
        Path.home() / ".ralph",
        Path.home() / ".notion-task-tracker",
        Path.home() / ".ssh",
        Path.home() / ".aws",
        Path.home() / ".azure",
        Path.home() / ".claude",
        Path.home() / ".config",
        Path.home() / ".cache",
        Path.home() / ".docker",
        Path.home() / ".gnupg",
        Path.home() / ".kube",
        Path.home() / ".local" / "share",
        Path.home() / ".local" / "state",
        Path("/workspace/.notion-task-tracker"),
        Path("/workspace/.ssh"),
        Path("/workspace/.aws"),
        Path("/workspace/.azure"),
        Path("/workspace/.claude"),
        Path("/workspace/.config"),
        Path("/workspace/.cache"),
        Path("/workspace/.codex"),
        Path("/workspace/.docker"),
        Path("/workspace/.gnupg"),
        Path("/workspace/.kube"),
    ]


def _build_credential_environment_variables_that_workers_must_not_receive() -> list[str]:
    return [
        "NOTION_API_KEY",
        "OPENAI_API_KEY",
        "SSH_AUTH_SOCK",
        "AWS_ACCESS_KEY_ID",
        "AWS_SECRET_ACCESS_KEY",
        "AZURE_TOKEN",
        "GITHUB_TOKEN",
    ]


def _build_agent_home_environment_variables() -> list[str]:
    return ["CODEX_HOME", "CLAUDE_CONFIG_DIR"]


def _build_shell_assertions_that_unselected_backend_environment_variables_are_absent(
    selected_agent_home_environment_variable: str,
) -> list[str]:
    return _build_shell_assertions_that_environment_variables_are_absent(
        [
            variable_name
            for variable_name in _build_agent_home_environment_variables()
            if variable_name != selected_agent_home_environment_variable
        ]
    )


def _remove_paths_that_overlap_explicit_mounts(
    hidden_paths: list[Path],
    explicitly_visible_paths: list[Path],
) -> list[Path]:
    return [
        hidden_path
        for hidden_path in hidden_paths
        if not any(
            _paths_overlap(left_path=hidden_path, right_path=visible_path)
            for visible_path in explicitly_visible_paths
        )
    ]


def _paths_overlap(left_path: Path, right_path: Path) -> bool:
    resolved_left_path = left_path.resolve()
    resolved_right_path = right_path.resolve()
    return (
        _paths_resolve_to_same_location(left_path=resolved_left_path, right_path=resolved_right_path)
        or resolved_left_path.is_relative_to(resolved_right_path)
        or resolved_right_path.is_relative_to(resolved_left_path)
    )


def _paths_resolve_to_same_location(left_path: Path, right_path: Path) -> bool:
    return left_path.resolve() == right_path.resolve()


def _build_shell_assertions_that_paths_are_hidden(paths: list[Path]) -> list[str]:
    return [
        f"test ! -e {_quote_shell_path(path)} || {{ echo RALPH_SANDBOX_LEAKED_PATH {_quote_shell_path(path)}; exit 1; }}"
        for path in paths
    ]


def _build_shell_assertions_that_environment_variables_are_absent(variable_names: list[str]) -> list[str]:
    return [
        f"test -z \"${{{variable_name}:-}}\" || {{ echo RALPH_SANDBOX_LEAKED_VARIABLE {variable_name}; exit 1; }}"
        for variable_name in variable_names
    ]


def _build_shell_assertions_that_worker_environment_matches_bwrap_setenv_options(
    environment_variables: list[tuple[str, str]],
) -> list[str]:
    return [
        (
            f"test \"${{{variable_name}-}}\" = {_quote_shell_value(value)} || "
            f"{{ echo RALPH_SANDBOX_ENV_MISMATCH {variable_name}; exit 1; }}"
        )
        for variable_name, value in environment_variables
    ]


def _build_backend_state_environment_variables_to_verify_exactly(
    agent_home_environment_variable: str,
    agent_home_path: Path,
    python_venv_path: Path | None,
) -> list[tuple[str, str]]:
    environment_variables = [(agent_home_environment_variable, str(agent_home_path))]
    if python_venv_path is not None:
        environment_variables.append(("VIRTUAL_ENV", str(python_venv_path)))
    return environment_variables


def _build_shell_assertions_that_repo_is_writable(repo_path: Path) -> list[str]:
    probe_path = repo_path / ".ralph-sandbox-write-test-dir"
    return [
        f"mkdir {_quote_shell_path(probe_path)}",
        f"rmdir {_quote_shell_path(probe_path)}",
    ]


def _build_shell_assertions_that_python_venv_is_read_only(python_venv_path: Path) -> list[str]:
    return [
        f"test -d {_quote_shell_path(python_venv_path)}",
        _build_shell_assertion_that_mount_point_is_read_only(python_venv_path),
        f"test \"$VIRTUAL_ENV\" = {_quote_shell_value(python_venv_path)}",
    ]


def _build_shell_assertion_that_mount_point_is_read_only(mount_path: Path) -> str:
    quoted_mount_path = _quote_shell_value(mount_path)
    return (
        "ralph_found_read_only_mount=0; "
        "while read -r _ _ _ _ ralph_mount_path ralph_mount_options _; do "
        f"if test \"$ralph_mount_path\" = {quoted_mount_path}; then "
        "case \",$ralph_mount_options,\" in "
        "*,ro,*) ralph_found_read_only_mount=1 ;; "
        "*) echo RALPH_SANDBOX_WRITABLE_VENV; exit 1 ;; "
        "esac; "
        "fi; "
        "done < /proc/self/mountinfo; "
        "test \"$ralph_found_read_only_mount\" = 1"
    )


def _task_has_planned_notion_pairing(task: dict[str, Any]) -> bool:
    notion_task = task.get("notion_task")
    return isinstance(notion_task, dict) and notion_task.get("planned") is True


def _resolve_related_notion_task_id(tasks: list[dict[str, Any]], related_to: str) -> str:
    if _is_alovya_task_id(related_to):
        return related_to

    related_task = _find_task_by_id(tasks, related_to)
    related_notion_task_id = _materialised_notion_task_id_from_task(related_task)
    if related_notion_task_id is None:
        raise RuntimeError(
            f"Task {related_to} must materialise its Notion task before another task can relate to it."
        )
    return related_notion_task_id


def _create_planned_notion_task(
    relationship: str,
    related_notion_task_id: str,
    title: str,
    task_path: Path,
) -> str:
    output_path = task_path / "notion-create-output.json"
    content_path = _write_notion_content_file(
        task_path=task_path,
        log_name="create",
        content={
            "subheading": "Ralph task materialised",
            "blocks": [
                {"type": "paragraph", "text": f"Created from Ralph plan: {title}"},
            ],
        },
    )
    command = _build_notion_task_creation_command(
        relationship=relationship,
        related_notion_task_id=related_notion_task_id,
        title=title,
        content_path=content_path,
        output_path=output_path,
    )
    completed_process = _run_notion_tracker_command(command)
    _write_text(task_path / "notion-create-stdout.txt", completed_process.stdout)
    return _extract_created_notion_task_id(
        output_text=completed_process.stdout,
        output_path=output_path,
        excluded_task_id=related_notion_task_id,
    )


def _append_notion_task_log(
    notion_task_id: str,
    task_path: Path,
    log_name: str,
    content: dict[str, Any],
) -> None:
    content_path = _write_notion_content_file(task_path=task_path, log_name=log_name, content=content)
    output_path = task_path / f"notion-{log_name}-output.json"
    command = [
        _resolve_notion_tracker_command_path(),
        "--log",
        "--ticket-number",
        _ticket_number_from_alovya_task_id(notion_task_id),
        "--content-path",
        str(content_path),
        "--tracker-state-path",
        str(DEFAULT_NOTION_TRACKER_STATE_PATH),
        "--output-path",
        str(output_path),
    ]
    completed_process = _run_notion_tracker_command(command)
    _write_text(task_path / f"notion-{log_name}-stdout.txt", completed_process.stdout)


def _build_notion_task_creation_command(
    relationship: str,
    related_notion_task_id: str,
    title: str,
    content_path: Path,
    output_path: Path,
) -> list[str]:
    if relationship == "child":
        return [
            _resolve_notion_tracker_command_path(),
            "--child",
            "--parent-ticket-number",
            _ticket_number_from_alovya_task_id(related_notion_task_id),
            "--title",
            title,
            "--content-path",
            str(content_path),
            "--tracker-state-path",
            str(DEFAULT_NOTION_TRACKER_STATE_PATH),
            "--output-path",
            str(output_path),
        ]
    if relationship == "sibling":
        return [
            _resolve_notion_tracker_command_path(),
            "--sibling",
            "--sibling-ticket-number",
            _ticket_number_from_alovya_task_id(related_notion_task_id),
            "--title",
            title,
            "--content-path",
            str(content_path),
            "--tracker-state-path",
            str(DEFAULT_NOTION_TRACKER_STATE_PATH),
            "--output-path",
            str(output_path),
        ]
    raise ValueError(f"Unsupported Notion relationship: {relationship}")


def _record_materialised_notion_task_id(
    ledger: dict[str, Any],
    task_id: str,
    materialised_task_id: str,
) -> dict[str, Any]:
    updated_ledger = copy.deepcopy(ledger)
    for task in _read_tasks_from_ledger(updated_ledger):
        if task["id"] == task_id:
            task["notion_task"]["materialized_task_id"] = materialised_task_id
            return updated_ledger
    raise ValueError(f"Unknown Ralph task id: {task_id}")


def _refresh_task_selection_from_ledger(
    ledger: dict[str, Any],
    selection: TaskSelection,
) -> TaskSelection:
    refreshed_task = _find_task_by_id(_read_tasks_from_ledger(ledger), selection.task["id"])
    refreshed_task_with_plan_commands = _attach_plan_command_contract_to_task(
        task=refreshed_task,
        allowed_bash_commands=selection.task.get("allowed_bash_commands") or [],
        verification_commands=selection.task.get("verification_commands") or [],
    )
    return TaskSelection(
        task=refreshed_task_with_plan_commands,
        shared_plan_context=selection.shared_plan_context,
        active_task_plan_context=selection.active_task_plan_context,
    )


def _find_task_by_id(tasks: list[dict[str, Any]], task_id: str) -> dict[str, Any]:
    for task in tasks:
        if task["id"] == task_id:
            return task
    raise ValueError(f"Unknown Ralph task id: {task_id}")


def _materialised_notion_task_id_from_task(task: dict[str, Any]) -> str | None:
    notion_task = task.get("notion_task")
    if not isinstance(notion_task, dict):
        return None

    materialised_task_id = notion_task.get("materialized_task_id")
    if materialised_task_id:
        return materialised_task_id
    return None


def _write_notion_content_file(task_path: Path, log_name: str, content: dict[str, Any]) -> Path:
    content_path = task_path / f"notion-{log_name}-content.json"
    content_path.write_text(json.dumps(content, indent=2, sort_keys=True), encoding="utf-8")
    return content_path


def _run_notion_tracker_command(command: list[str]) -> subprocess.CompletedProcess[str]:
    completed_process = subprocess.run(
        command,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )
    if completed_process.returncode != 0:
        raise RuntimeError(f"Notion task tracker command failed:\n{completed_process.stdout}")
    return completed_process


def _extract_created_notion_task_id(output_text: str, output_path: Path, excluded_task_id: str) -> str:
    candidate_task_ids = _alovya_task_ids_from_text(output_text)
    if output_path.is_file():
        candidate_task_ids += _alovya_task_ids_from_text(output_path.read_text(encoding="utf-8"))

    created_task_ids = [
        task_id
        for task_id in dict.fromkeys(candidate_task_ids)
        if task_id != excluded_task_id
    ]
    if len(created_task_ids) != 1:
        raise RuntimeError(
            "Could not determine the single Notion task created by ntt. "
            f"Candidates: {created_task_ids}"
        )
    return created_task_ids[0]


def _alovya_task_ids_from_text(text: str) -> list[str]:
    return re.findall(r"ALOVYA-\d+", text)


def _is_alovya_task_id(value: str) -> bool:
    return ALOVYA_TASK_ID_PATTERN.match(value) is not None


def _ticket_number_from_alovya_task_id(task_id: str) -> str:
    match = ALOVYA_TASK_ID_PATTERN.match(task_id)
    if match is None:
        raise ValueError(f"Expected ALOVYA task id, got: {task_id}")
    return match.group("ticket_number")


def _resolve_notion_tracker_command_path() -> str:
    command_path = shutil.which("ntt")
    if command_path is not None:
        return command_path

    workspace_command_path = Path("/workspace/venv/bin/ntt")
    if workspace_command_path.is_file():
        return str(workspace_command_path)

    raise RuntimeError("Notion task tracker command not found: ntt")


def _read_committed_files(repo_path: Path, commit_hash: str) -> list[str]:
    changed_files_output = _run_git(repo_path, "show", "--name-status", "--format=", commit_hash).strip()
    if not changed_files_output:
        return []
    return changed_files_output.splitlines()


def _read_text_if_file_exists(path: Path) -> str:
    if path.is_file():
        return path.read_text(encoding="utf-8")
    return ""


def _worker_launch_constraints() -> list[str]:
    return [
        "Worker cannot read Ralph controller state.",
        "Worker cannot receive Notion credentials or tracker state.",
        "Worker may run only the bash commands allowed by the active task contract.",
        "Worker must run verification before DONE.",
        "Worker must commit with git commit --no-verify before DONE.",
        "Controller owns Notion logging and validates worker-produced verification and commit artefacts.",
    ]


def _build_worker_allowed_bash_commands(task: dict[str, Any]) -> list[str]:
    allowed_commands = list(ALWAYS_ALLOWED_WORKER_BASH_COMMANDS)
    allowed_commands += list(task.get("allowed_bash_commands") or [])
    allowed_commands += list(task.get("verification_commands") or [])
    return list(dict.fromkeys(allowed_commands))


def _quote_shell_path(path: Path) -> str:
    return shlex.quote(str(path))


def _quote_shell_value(value: Path | str) -> str:
    return shlex.quote(str(value))


def _select_agent_backend_config(
    agent_backend: str,
    agent_command: str | None,
) -> AgentBackendConfig:
    if agent_backend == "codex":
        return _build_codex_backend_config(agent_command)
    if agent_backend == "claude":
        return _build_claude_backend_config(agent_command)
    raise ValueError(f"Unsupported agent backend: {agent_backend}")


def _build_codex_backend_config(agent_command: str | None) -> AgentBackendConfig:
    agent_home_path = _require_agent_home_path_from_environment_variable("CODEX_HOME")
    return AgentBackendConfig(
        backend_name="codex",
        command_name=agent_command or _read_default_codex_agent_command(),
        agent_home_path=agent_home_path,
        agent_home_environment_variable="CODEX_HOME",
    )


def _build_claude_backend_config(agent_command: str | None) -> AgentBackendConfig:
    agent_home_path = _require_agent_home_path_from_environment_variable("CLAUDE_CONFIG_DIR")
    return AgentBackendConfig(
        backend_name="claude",
        command_name=agent_command or _read_default_claude_agent_command(),
        agent_home_path=agent_home_path,
        agent_home_environment_variable="CLAUDE_CONFIG_DIR",
    )


def _build_bwrap_agent_command(
    repo_path: Path,
    backend_config: AgentBackendConfig,
    python_venv_path: Path | None,
    allowed_bash_commands: list[str] | None = None,
) -> list[str]:
    bwrap_path = shutil.which("bwrap")
    if bwrap_path is None:
        raise RuntimeError("Ralph requires bubblewrap installed as `bwrap`.")

    host_agent_binary_path = _resolve_agent_binary_path(backend_config.command_name)

    command = [bwrap_path]
    command += ["--tmpfs", "/"]
    command += ["--tmpfs", "/tmp"]
    command += _build_bwrap_runtime_mount_options()
    command += _build_bwrap_dir_options_for_bind_mount_target(WORKER_AGENT_BINARY_PATH, create_target_dir=False)
    command += ["--ro-bind", str(host_agent_binary_path), str(WORKER_AGENT_BINARY_PATH)]
    command += _build_bwrap_dir_options_for_bind_mount_target(repo_path)
    command += ["--bind", str(repo_path), str(repo_path)]
    command += ["--dev", "/dev"]

    command += _build_bwrap_agent_home_mount_options(backend_config.agent_home_path)
    command += _build_bwrap_dir_options_for_bind_mount_target(WORKER_HOME_PATH)
    command += _build_bwrap_dir_options_for_bind_mount_target(WORKER_TEMP_PATH)

    if python_venv_path is not None:
        command += _build_bwrap_dir_options_for_bind_mount_target(python_venv_path)
        command += ["--ro-bind", str(python_venv_path), str(python_venv_path)]

    command += ["--clearenv"]
    command += _build_bwrap_setenv_options(
        _build_bwrap_worker_environment_variables(
            agent_home_environment_variable=backend_config.agent_home_environment_variable,
            agent_home_path=backend_config.agent_home_path,
            python_venv_path=python_venv_path,
        )
    )

    command += [str(WORKER_AGENT_BINARY_PATH)]
    command += _build_agent_command_tail(
        backend_config=backend_config,
        repo_path=repo_path,
        allowed_bash_commands=allowed_bash_commands or [],
    )
    return command


def _build_agent_command_tail(
    backend_config: AgentBackendConfig,
    repo_path: Path,
    allowed_bash_commands: list[str],
) -> list[str]:
    if backend_config.backend_name == "codex":
        return _build_codex_command_tail(repo_path)
    if backend_config.backend_name == "claude":
        return _build_claude_command_tail(allowed_bash_commands)
    raise ValueError(f"Unsupported agent backend: {backend_config.backend_name}")


def _build_codex_command_tail(repo_path: Path) -> list[str]:
    return [
        "--ask-for-approval",
        "never",
        "exec",
        "-C",
        str(repo_path),
        "--sandbox",
        "danger-full-access",
        "--ephemeral",
        "--ignore-rules",
        "-",
    ]


def _build_claude_command_tail(allowed_bash_commands: list[str]) -> list[str]:
    command_tail = [
        "--print",
        "--input-format",
        "text",
        "--output-format",
        "text",
        "--permission-mode",
        "dontAsk",
        "--allowedTools",
    ]
    command_tail += _build_claude_allowed_tools(allowed_bash_commands)
    command_tail += [
        "--no-session-persistence",
    ]
    return command_tail


def _build_claude_allowed_tools(allowed_bash_commands: list[str]) -> list[str]:
    allowed_tools = ["Read", "Glob", "Grep", "Edit", "MultiEdit", "Write"]
    allowed_tools += [
        f"Bash({command})"
        for command in allowed_bash_commands
    ]
    return allowed_tools


def _build_bwrap_worker_environment_variables(
    agent_home_environment_variable: str,
    agent_home_path: Path,
    python_venv_path: Path | None,
) -> list[tuple[str, str]]:
    environment_variables = [
        ("HOME", str(WORKER_HOME_PATH)),
        ("TMPDIR", str(WORKER_TEMP_PATH)),
        (agent_home_environment_variable, str(agent_home_path)),
        ("XDG_CONFIG_HOME", str(WORKER_HOME_PATH / ".config")),
        ("XDG_CACHE_HOME", str(WORKER_HOME_PATH / ".cache")),
        ("XDG_DATA_HOME", str(WORKER_HOME_PATH / ".local" / "share")),
        ("AZURE_CONFIG_DIR", str(WORKER_HOME_PATH / ".azure")),
        ("DOCKER_CONFIG", str(WORKER_HOME_PATH / ".docker")),
        ("GNUPGHOME", str(WORKER_HOME_PATH / ".gnupg")),
        ("KUBECONFIG", str(WORKER_HOME_PATH / ".kube" / "config")),
        ("SSL_CERT_FILE", "/etc/ssl/certs/ca-certificates.crt"),
        ("PATH", _build_agent_path_value(python_venv_path)),
    ]

    if python_venv_path is not None:
        environment_variables += [
            ("VIRTUAL_ENV", str(python_venv_path)),
        ]

    return environment_variables


def _build_bwrap_setenv_options(environment_variables: list[tuple[str, str]]) -> list[str]:
    options: list[str] = []
    for variable_name, value in environment_variables:
        options += ["--setenv", variable_name, value]
    return options


def _build_bwrap_runtime_mount_options() -> list[str]:
    options = ["--proc", "/proc"]
    options += _build_bwrap_host_os_runtime_mount_options()
    options += _build_bwrap_read_only_file_mount_options(
        host_path=Path("/etc/hosts"),
        sandbox_path=Path("/etc/hosts"),
    )
    options += _build_bwrap_read_only_file_mount_options(
        host_path=Path("/etc/resolv.conf").resolve(),
        sandbox_path=Path("/etc/resolv.conf"),
    )
    options += _build_bwrap_read_only_file_mount_options(
        host_path=Path("/etc/nsswitch.conf"),
        sandbox_path=Path("/etc/nsswitch.conf"),
    )
    options += _build_bwrap_read_only_file_mount_options(
        host_path=Path("/etc/ld.so.cache"),
        sandbox_path=Path("/etc/ld.so.cache"),
    )
    options += _build_bwrap_read_only_file_mount_options(
        host_path=Path("/etc/ssl/certs/ca-certificates.crt"),
        sandbox_path=Path("/etc/ssl/certs/ca-certificates.crt"),
    )
    return options


def _build_bwrap_host_os_runtime_mount_options() -> list[str]:
    options = _build_bwrap_read_only_dir_mount_options(
        host_path=Path("/usr"),
        sandbox_path=Path("/usr"),
    )
    for compatibility_path in [Path("/bin"), Path("/lib"), Path("/lib64"), Path("/sbin")]:
        options += _build_bwrap_host_os_compatibility_mount_options(compatibility_path)
    return options


def _build_bwrap_host_os_compatibility_mount_options(compatibility_path: Path) -> list[str]:
    if compatibility_path.is_symlink():
        return ["--symlink", os.readlink(compatibility_path), str(compatibility_path)]
    return _build_bwrap_read_only_dir_mount_options(
        host_path=compatibility_path,
        sandbox_path=compatibility_path,
    )


def _build_bwrap_agent_home_mount_options(agent_home_path: Path) -> list[str]:
    options = _build_bwrap_dir_options_for_bind_mount_target(agent_home_path)
    options += ["--bind", str(agent_home_path), str(agent_home_path)]
    if (agent_home_path / ".tmp").is_dir():
        options += ["--tmpfs", str(agent_home_path / ".tmp")]
    return options


def _build_bwrap_read_only_file_mount_options(host_path: Path, sandbox_path: Path) -> list[str]:
    if not host_path.is_file():
        return []

    options = _build_bwrap_dir_options_for_bind_mount_target(sandbox_path, create_target_dir=False)
    options += ["--ro-bind", str(host_path), str(sandbox_path)]
    return options


def _build_bwrap_read_only_dir_mount_options(host_path: Path, sandbox_path: Path) -> list[str]:
    if not host_path.is_dir():
        return []

    options = _build_bwrap_dir_options_for_bind_mount_target(sandbox_path)
    options += ["--ro-bind", str(host_path), str(sandbox_path)]
    return options


def _require_codex_home_path() -> Path:
    return _require_agent_home_path_from_environment_variable("CODEX_HOME")


def _require_agent_home_path_from_environment_variable(variable_name: str) -> Path:
    configured_path = os.environ.get(variable_name)
    if not configured_path:
        raise RuntimeError(f"{variable_name} must be set before running Ralph agents.")

    agent_home_path = Path(configured_path).expanduser().resolve()
    if not agent_home_path.is_dir():
        raise RuntimeError(f"{variable_name} does not exist: {agent_home_path}")
    _refuse_agent_home_path_that_exposes_other_sensitive_state(
        agent_home_path=agent_home_path,
        variable_name=variable_name,
    )
    return agent_home_path


def _refuse_agent_home_path_that_exposes_other_sensitive_state(agent_home_path: Path, variable_name: str) -> None:
    for sensitive_path in _build_sensitive_paths_that_workers_must_not_see():
        if _paths_resolve_to_same_location(left_path=agent_home_path, right_path=sensitive_path):
            continue
        if _paths_overlap(left_path=agent_home_path, right_path=sensitive_path):
            raise ValueError(
                f"{variable_name} must not overlap other worker-hidden sensitive state: "
                f"{agent_home_path} overlaps {sensitive_path}"
            )


def _resolve_python_venv_path(python_venv: str | None) -> Path | None:
    if python_venv is None:
        python_venv = os.environ.get("VIRTUAL_ENV")
    if python_venv is None:
        return None

    python_venv_path = Path(python_venv).expanduser().resolve()
    if not python_venv_path.is_dir():
        raise FileNotFoundError(f"Python venv does not exist: {python_venv_path}")
    if not (python_venv_path / "bin" / "python").is_file():
        raise FileNotFoundError(f"Python venv is missing bin/python: {python_venv_path}")
    _refuse_explicit_worker_mount_that_overlaps_sensitive_hidden_paths(
        path=python_venv_path,
        role="Python venv",
    )
    return python_venv_path


def _refuse_explicit_worker_mount_that_overlaps_sensitive_hidden_paths(path: Path, role: str) -> None:
    for sensitive_path in _build_sensitive_paths_that_workers_must_not_see():
        if _paths_overlap(left_path=path, right_path=sensitive_path):
            raise ValueError(
                f"{role} must not overlap worker-hidden sensitive state: "
                f"{path} overlaps {sensitive_path}"
            )


def _build_bwrap_dir_options_for_bind_mount_target(path: Path, *, create_target_dir: bool = True) -> list[str]:
    """
    bwrap --dir creates an empty directory inside the sandbox before bind mounting.

    For directory target /workspace/repo, this returns:
    --dir /workspace --dir /workspace/repo

    For file target /home/alovyachowdhury/.local/bin/codex with create_target_dir false, this returns:
    --dir /home --dir /home/alovyachowdhury --dir /home/alovyachowdhury/.local --dir /home/alovyachowdhury/.local/bin
    """
    path_parts = path.resolve().parts[1:]
    if not create_target_dir:
        path_parts = path_parts[:-1]

    options: list[str] = []
    current_path = Path("/")
    for part in path_parts:
        current_path = current_path / part
        options.extend(["--dir", str(current_path)])
    return options


def _resolve_agent_binary_path(agent_command: str) -> Path:
    resolved_command = shutil.which(agent_command)
    if resolved_command is None:
        raise RuntimeError(f"Agent command not found: {agent_command}")
    return Path(resolved_command).resolve()


def _read_yaml_file(yaml_path: Path) -> dict[str, Any]:
    value = yaml.safe_load(yaml_path.read_text())
    if not isinstance(value, dict):
        raise ValueError(f"Expected YAML mapping in {yaml_path}")
    return value


def _write_yaml_file(yaml_path: Path, value: dict[str, Any]) -> None:
    yaml_path.write_text(_dump_yaml(value))


def _dump_yaml(value: Any) -> str:
    return yaml.safe_dump(value, sort_keys=False)


def _read_tasks_from_ledger(ledger: dict[str, Any]) -> list[dict[str, Any]]:
    tasks = ledger.get("tasks")
    if not isinstance(tasks, list):
        raise ValueError("ledger.yaml must contain a tasks list.")
    for task in tasks:
        _validate_task_shape(task)
    _validate_planned_notion_task_relationships(tasks)
    return tasks


def _validate_task_shape(task: Any) -> None:
    if not isinstance(task, dict):
        raise ValueError("Every ledger task must be a mapping.")
    for required_key in ["id", "title", "status"]:
        if not task.get(required_key):
            raise ValueError(f"Every ledger task must have {required_key}.")
    for plan_command_key in ["allowed_bash_commands", "verification_commands"]:
        if plan_command_key in task:
            raise ValueError(f"Ledger task {task['id']} must keep {plan_command_key} in PLAN.md.")
    if task["status"] not in {"pending", "done", "blocked", "aborted"}:
        raise ValueError(f"Invalid task status for {task['id']}: {task['status']}")
    if _contains_forbidden_plan_field(task):
        raise ValueError(f"Ledger task {task['id']} contains plan-like prose fields.")
    _validate_notion_task_shape(task)


def _validate_notion_task_shape(task: dict[str, Any]) -> None:
    notion_task = task.get("notion_task")
    if notion_task is None:
        return
    if not isinstance(notion_task, dict):
        raise ValueError(f"notion_task for {task['id']} must be a mapping.")
    if not isinstance(notion_task.get("planned"), bool):
        raise ValueError(f"notion_task.planned for {task['id']} must be boolean.")
    if notion_task["planned"] is False:
        return
    if notion_task.get("relationship") not in {"child", "sibling"}:
        raise ValueError(f"notion_task.relationship for {task['id']} must be child or sibling.")
    for required_key in ["related_to", "title"]:
        if not isinstance(notion_task.get(required_key), str) or not notion_task[required_key].strip():
            raise ValueError(f"notion_task.{required_key} for {task['id']} must be a non-empty string.")
    materialised_task_id = notion_task.get("materialized_task_id")
    if materialised_task_id is not None and (
        not isinstance(materialised_task_id, str) or not _is_alovya_task_id(materialised_task_id)
    ):
        raise ValueError(f"notion_task.materialized_task_id for {task['id']} must be null or an ALOVYA id.")


def _validate_planned_notion_task_relationships(tasks: list[dict[str, Any]]) -> None:
    task_ids = {task["id"] for task in tasks}
    for task in tasks:
        notion_task = task.get("notion_task")
        if not isinstance(notion_task, dict) or notion_task.get("planned") is not True:
            continue

        related_to = notion_task["related_to"]
        if _is_alovya_task_id(related_to):
            continue
        if related_to not in task_ids:
            raise ValueError(f"notion_task.related_to for {task['id']} references unknown Ralph task {related_to}.")
        if related_to not in (task.get("depends_on") or []):
            raise ValueError(f"Task {task['id']} must depend on related Ralph task {related_to}.")


def _contains_forbidden_plan_field(value: Any) -> bool:
    if isinstance(value, dict):
        return any(key in {"plan", "context", "notes", "description", "implementation"} for key in value)
    return False


def _extract_shared_plan_context(plan_text: str) -> str:
    matches = list(SHARED_BLOCK_PATTERN.finditer(plan_text))
    if len(matches) != 1:
        raise ValueError("PLAN.md must contain exactly one ralph-shared block.")
    return matches[0].group("body")


def _extract_task_plan_contexts(plan_text: str) -> dict[str, str]:
    task_plan_contexts: dict[str, str] = {}
    duplicate_task_ids: set[str] = set()
    for match in TASK_BLOCK_PATTERN.finditer(plan_text):
        task_id = match.group("task_id")
        if task_id in task_plan_contexts:
            duplicate_task_ids.add(task_id)
        task_plan_contexts[task_id] = match.group("body")
    if duplicate_task_ids:
        raise ValueError(f"Duplicate Ralph task blocks: {sorted(duplicate_task_ids)}")
    return task_plan_contexts


def _derive_task_command_contracts_from_plan(
    task_plan_contexts: dict[str, str],
) -> dict[str, dict[str, list[str]]]:
    return {
        task_id: {
            "allowed_bash_commands": _extract_plan_command_list(
                task_id=task_id,
                task_plan_context=task_plan_context,
                block_name="ralph-allowed-bash",
            ),
            "verification_commands": _extract_plan_command_list(
                task_id=task_id,
                task_plan_context=task_plan_context,
                block_name="ralph-verification",
            ),
        }
        for task_id, task_plan_context in task_plan_contexts.items()
    }


def _attach_plan_command_contract_to_task(
    task: dict[str, Any],
    allowed_bash_commands: list[str],
    verification_commands: list[str],
) -> dict[str, Any]:
    task_with_plan_commands = dict(task)
    task_with_plan_commands["allowed_bash_commands"] = allowed_bash_commands
    task_with_plan_commands["verification_commands"] = verification_commands
    return task_with_plan_commands


def _extract_plan_command_list(
    task_id: str,
    task_plan_context: str,
    block_name: str,
) -> list[str]:
    block_body = _extract_single_plan_command_block(
        task_id=task_id,
        task_plan_context=task_plan_context,
        block_name=block_name,
    )
    commands: list[str] = []
    malformed_lines: list[str] = []
    for line in block_body.splitlines():
        if not line.strip():
            continue
        match = PLAN_COMMAND_ITEM_PATTERN.match(line)
        if match is None:
            malformed_lines.append(line)
            continue
        commands.append(match.group("command"))
    if malformed_lines:
        raise ValueError(
            f"Task {task_id} {block_name} block must contain only '- <command>' lines: {malformed_lines}"
        )
    if not commands:
        raise ValueError(f"Task {task_id} {block_name} block must contain at least one command.")
    return commands


def _extract_single_plan_command_block(
    task_id: str,
    task_plan_context: str,
    block_name: str,
) -> str:
    command_block_pattern = re.compile(
        rf"<!--\s*{re.escape(block_name)}:start\s*-->\n"
        rf"(?P<body>.*?)"
        rf"<!--\s*{re.escape(block_name)}:end\s*-->",
        re.DOTALL,
    )
    matches = list(command_block_pattern.finditer(task_plan_context))
    if len(matches) != 1:
        raise ValueError(f"Task {task_id} must contain exactly one {block_name} block.")
    return matches[0].group("body")


def _validate_plan_and_ledger_match(
    tasks: list[dict[str, Any]],
    task_plan_contexts: dict[str, str],
) -> None:
    ledger_task_ids = {task["id"] for task in tasks}
    plan_task_ids = set(task_plan_contexts)
    missing_task_ids = sorted(ledger_task_ids - plan_task_ids)
    unknown_task_ids = sorted(plan_task_ids - ledger_task_ids)
    if missing_task_ids:
        raise ValueError(f"PLAN.md is missing Ralph task blocks: {missing_task_ids}")
    if unknown_task_ids:
        raise ValueError(f"PLAN.md contains task blocks absent from ledger.yaml: {unknown_task_ids}")


def _mark_task_done(ledger: dict[str, Any], task_id: str) -> dict[str, Any]:
    updated_ledger = dict(ledger)
    updated_tasks = []
    for task in _read_tasks_from_ledger(ledger):
        updated_task = dict(task)
        if updated_task["id"] == task_id:
            updated_task["status"] = "done"
            updated_task["completed_at"] = dt.datetime.now(dt.timezone.utc).isoformat()
        updated_tasks.append(updated_task)
    updated_ledger["tasks"] = updated_tasks
    return updated_ledger


def _remove_plan_like_fields(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: _remove_plan_like_fields(child_value)
            for key, child_value in value.items()
            if key not in {"plan", "context", "notes", "description", "implementation"}
        }
    if isinstance(value, list):
        return [_remove_plan_like_fields(item) for item in value]
    return value


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


def _contains_private_control_path_named_under_repo(repo_path: Path, name: str) -> bool:
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


def _find_last_non_empty_line(text: str) -> str:
    for line in reversed(text.splitlines()):
        if line.strip():
            return line.strip()
    return ""


def _read_default_codex_agent_command() -> str:
    return os.environ.get("RALPH_AGENT_COMMAND", os.environ.get("RALPH_CODEX_COMMAND", "codex"))


def _read_default_claude_agent_command() -> str:
    return os.environ.get("RALPH_AGENT_COMMAND", os.environ.get("RALPH_CLAUDE_COMMAND", "claude"))


def _describe_tool_environment(python_venv_path: Path | None) -> str:
    if python_venv_path is None:
        return "No Python venv was configured for helper tools. Use only tools already available on PATH."

    return "\n".join(
        [
            f"Python venv: {python_venv_path}",
            f"`{python_venv_path / 'bin'}` is already first on PATH.",
            f"`VIRTUAL_ENV` is already set to `{python_venv_path}`.",
            f"`BASH_ENV` points at `{python_venv_path / 'bin' / 'activate'}` so shell tool calls keep the venv active.",
            "Use commands installed in this venv only when the active task requires them.",
        ]
    )


def _build_agent_path_value(python_venv_path: Path | None) -> str:
    path_entries = []
    if python_venv_path is not None:
        path_entries.append(str(python_venv_path / "bin"))
    path_entries.extend(
        [
            "/usr/local/sbin",
            "/usr/local/bin",
            "/usr/sbin",
            "/usr/bin",
            "/sbin",
            "/bin",
        ]
    )
    return ":".join(
        path_entries
    )


if __name__ == "__main__":
    main()
