from __future__ import annotations

import argparse
import datetime as dt
import os
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from string import Formatter
from typing import Any

try:
    import yaml
except ImportError as error:
    raise SystemExit("Ralph requires PyYAML. Install it with: python -m pip install PyYAML") from error


RALPH_HOME_PATH = Path.home() / ".ralph"
DEFAULT_MAX_ITERATIONS = 10
PROMISE_PATTERN = re.compile(r"<promise>(DONE|BLOCKED|ABORT)</promise>")
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


@dataclass(frozen=True)
class RalphProject:
    project_name: str
    project_path: Path
    plan_path: Path
    ledger_path: Path
    runs_path: Path


@dataclass(frozen=True)
class TaskSelection:
    task: dict[str, Any]
    shared_plan_context: str
    active_task_plan_context: str


@dataclass(frozen=True)
class WorkerResult:
    promise: str
    output: str


def main(argv: list[str] | None = None) -> None:
    arguments = _parse_arguments(argv)
    if arguments.command == "run":
        _run_ralph_loop(arguments)
        return
    if arguments.command == "smoke-test":
        _run_worker_visibility_smoke_test(
            repo_path=Path(arguments.repo_path).expanduser(),
            codex_command=arguments.codex_command,
        )
        return
    raise SystemExit(f"Unknown command: {arguments.command}")


def _run_ralph_loop(arguments: argparse.Namespace) -> None:
    repo_path = Path(arguments.repo_path).expanduser().resolve()
    project = _find_ralph_project(arguments.project_name)
    _prepare_project_directories(project)
    _refuse_unsafe_starting_state(repo_path, project)
    _run_worker_visibility_smoke_test(repo_path=repo_path, codex_command=arguments.codex_command)

    for _ in range(arguments.max_iterations):
        ledger = _read_yaml_file(project.ledger_path)
        plan_text = project.plan_path.read_text()
        selection = _select_next_task_from_plan_and_ledger(ledger, plan_text)
        if selection is None:
            print("No runnable Ralph tasks remain.")
            return

        run_path = _create_run_directory(project.runs_path, selection.task["id"])
        prompt = _render_worker_prompt(repo_path=repo_path, ledger=ledger, selection=selection)
        worker_result = _run_codex_worker(
            repo_path=repo_path,
            prompt=prompt,
            codex_command=arguments.codex_command,
            output_path=run_path / "worker-output.txt",
        )
        _write_text(run_path / "promise.txt", worker_result.promise)

        if worker_result.promise != "DONE":
            print(f"Worker stopped with {worker_result.promise}. See {run_path}")
            return

        verification_output = _run_verification_commands(
            repo_path=repo_path,
            task=selection.task,
            output_path=run_path / "verification-output.txt",
        )
        _write_text(run_path / "verification-output.txt", verification_output)

        ledger = _mark_task_done(ledger, selection.task["id"])
        _write_yaml_file(project.ledger_path, ledger)
        commit_hash = _commit_target_repo_changes(repo_path=repo_path, task=selection.task)
        _write_text(run_path / "commit.txt", commit_hash)
        print(f"Completed {selection.task['id']}: {commit_hash}")

    raise SystemExit(f"Reached max iterations: {arguments.max_iterations}")


