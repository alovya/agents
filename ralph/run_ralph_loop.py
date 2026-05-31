from __future__ import annotations

import argparse
import datetime as dt
import os
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


RALPH_HOME_PATH = Path.home() / ".ralph"
NOTION_TASK_TRACKER_HOME_PATH = Path.home() / ".notion-task-tracker"
DEFAULT_MAX_ITERATIONS = 10
PROMISE_PATTERN = re.compile(r"<promise>(DONE|BLOCKED|ABORT)</promise>")
PROMISE_LINE_PATTERN = re.compile(r"^<promise>(DONE|BLOCKED|ABORT)</promise>$")
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


def main(argv: list[str] | None = None) -> None:
    arguments = _parse_arguments(argv)
    if arguments.command == "run":
        _run_ralph_loop(arguments)
        return
    if arguments.command == "smoke-test":
        _run_agent_visibility_smoke_test(
            repo_path=Path(arguments.repo_path).expanduser(),
            agent_command=arguments.agent_command,
            python_venv_path=_resolve_python_venv_path(arguments.python_venv),
        )
        return
    raise SystemExit(f"Unknown command: {arguments.command}")


def _run_ralph_loop(arguments: argparse.Namespace) -> None:
    repo_path = Path(arguments.repo_path).expanduser().resolve()
    python_venv_path = _resolve_python_venv_path(arguments.python_venv)
    job = _find_ralph_job(arguments.job_name)
    _prepare_job_directories(job)
    _refuse_unsafe_starting_state(repo_path, job)
    _run_agent_visibility_smoke_test(
        repo_path=repo_path,
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
        prompt = _render_agent_prompt(
            repo_path=repo_path,
            ledger=ledger,
            selection=selection,
            python_venv_path=python_venv_path,
        )
        agent_result = _run_agent(
            repo_path=repo_path,
            prompt=prompt,
            agent_command=arguments.agent_command,
            python_venv_path=python_venv_path,
            output_path=task_path / "agent-output.txt",
            tee_output=arguments.tee_agent_output,
        )
        _write_text(task_path / "promise.txt", agent_result.promise)

        if agent_result.promise != "DONE":
            print(f"Agent stopped with {agent_result.promise}. See {task_path}")
            return

        _verify_task_result(
            repo_path=repo_path,
            task=selection.task,
            task_path=task_path,
        )
        commit_hash = _commit_verified_task(
            repo_path=repo_path,
            job=job,
            ledger=ledger,
            selection=selection,
            task_path=task_path,
        )
        print(f"Completed {selection.task['id']}: {commit_hash}")

    raise SystemExit(f"Reached max iterations: {arguments.max_iterations}")


def _verify_task_result(
    repo_path: Path,
    task: dict[str, Any],
    task_path: Path,
) -> None:
    verification_output = _run_verification_commands(
        repo_path=repo_path,
        task=task,
        output_path=task_path / "verification-output.txt",
    )
    _write_text(task_path / "verification-output.txt", verification_output)


def _commit_verified_task(
    repo_path: Path,
    job: RalphJob,
    ledger: dict[str, Any],
    selection: TaskSelection,
    task_path: Path,
) -> str:
    commit_hash = _commit_target_repo_changes(repo_path=repo_path, task=selection.task)
    _write_text(task_path / "commit.txt", commit_hash)

    advanced_ledger = _mark_task_done(ledger, selection.task["id"])
    _write_yaml_file(job.ledger_path, advanced_ledger)
    return commit_hash


def _parse_arguments(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run Ralph task loops with sliced plan context.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    run_parser = subparsers.add_parser("run", help="Run the Ralph loop for one job.")
    run_parser.add_argument("--repo-path", required=True)
    run_parser.add_argument("--job-name", required=True)
    run_parser.add_argument("--max-iterations", type=int, default=DEFAULT_MAX_ITERATIONS)
    run_parser.add_argument("--agent-command", default=_read_default_agent_command())
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

    smoke_parser = subparsers.add_parser("smoke-test", help="Verify the agent sandbox hides ~/.ralph.")
    smoke_parser.add_argument("--repo-path", required=True)
    smoke_parser.add_argument("--agent-command", default=_read_default_agent_command())
    smoke_parser.add_argument("--python-venv")

    return parser.parse_args(argv)


def _find_ralph_job(job_name: str) -> RalphJob:
    job_path = RALPH_HOME_PATH / "jobs" / job_name
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
    if _contains_path_named_under_repo(repo_path, "PLAN.md"):
        raise RuntimeError("Refusing to run because PLAN.md exists under the target repo.")
    if _contains_path_named_under_repo(repo_path, "ledger.yaml"):
        raise RuntimeError("Refusing to run because ledger.yaml exists under the target repo.")
    if _contains_path_named_under_repo(repo_path, ".ralph"):
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
    prompt: str,
    agent_command: str,
    python_venv_path: Path | None,
    output_path: Path,
    tee_output: bool,
) -> AgentResult:
    _write_text(output_path, "")
    command = _build_bwrap_agent_command(
        repo_path=repo_path,
        agent_command=agent_command,
        python_venv_path=python_venv_path,
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
    agent_command: str,
    python_venv_path: Path | None,
) -> None:
    command = _build_bwrap_agent_command(
        repo_path=repo_path,
        agent_command=agent_command,
        python_venv_path=python_venv_path,
    )
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
        raise RuntimeError(f"Ralph agent sandbox smoke test failed:\n{completed_process.stdout}")
    if _find_last_non_empty_line(completed_process.stdout) != "HIDDEN":
        raise RuntimeError(f"Ralph agent can see ~/.ralph. Refusing to run:\n{completed_process.stdout}")


def _build_bwrap_agent_command(
    repo_path: Path,
    agent_command: str,
    python_venv_path: Path | None,
) -> list[str]:
    bwrap_path = shutil.which("bwrap")
    if bwrap_path is None:
        raise RuntimeError("Ralph requires bubblewrap installed as `bwrap`.")

    agent_binary_path = _resolve_agent_binary_path(agent_command)
    agent_home_path = Path(os.environ.get("CODEX_HOME", Path.home() / ".codex")).expanduser().resolve()
    local_path = Path.home() / ".local"

    command = [bwrap_path]
    command += ["--ro-bind", "/", "/"]
    command += ["--tmpfs", str(Path.home())]
    command += ["--tmpfs", "/tmp"]
    command += ["--ro-bind", str(local_path), str(local_path)]
    command += ["--bind", str(repo_path), str(repo_path)]
    command += ["--dev", "/dev"]

    command += _build_bwrap_home_dir_options(agent_home_path)
    command += ["--bind", str(agent_home_path), str(agent_home_path)]

    if python_venv_path is not None:
        command += _build_bwrap_home_dir_options(python_venv_path)
        command += ["--ro-bind", str(python_venv_path), str(python_venv_path)]

    # TODO: Replace this ntt-specific state bind with a generic agent-state story.
    # For now Ralph agents need installed ntt to see the same tracker cache path
    # that ntt uses by default: ~/.notion-task-tracker/notion_tasks_graph.json.
    if NOTION_TASK_TRACKER_HOME_PATH.is_dir():
        command += _build_bwrap_home_dir_options(NOTION_TASK_TRACKER_HOME_PATH)
        command += ["--bind", str(NOTION_TASK_TRACKER_HOME_PATH), str(NOTION_TASK_TRACKER_HOME_PATH)]

    command += ["--setenv", "HOME", str(Path.home())]
    command += ["--setenv", "PATH", _build_agent_path_value(python_venv_path)]

    if python_venv_path is not None:
        command += ["--setenv", "VIRTUAL_ENV", str(python_venv_path)]
        command += ["--setenv", "BASH_ENV", str(python_venv_path / "bin" / "activate")]

    if "NOTION_API_KEY" in os.environ:
        command += ["--setenv", "NOTION_API_KEY", os.environ["NOTION_API_KEY"]]

    command += [str(agent_binary_path)]
    command += ["--ask-for-approval", "never"]
    command += ["exec", "-C", str(repo_path)]
    command += ["--sandbox", "danger-full-access"]
    command += ["--ephemeral"]
    command += ["--ignore-rules"]
    command += ["-"]
    return command


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
    if _is_path_inside(child_path=python_venv_path, parent_path=RALPH_HOME_PATH):
        raise ValueError(
            f"Python venv must not live under {RALPH_HOME_PATH}; mounting it would expose Ralph controller state."
        )
    return python_venv_path


def _build_bwrap_home_dir_options(path: Path) -> list[str]:
    home_path = Path.home()
    if not path.is_relative_to(home_path):
        return []

    relative_path = path.relative_to(home_path)
    options: list[str] = []
    current_path = home_path
    for part in relative_path.parts:
        current_path = current_path / part
        options.extend(["--dir", str(current_path)])
    return options


def _resolve_agent_binary_path(agent_command: str) -> Path:
    resolved_command = shutil.which(agent_command)
    if resolved_command is None:
        raise RuntimeError(f"Agent command not found: {agent_command}")
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
    if not _read_git_status(repo_path):
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


def _contains_path_named_under_repo(repo_path: Path, name: str) -> bool:
    return any(path.name == name for path in repo_path.rglob(name))


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


def _read_default_agent_command() -> str:
    return os.environ.get("RALPH_AGENT_COMMAND", os.environ.get("RALPH_CODEX_COMMAND", "codex"))


def _describe_tool_environment(python_venv_path: Path | None) -> str:
    if python_venv_path is None:
        return "No Python venv was configured for agent tools. Use only tools already available on PATH."

    return "\n".join(
        [
            f"Python venv: {python_venv_path}",
            f"`{python_venv_path / 'bin'}` is already first on PATH.",
            f"`VIRTUAL_ENV` is already set to `{python_venv_path}`.",
            f"`BASH_ENV` points at `{python_venv_path / 'bin' / 'activate'}` so shell tool calls keep the venv active.",
            "Use installed CLIs directly, for example `ntt ...`.",
        ]
    )


def _build_agent_path_value(python_venv_path: Path | None) -> str:
    path_entries = []
    if python_venv_path is not None:
        path_entries.append(str(python_venv_path / "bin"))
    path_entries.extend(
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
    return ":".join(
        path_entries
    )


if __name__ == "__main__":
    main()
