from __future__ import annotations

import argparse
import contextlib
import datetime as dt
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator

if __name__ == "__main__":
    _package_root = Path(__file__).resolve().parent.parent
    if str(_package_root) not in sys.path:
        sys.path.insert(0, str(_package_root))

import yaml

from ralph.notion import (
    DEFAULT_NOTION_TRACKER_STATE_PATH,
    build_notion_task_creation_command,
    extract_created_notion_task_id,
    log_completed_worker_to_notion,
    log_failed_verification_to_notion,
    log_slice_start_to_notion,
    log_worker_promise_to_notion,
    materialise_planned_notion_task_before_worker_launch,
    materialised_notion_task_id_from_task,
    prepare_notion_task_before_worker_runs_task,
)
from ralph.plan_selection import (
    TaskSelection,
    read_tasks_from_ledger,
    select_next_task_from_plan_and_ledger,
)
from ralph.prompt import (
    describe_python_venv_for_worker_prompt,
    render_agent_prompt,
)


DEFAULT_RALPH_HOME_PATH = Path("/workspace/.ralph")
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
CODEX_RULES_BACKUP_FILENAME = "codex-rules-backup.marker"


@dataclass(frozen=True)
class RalphJob:
    job_name: str
    job_path: Path
    plan_path: Path
    ledger_path: Path
    tasks_path: Path


@dataclass(frozen=True)
class AgentResult:
    promise: str
    output: str


@dataclass(frozen=True)
class AgentBackend:
    backend_name: str
    command_name: str
    agent_state_dir: Path
    agent_home_environment_variable: str


PRIVATE_CONTROL_PATH_NAMES = frozenset({"PLAN.md", "ledger.yaml", ".ralph"})