def _parse_arguments(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run Codex Ralph loops with sliced plan context.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    run_parser = subparsers.add_parser("run", help="Run the Ralph loop for one project.")
    run_parser.add_argument("--repo-path", required=True)
    run_parser.add_argument("--project-name", required=True)
    run_parser.add_argument("--max-iterations", type=int, default=DEFAULT_MAX_ITERATIONS)
    run_parser.add_argument("--codex-command", default=_default_codex_command())

    smoke_parser = subparsers.add_parser("smoke-test", help="Verify the worker sandbox hides ~/.ralph.")
    smoke_parser.add_argument("--repo-path", required=True)
    smoke_parser.add_argument("--codex-command", default=_default_codex_command())

    return parser.parse_args(argv)


def _find_ralph_project(project_name: str) -> RalphProject:
    project_path = RALPH_HOME_PATH / "projects" / project_name
    return RalphProject(
        project_name=project_name,
        project_path=project_path,
        plan_path=project_path / "PLAN.md",
        ledger_path=project_path / "ledger.yaml",
        runs_path=project_path / "runs",
    )


def _prepare_project_directories(project: RalphProject) -> None:
    project.runs_path.mkdir(parents=True, exist_ok=True)
    if not project.plan_path.is_file():
        raise FileNotFoundError(f"Missing Ralph plan: {project.plan_path}")
    if not project.ledger_path.is_file():
        raise FileNotFoundError(f"Missing Ralph ledger: {project.ledger_path}")


def _refuse_unsafe_starting_state(repo_path: Path, project: RalphProject) -> None:
    if not repo_path.is_dir():
        raise FileNotFoundError(f"Target repo does not exist: {repo_path}")
    if _is_path_inside(child_path=project.project_path, parent_path=repo_path):
        raise RuntimeError(f"Ralph project path must not be inside target repo: {project.project_path}")
    if _path_exists_under_repo(repo_path, "PLAN.md"):
        raise RuntimeError("Refusing to run because PLAN.md exists under the target repo.")
    if _path_exists_under_repo(repo_path, "ledger.yaml"):
        raise RuntimeError("Refusing to run because ledger.yaml exists under the target repo.")
    if _path_exists_under_repo(repo_path, ".ralph"):
        raise RuntimeError("Refusing to run because .ralph exists under the target repo.")
    if _git_status(repo_path):
        raise RuntimeError("Refusing to run because the target repo is dirty.")


def _select_next_task_from_plan_and_ledger(
    ledger: dict[str, Any],
    plan_text: str,
) -> TaskSelection | None:
    tasks = _read_tasks_from_ledger(ledger)
    shared_plan_context = _extract_shared_plan_context(plan_text)
    task_plan_contexts = _extract_task_plan_contexts(plan_text)
    _validate_plan_and_ledger_match(tasks, task_plan_contexts)

    completed_task_ids = {task["id"] for task in tasks if task.get("status") == "done"}
    for task in tasks:
        if task.get("status") != "pending":
            continue
        depends_on = task.get("depends_on") or []
        if all(task_id in completed_task_ids for task_id in depends_on):
            return TaskSelection(
                task=task,
                shared_plan_context=shared_plan_context,
                active_task_plan_context=task_plan_contexts[task["id"]],
            )
    return None


def _render_worker_prompt(
    repo_path: Path,
    ledger: dict[str, Any],
    selection: TaskSelection,
) -> str:
    prompt_template_path = Path(__file__).resolve().parent / "PROMPT.md"
    prompt_template = prompt_template_path.read_text()
    visible_ledger = _remove_plan_like_fields(ledger)
    active_task = _remove_plan_like_fields(selection.task)

    return prompt_template.format(
        repo_path=repo_path,
        active_task_yaml=_dump_yaml(active_task),
        visible_ledger_yaml=_dump_yaml(visible_ledger),
        shared_plan_context=selection.shared_plan_context.strip(),
        active_task_plan_context=selection.active_task_plan_context.strip(),
    )


def _run_codex_worker(
    repo_path: Path,
    prompt: str,
    codex_command: str,
    output_path: Path,
) -> WorkerResult:
    command = _build_bwrap_codex_command(repo_path=repo_path, codex_command=codex_command)
    completed_process = subprocess.run(
        command,
        input=prompt,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )
    _write_text(output_path, completed_process.stdout)
    if completed_process.returncode != 0:
        raise RuntimeError(f"Codex worker failed with exit code {completed_process.returncode}. See {output_path}")
    promise = _parse_worker_promise(completed_process.stdout)
    return WorkerResult(promise=promise, output=completed_process.stdout)


def _run_worker_visibility_smoke_test(repo_path: Path, codex_command: str) -> None:
    command = _build_bwrap_codex_command(repo_path=repo_path, codex_command=codex_command)
    prompt = (
        "Run exactly this shell command: "
        "test -e /home/alovyachowdhury/.ralph && echo VISIBLE || echo HIDDEN. "
        "Then answer only the word it prints."
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
        raise RuntimeError(f"Ralph worker sandbox smoke test failed:\n{completed_process.stdout}")
    if _last_non_empty_line(completed_process.stdout) != "HIDDEN":
        raise RuntimeError(f"Ralph worker can see ~/.ralph. Refusing to run:\n{completed_process.stdout}")


def _build_bwrap_codex_command(repo_path: Path, codex_command: str) -> list[str]:
    bwrap_path = shutil.which("bwrap")
    if bwrap_path is None:
        raise RuntimeError("Ralph requires bubblewrap installed as `bwrap`.")

    codex_binary_path = _resolve_codex_binary_path(codex_command)
    codex_home_path = Path(os.environ.get("CODEX_HOME", Path.home() / ".codex")).expanduser().resolve()
    local_path = Path.home() / ".local"
    visible_codex_home_path = Path("/tmp/codex-home")

    return [
        bwrap_path,
        "--ro-bind",
        "/",
        "/",
        "--tmpfs",
        str(Path.home()),
        "--tmpfs",
        "/tmp",
        "--bind",
        str(codex_home_path),
        str(visible_codex_home_path),
        "--ro-bind",
        str(local_path),
        str(local_path),
        "--symlink",
        str(visible_codex_home_path),
        str(codex_home_path),
        "--bind",
        str(repo_path),
        str(repo_path),
        "--dev",
        "/dev",
        "--setenv",
        "HOME",
        str(Path.home()),
        "--setenv",
        "CODEX_HOME",
        str(codex_home_path),
        "--setenv",
        "PATH",
        _worker_path_value(),
        str(codex_binary_path),
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


def _resolve_codex_binary_path(codex_command: str) -> Path:
    resolved_command = shutil.which(codex_command)
    if resolved_command is None:
        raise RuntimeError(f"Codex command not found: {codex_command}")
    return Path(resolved_command).resolve()


def _run_verification_commands(repo_path: Path, task: dict[str, Any], output_path: Path) -> str:
    verification_output = []
    for command in task.get("verification_commands") or []:
        completed_process = subprocess.run(
            command,
            cwd=repo_path,
            shell=True,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            check=False,
        )
        verification_output.append(f"$ {command}\n{completed_process.stdout}")
        if completed_process.returncode != 0:
            _write_text(output_path, "\n".join(verification_output))
            raise RuntimeError(f"Verification failed for task {task['id']}: {command}")
    return "\n".join(verification_output)


def _commit_target_repo_changes(repo_path: Path, task: dict[str, Any]) -> str:
    if not _git_status(repo_path):
        raise RuntimeError(f"Task {task['id']} returned DONE but produced no target repo changes.")
    _run_git(repo_path, "add", ".")
    message = f"Ralph: {task['id']} {task['title']}"
    _run_git(repo_path, "commit", "-m", message)
    return _run_git(repo_path, "rev-parse", "HEAD").strip()


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
    return tasks


def _validate_task_shape(task: Any) -> None:
    if not isinstance(task, dict):
        raise ValueError("Every ledger task must be a mapping.")
    for required_key in ["id", "title", "status"]:
        if not task.get(required_key):
            raise ValueError(f"Every ledger task must have {required_key}.")
    if task["status"] not in {"pending", "done", "blocked", "aborted"}:
        raise ValueError(f"Invalid task status for {task['id']}: {task['status']}")
    if _contains_forbidden_plan_field(task):
        raise ValueError(f"Ledger task {task['id']} contains plan-like prose fields.")


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


def _parse_worker_promise(output: str) -> str:
    promises = PROMISE_PATTERN.findall(output)
    if len(promises) != 1:
        raise RuntimeError(f"Expected exactly one worker promise, found {len(promises)}.")
    return promises[0]


def _create_run_directory(runs_path: Path, task_id: str) -> Path:
    timestamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    run_path = runs_path / f"{timestamp}-{task_id}"
    run_path.mkdir(parents=True, exist_ok=False)
    return run_path


def _path_exists_under_repo(repo_path: Path, name: str) -> bool:
    return any(path.name == name for path in repo_path.rglob(name))


def _is_path_inside(child_path: Path, parent_path: Path) -> bool:
    try:
        child_path.resolve().relative_to(parent_path.resolve())
    except ValueError:
        return False
    return True


def _git_status(repo_path: Path) -> str:
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


def _last_non_empty_line(text: str) -> str:
    for line in reversed(text.splitlines()):
        if line.strip():
            return line.strip()
    return ""


def _default_codex_command() -> str:
    return os.environ.get("RALPH_CODEX_COMMAND", "codex")


def _worker_path_value() -> str:
    return ":".join(
        [
            str(Path.home() / ".local" / "bin"),
            "/usr/local/sbin",
            "/usr/local/bin",
            "/usr/sbin",
            "/usr/bin",
            "/sbin",
            "/bin",
        ]
    )


if __name__ == "__main__":
    main()