# Re-export for backwards compatibility
_select_next_task_from_plan_and_ledger = select_next_task_from_plan_and_ledger
_read_tasks_from_ledger = read_tasks_from_ledger
_render_agent_prompt = render_agent_prompt
_describe_python_venv_for_worker_prompt = describe_python_venv_for_worker_prompt
_prepare_notion_task_before_worker_runs_task = prepare_notion_task_before_worker_runs_task
_materialise_planned_notion_task_before_worker_launch = materialise_planned_notion_task_before_worker_launch
_log_slice_start_to_notion = log_slice_start_to_notion
_log_worker_promise_to_notion = log_worker_promise_to_notion
_log_failed_verification_to_notion = log_failed_verification_to_notion
_log_completed_worker_to_notion = log_completed_worker_to_notion
_materialised_notion_task_id_from_task = materialised_notion_task_id_from_task
_build_notion_task_creation_command = build_notion_task_creation_command
_extract_created_notion_task_id = extract_created_notion_task_id


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
    _recover_interrupted_codex_rules(job)
    _run_agent_visibility_smoke_test(
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
    _reject_worker_visible_path_that_overlaps_hidden_state(
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
    backend_config = _select_agent_backend_config(
        agent_backend=agent_backend,
        agent_command=agent_command,
    )
    allowed_bash_commands = _build_worker_allowed_bash_commands(task)
    command = _build_bwrap_agent_command(
        repo_path=repo_path,
        backend_config=backend_config,
        python_venv_path=python_venv_path,
        allowed_bash_commands=allowed_bash_commands,
    )

    with _backend_permission_setup(
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

    output = _extract_agent_result_text(
        backend_config=backend_config,
        raw_output=completed_process.stdout or "",
    )
    if completed_process.returncode != 0:
        raise RuntimeError(f"Agent failed with exit code {completed_process.returncode}. See {output_path}")
    promise = _parse_agent_promise(output)
    return AgentResult(promise=promise, output=output)


@contextlib.contextmanager
def _backend_permission_setup(
    backend_config: AgentBackend,
    allowed_bash_commands: list[str],
    task_path: Path | None,
) -> Iterator[None]:
    if backend_config.backend_name == "codex" and task_path is not None:
        with _codex_permission_setup(
            backend_config=backend_config,
            allowed_bash_commands=allowed_bash_commands,
            task_path=task_path,
        ):
            yield
    else:
        with _claude_permission_setup():
            yield


@contextlib.contextmanager
def _codex_permission_setup(
    backend_config: AgentBackend,
    allowed_bash_commands: list[str],
    task_path: Path,
) -> Iterator[None]:
    codex_home_path = backend_config.agent_state_dir
    rules_path = _codex_rules_path(codex_home_path)
    backup_path = task_path / CODEX_RULES_BACKUP_FILENAME

    original_rules_snapshot = _snapshot_codex_rules(rules_path)
    _write_codex_rules_backup(backup_path, original_rules_snapshot)

    try:
        generated_rules = _generate_codex_execpolicy_rules(allowed_bash_commands)
        _write_codex_rules_atomically(rules_path, generated_rules)
        yield
    finally:
        _restore_codex_rules(rules_path, original_rules_snapshot)
        backup_path.unlink(missing_ok=True)


@contextlib.contextmanager
def _claude_permission_setup() -> Iterator[None]:
    yield


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
    _reject_worker_visible_path_that_overlaps_hidden_state(
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
    output = _extract_agent_result_text(
        backend_config=backend_config,
        raw_output=completed_process.stdout or "",
    )
    if _find_last_non_empty_line(output) != "RALPH_SANDBOX_OK":
        raise RuntimeError(f"Ralph agent sandbox smoke test did not prove isolation:\n{completed_process.stdout}")


def _build_agent_visibility_smoke_test_prompt(
    repo_path: Path,
    backend_config: AgentBackend,
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
    backend_config: AgentBackend,
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
    backend_config: AgentBackend,
    python_venv_path: Path | None,
) -> str:
    hidden_paths = _remove_paths_that_overlap_explicit_mounts(
        hidden_paths=_build_sensitive_paths_that_workers_must_not_see(),
        explicitly_visible_paths=_build_explicit_worker_mount_paths(
            repo_path=repo_path,
            agent_state_dir=backend_config.agent_state_dir,
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
            agent_state_dir=backend_config.agent_state_dir,
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
    agent_state_dir: Path,
    python_venv_path: Path | None,
) -> list[Path]:
    explicitly_visible_paths = [repo_path, agent_state_dir]
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
    agent_state_dir: Path,
    python_venv_path: Path | None,
) -> list[tuple[str, str]]:
    environment_variables = [(agent_home_environment_variable, str(agent_state_dir))]
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


def _read_committed_files(repo_path: Path, commit_hash: str) -> list[str]:
    changed_files_output = _run_git(repo_path, "show", "--name-status", "--format=", commit_hash).strip()
    if not changed_files_output:
        return []
    return changed_files_output.splitlines()


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
) -> AgentBackend:
    if agent_backend == "codex":
        return _build_codex_backend_config(agent_command)
    if agent_backend == "claude":
        return _build_claude_backend_config(agent_command)
    raise ValueError(f"Unsupported agent backend: {agent_backend}")


def _build_codex_backend_config(agent_command: str | None) -> AgentBackend:
    agent_state_dir = _require_agent_state_dir_from_environment_variable("CODEX_HOME")
    return AgentBackend(
        backend_name="codex",
        command_name=agent_command or _read_default_codex_agent_command(),
        agent_state_dir=agent_state_dir,
        agent_home_environment_variable="CODEX_HOME",
    )


def _build_claude_backend_config(agent_command: str | None) -> AgentBackend:
    agent_state_dir = _require_agent_state_dir_from_environment_variable("CLAUDE_CONFIG_DIR")
    return AgentBackend(
        backend_name="claude",
        command_name=agent_command or _read_default_claude_agent_command(),
        agent_state_dir=agent_state_dir,
        agent_home_environment_variable="CLAUDE_CONFIG_DIR",
    )


def _build_bwrap_agent_command(
    repo_path: Path,
    backend_config: AgentBackend,
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
    command += _build_bwrap_sandbox_mount_target_dir_options(WORKER_AGENT_BINARY_PATH, create_target_dir=False)
    command += ["--ro-bind", str(host_agent_binary_path), str(WORKER_AGENT_BINARY_PATH)]
    command += _build_bwrap_sandbox_mount_target_dir_options(repo_path)
    command += ["--bind", str(repo_path), str(repo_path)]
    command += ["--dev", "/dev"]

    command += _build_bwrap_agent_home_mount_options(backend_config.agent_state_dir)
    command += _build_bwrap_sandbox_mount_target_dir_options(WORKER_HOME_PATH)
    command += _build_bwrap_sandbox_mount_target_dir_options(WORKER_TEMP_PATH)

    if python_venv_path is not None:
        command += _build_bwrap_sandbox_mount_target_dir_options(python_venv_path)
        command += ["--ro-bind", str(python_venv_path), str(python_venv_path)]

    command += ["--clearenv"]
    command += _build_bwrap_worker_environment_options(
        agent_home_environment_variable=backend_config.agent_home_environment_variable,
        agent_state_dir=backend_config.agent_state_dir,
        python_venv_path=python_venv_path,
    )

    command += [str(WORKER_AGENT_BINARY_PATH)]
    command += _build_agent_command_tail(
        backend_config=backend_config,
        repo_path=repo_path,
        allowed_bash_commands=allowed_bash_commands or [],
    )
    return command


def _build_agent_command_tail(
    backend_config: AgentBackend,
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
        "untrusted",
        "exec",
        "-C",
        str(repo_path),
        "--sandbox",
        "danger-full-access",
        "--ephemeral",
        "-",
    ]


def _build_claude_command_tail(allowed_bash_commands: list[str]) -> list[str]:
    command_tail = [
        "--print",
        "--verbose",
        "--input-format",
        "text",
        "--output-format",
        "stream-json",
        "--include-partial-messages",
        "--include-hook-events",
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


def _extract_agent_result_text(backend_config: AgentBackend, raw_output: str) -> str:
    if backend_config.backend_name != "claude":
        return raw_output
    return _extract_claude_stream_result_text(raw_output)


def _extract_claude_stream_result_text(raw_output: str) -> str:
    result_text: str | None = None
    final_assistant_text: str | None = None
    malformed_lines: list[str] = []
    for line in raw_output.splitlines():
        if not line.strip():
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            malformed_lines.append(line)
            continue

        if event.get("type") == "result" and isinstance(event.get("result"), str):
            result_text = event["result"]
        if event.get("type") == "assistant":
            assistant_text = _extract_text_from_claude_assistant_event(event)
            if assistant_text:
                final_assistant_text = assistant_text

    if result_text is not None:
        return result_text
    if final_assistant_text is not None:
        return final_assistant_text
    if malformed_lines:
        raise RuntimeError("Claude stream-json output contained malformed JSON lines.")
    raise RuntimeError("Claude stream-json output did not include a result or assistant text event.")


def _extract_text_from_claude_assistant_event(event: dict[str, Any]) -> str:
    message = event.get("message")
    if not isinstance(message, dict):
        return ""
    content_blocks = message.get("content")
    if not isinstance(content_blocks, list):
        return ""
    return "".join(
        content_block["text"]
        for content_block in content_blocks
        if isinstance(content_block, dict)
        and content_block.get("type") == "text"
        and isinstance(content_block.get("text"), str)
    )


def _build_bwrap_worker_environment_options(
    agent_home_environment_variable: str,
    agent_state_dir: Path,
    python_venv_path: Path | None,
) -> list[str]:
    environment_variables = [
        ("HOME", str(WORKER_HOME_PATH)),
        ("TMPDIR", str(WORKER_TEMP_PATH)),
        (agent_home_environment_variable, str(agent_state_dir)),
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
        environment_variables.append(("VIRTUAL_ENV", str(python_venv_path)))

    options: list[str] = []
    for variable_name, value in environment_variables:
        options += ["--setenv", variable_name, value]
    return options


def _build_bwrap_runtime_mount_options() -> list[str]:
    options = ["--proc", "/proc"]
    options += _build_bwrap_host_os_runtime_mount_options()
    options += _build_bwrap_minimal_host_etc_file_mount_options()
    return options


def _build_bwrap_minimal_host_etc_file_mount_options() -> list[str]:
    options: list[str] = []
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


def _build_bwrap_agent_home_mount_options(agent_state_dir: Path) -> list[str]:
    options = _build_bwrap_sandbox_mount_target_dir_options(agent_state_dir)
    options += ["--bind", str(agent_state_dir), str(agent_state_dir)]
    if (agent_state_dir / ".tmp").is_dir():
        options += ["--tmpfs", str(agent_state_dir / ".tmp")]
    return options


def _build_bwrap_read_only_file_mount_options(host_path: Path, sandbox_path: Path) -> list[str]:
    if not host_path.is_file():
        return []

    options = _build_bwrap_sandbox_mount_target_dir_options(sandbox_path, create_target_dir=False)
    options += ["--ro-bind", str(host_path), str(sandbox_path)]
    return options


def _build_bwrap_read_only_dir_mount_options(host_path: Path, sandbox_path: Path) -> list[str]:
    if not host_path.is_dir():
        return []

    options = _build_bwrap_sandbox_mount_target_dir_options(sandbox_path)
    options += ["--ro-bind", str(host_path), str(sandbox_path)]
    return options


def _require_codex_home_path() -> Path:
    return _require_agent_state_dir_from_environment_variable("CODEX_HOME")


def _require_agent_state_dir_from_environment_variable(variable_name: str) -> Path:
    configured_path = os.environ.get(variable_name)
    if not configured_path:
        raise RuntimeError(f"{variable_name} must be set before running Ralph agents.")

    agent_state_dir = Path(configured_path).expanduser().resolve()
    if not agent_state_dir.is_dir():
        raise RuntimeError(f"{variable_name} does not exist: {agent_state_dir}")
    _refuse_agent_state_dir_that_exposes_other_sensitive_state(
        agent_state_dir=agent_state_dir,
        variable_name=variable_name,
    )
    return agent_state_dir


def _refuse_agent_state_dir_that_exposes_other_sensitive_state(agent_state_dir: Path, variable_name: str) -> None:
    for sensitive_path in _build_sensitive_paths_that_workers_must_not_see():
        if _paths_resolve_to_same_location(left_path=agent_state_dir, right_path=sensitive_path):
            continue
        if _paths_overlap(left_path=agent_state_dir, right_path=sensitive_path):
            raise ValueError(
                f"{variable_name} must not overlap other worker-hidden sensitive state: "
                f"{agent_state_dir} overlaps {sensitive_path}"
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
    _reject_worker_visible_path_that_overlaps_hidden_state(
        path=python_venv_path,
        role="Python venv",
    )
    return python_venv_path


def _reject_worker_visible_path_that_overlaps_hidden_state(path: Path, role: str) -> None:
    for sensitive_path in _build_sensitive_paths_that_workers_must_not_see():
        if _paths_overlap(left_path=path, right_path=sensitive_path):
            raise ValueError(
                f"{role} must not overlap worker-hidden sensitive state: "
                f"{path} overlaps {sensitive_path}"
            )


def _build_bwrap_sandbox_mount_target_dir_options(path: Path, *, create_target_dir: bool = True) -> list[str]:
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


def _find_last_non_empty_line(text: str) -> str:
    for line in reversed(text.splitlines()):
        if line.strip():
            return line.strip()
    return ""


def _read_default_codex_agent_command() -> str:
    return os.environ.get("RALPH_AGENT_COMMAND", os.environ.get("RALPH_CODEX_COMMAND", "codex"))


def _read_default_claude_agent_command() -> str:
    return os.environ.get("RALPH_AGENT_COMMAND", os.environ.get("RALPH_CLAUDE_COMMAND", "claude"))


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


def _recover_interrupted_codex_rules(job: RalphJob) -> None:
    backup_path = _find_interrupted_codex_rules_backup(job)
    if backup_path is None:
        return

    backup_snapshot = _read_codex_rules_backup(backup_path)
    codex_home_path = _read_codex_home_path_from_environment()
    if codex_home_path is None:
        backup_path.unlink()
        return

    rules_path = _codex_rules_path(codex_home_path)
    _restore_codex_rules(rules_path, backup_snapshot)
    backup_path.unlink()
    raise RuntimeError(
        f"Recovered Codex rules left by interrupted worker from {backup_path}. "
        "Please restart Ralph to continue."
    )


def _find_interrupted_codex_rules_backup(job: RalphJob) -> Path | None:
    if not job.tasks_path.is_dir():
        return None
    for task_dir in job.tasks_path.iterdir():
        if not task_dir.is_dir():
            continue
        backup_path = task_dir / CODEX_RULES_BACKUP_FILENAME
        if backup_path.is_file():
            return backup_path
    return None


def _read_codex_home_path_from_environment() -> Path | None:
    configured_path = os.environ.get("CODEX_HOME")
    if not configured_path:
        return None
    codex_home_path = Path(configured_path).expanduser().resolve()
    if not codex_home_path.is_dir():
        return None
    return codex_home_path


def _codex_rules_path(codex_home_path: Path) -> Path:
    return codex_home_path / "rules" / "default.rules"


@dataclass(frozen=True)
class CodexRulesSnapshot:
    existed: bool
    content: str | None


def _snapshot_codex_rules(rules_path: Path) -> CodexRulesSnapshot:
    if not rules_path.is_file():
        return CodexRulesSnapshot(existed=False, content=None)
    return CodexRulesSnapshot(existed=True, content=rules_path.read_text(encoding="utf-8"))


def _write_codex_rules_backup(backup_path: Path, snapshot: CodexRulesSnapshot) -> None:
    backup_content = {
        "existed": snapshot.existed,
        "content": snapshot.content,
    }
    backup_path.parent.mkdir(parents=True, exist_ok=True)
    backup_path.write_text(json.dumps(backup_content, indent=2), encoding="utf-8")


def _read_codex_rules_backup(backup_path: Path) -> CodexRulesSnapshot:
    backup_content = json.loads(backup_path.read_text(encoding="utf-8"))
    return CodexRulesSnapshot(
        existed=backup_content["existed"],
        content=backup_content["content"],
    )


def _restore_codex_rules(rules_path: Path, snapshot: CodexRulesSnapshot) -> None:
    if not snapshot.existed:
        rules_path.unlink(missing_ok=True)
        return
    rules_path.parent.mkdir(parents=True, exist_ok=True)
    rules_path.write_text(snapshot.content, encoding="utf-8")


def _generate_codex_execpolicy_rules(allowed_bash_commands: list[str]) -> str:
    rules_lines: list[str] = []
    for command in allowed_bash_commands:
        pattern = _parse_command_to_execpolicy_pattern(command)
        rules_lines.append(f'prefix_rule(pattern={pattern!r}, decision="allow")')
    return "\n".join(rules_lines) + "\n"


def _parse_command_to_execpolicy_pattern(command: str) -> list[str]:
    tokens = shlex.split(command)
    if not tokens:
        raise ValueError(f"Empty command cannot be converted to execpolicy pattern: {command!r}")
    if tokens == ["*"]:
        raise ValueError(f"Command cannot be only a wildcard: {command!r}")
    for i, token in enumerate(tokens[:-1]):
        if token == "*":
            raise ValueError(
                f"Wildcard '*' is only allowed as the final token in command: {command!r}"
            )
    if tokens[-1] == "*":
        tokens = tokens[:-1]
    return tokens


def _write_codex_rules_atomically(rules_path: Path, content: str) -> None:
    rules_path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = rules_path.with_suffix(".rules.tmp")
    try:
        temp_path.write_text(content, encoding="utf-8")
        temp_path.replace(rules_path)
    except Exception:
        temp_path.unlink(missing_ok=True)
        raise


if __name__ == "__main__":
    main()
