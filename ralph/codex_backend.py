from __future__ import annotations

import contextlib
import json
import os
import shlex
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Iterator

if TYPE_CHECKING:
    from ralph.agent_backends import AgentBackend


CODEX_RULES_BACKUP_FILENAME = "codex-rules-backup.marker"
CODEX_WORKER_HOME_SEED_FILENAMES = (
    "auth.json",
    ".credentials.json",
    "config.toml",
    "AGENTS.md",
    "installation_id",
    "version.json",
)


@dataclass(frozen=True)
class CodexRulesSnapshot:
    existed: bool
    content: str | None


def build_codex_agent_backend(agent_command: str | None) -> "AgentBackend":
    from ralph.agent_backends import AgentBackend, read_default_codex_agent_command

    agent_state_dir = require_agent_state_dir_from_environment_variable("CODEX_HOME")
    return AgentBackend(
        backend_name="codex",
        command_name=agent_command or read_default_codex_agent_command(),
        agent_state_dir=agent_state_dir,
        agent_home_environment_variable="CODEX_HOME",
    )


def build_codex_command_tail(repo_path: Path) -> list[str]:
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


@contextlib.contextmanager
def prepare_codex_worker_home(source_agent_backend: "AgentBackend") -> Iterator["AgentBackend"]:
    from ralph.agent_backends import AgentBackend

    source_codex_home_path = source_agent_backend.agent_state_dir
    with tempfile.TemporaryDirectory(prefix="ralph-codex-home-") as worker_home_dir:
        worker_codex_home_path = Path(worker_home_dir).resolve()
        _copy_codex_worker_seed_files(
            source_codex_home_path=source_codex_home_path,
            worker_codex_home_path=worker_codex_home_path,
        )
        _copy_codex_worker_skills(
            source_codex_home_path=source_codex_home_path,
            worker_codex_home_path=worker_codex_home_path,
        )
        _create_codex_worker_runtime_dirs(worker_codex_home_path)
        read_only_home_mounts = _prepare_codex_worker_packages(
            source_codex_home_path=source_codex_home_path,
            worker_codex_home_path=worker_codex_home_path,
        )
        yield AgentBackend(
            backend_name=source_agent_backend.backend_name,
            command_name=source_agent_backend.command_name,
            agent_state_dir=worker_codex_home_path,
            agent_home_environment_variable=source_agent_backend.agent_home_environment_variable,
            read_only_home_mounts=read_only_home_mounts,
        )


def require_codex_home_path() -> Path:
    return require_agent_state_dir_from_environment_variable("CODEX_HOME")


def require_agent_state_dir_from_environment_variable(variable_name: str) -> Path:
    from ralph.sandbox import (
        build_sensitive_paths_that_workers_must_not_see,
        paths_overlap,
        paths_resolve_to_same_location,
    )

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
    from ralph.sandbox import (
        build_sensitive_paths_that_workers_must_not_see,
        paths_overlap,
        paths_resolve_to_same_location,
    )

    for sensitive_path in build_sensitive_paths_that_workers_must_not_see():
        if paths_resolve_to_same_location(left_path=agent_state_dir, right_path=sensitive_path):
            continue
        if paths_overlap(left_path=agent_state_dir, right_path=sensitive_path):
            raise ValueError(
                f"{variable_name} must not overlap other worker-hidden sensitive state: "
                f"{agent_state_dir} overlaps {sensitive_path}"
            )


def _copy_codex_worker_seed_files(source_codex_home_path: Path, worker_codex_home_path: Path) -> None:
    for seed_filename in CODEX_WORKER_HOME_SEED_FILENAMES:
        source_seed_path = source_codex_home_path / seed_filename
        worker_seed_path = worker_codex_home_path / seed_filename
        if source_seed_path.is_file():
            shutil.copy2(source_seed_path, worker_seed_path)


def _copy_codex_worker_skills(source_codex_home_path: Path, worker_codex_home_path: Path) -> None:
    source_skills_path = source_codex_home_path / "skills"
    worker_skills_path = worker_codex_home_path / "skills"
    if source_skills_path.is_dir():
        shutil.copytree(source_skills_path, worker_skills_path, symlinks=False)


def _create_codex_worker_runtime_dirs(worker_codex_home_path: Path) -> None:
    (worker_codex_home_path / ".tmp").mkdir(parents=True, exist_ok=True)
    (worker_codex_home_path / "rules").mkdir(parents=True, exist_ok=True)


def _prepare_codex_worker_packages(
    source_codex_home_path: Path,
    worker_codex_home_path: Path,
) -> tuple["AgentHomeMount", ...]:
    from ralph.agent_backends import AgentHomeMount

    source_standalone_path = source_codex_home_path / "packages" / "standalone"
    worker_standalone_path = worker_codex_home_path / "packages" / "standalone"
    source_releases_path = source_standalone_path / "releases"
    worker_releases_path = worker_standalone_path / "releases"

    if not source_standalone_path.exists():
        return ()

    worker_standalone_path.mkdir(parents=True, exist_ok=True)
    _copy_codex_standalone_install_lock(
        source_standalone_path=source_standalone_path,
        worker_standalone_path=worker_standalone_path,
    )
    if not source_releases_path.is_dir():
        return ()

    _link_codex_worker_current_release(
        source_standalone_path=source_standalone_path,
        source_releases_path=source_releases_path,
        worker_standalone_path=worker_standalone_path,
        worker_releases_path=worker_releases_path,
    )
    return (
        AgentHomeMount(
            host_path=source_releases_path,
            worker_path=worker_releases_path,
        ),
    )


def _copy_codex_standalone_install_lock(source_standalone_path: Path, worker_standalone_path: Path) -> None:
    source_install_lock_path = source_standalone_path / "install.lock"
    worker_install_lock_path = worker_standalone_path / "install.lock"
    if source_install_lock_path.is_file():
        shutil.copy2(source_install_lock_path, worker_install_lock_path)


def _link_codex_worker_current_release(
    source_standalone_path: Path,
    source_releases_path: Path,
    worker_standalone_path: Path,
    worker_releases_path: Path,
) -> None:
    source_current_path = source_standalone_path / "current"
    if not source_current_path.exists():
        return

    source_current_release_path = source_current_path.resolve()
    if not source_current_release_path.is_relative_to(source_releases_path):
        return

    worker_current_release_path = worker_releases_path / source_current_release_path.relative_to(source_releases_path)
    worker_current_path = worker_standalone_path / "current"
    worker_current_path.symlink_to(worker_current_release_path)


@contextlib.contextmanager
def codex_permission_setup(
    agent_backend: "AgentBackend",
    allowed_bash_commands: list[str],
    task_path: Path,
) -> Iterator[None]:
    codex_home_path = agent_backend.agent_state_dir
    rules_path = codex_rules_path(codex_home_path)
    backup_path = task_path / CODEX_RULES_BACKUP_FILENAME

    original_rules_snapshot = snapshot_codex_rules(rules_path)
    write_codex_rules_backup(backup_path, original_rules_snapshot)

    try:
        generated_rules = generate_codex_execpolicy_rules(allowed_bash_commands)
        write_codex_rules_atomically(rules_path, generated_rules)
        yield
    finally:
        restore_codex_rules(rules_path, original_rules_snapshot)
        backup_path.unlink(missing_ok=True)


def recover_interrupted_codex_rules(job: "RalphJob") -> None:
    from ralph.run_ralph_loop import RalphJob

    backup_path = find_interrupted_codex_rules_backup(job)
    if backup_path is None:
        return

    backup_snapshot = read_codex_rules_backup(backup_path)
    codex_home_path = read_codex_home_path_from_environment()
    if codex_home_path is None:
        backup_path.unlink()
        return

    rules_path = codex_rules_path(codex_home_path)
    restore_codex_rules(rules_path, backup_snapshot)
    backup_path.unlink()
    raise RuntimeError(
        f"Recovered Codex rules left by interrupted worker from {backup_path}. "
        "Please restart Ralph to continue."
    )


def find_interrupted_codex_rules_backup(job: "RalphJob") -> Path | None:
    if not job.tasks_path.is_dir():
        return None
    for task_dir in job.tasks_path.iterdir():
        if not task_dir.is_dir():
            continue
        backup_path = task_dir / CODEX_RULES_BACKUP_FILENAME
        if backup_path.is_file():
            return backup_path
    return None


def read_codex_home_path_from_environment() -> Path | None:
    configured_path = os.environ.get("CODEX_HOME")
    if not configured_path:
        return None
    codex_home_path = Path(configured_path).expanduser().resolve()
    if not codex_home_path.is_dir():
        return None
    return codex_home_path


def codex_rules_path(codex_home_path: Path) -> Path:
    return codex_home_path / "rules" / "default.rules"


def snapshot_codex_rules(rules_path: Path) -> CodexRulesSnapshot:
    if not rules_path.is_file():
        return CodexRulesSnapshot(existed=False, content=None)
    return CodexRulesSnapshot(existed=True, content=rules_path.read_text(encoding="utf-8"))


def write_codex_rules_backup(backup_path: Path, snapshot: CodexRulesSnapshot) -> None:
    backup_content = {
        "existed": snapshot.existed,
        "content": snapshot.content,
    }
    backup_path.parent.mkdir(parents=True, exist_ok=True)
    backup_path.write_text(json.dumps(backup_content, indent=2), encoding="utf-8")


def read_codex_rules_backup(backup_path: Path) -> CodexRulesSnapshot:
    backup_content = json.loads(backup_path.read_text(encoding="utf-8"))
    return CodexRulesSnapshot(
        existed=backup_content["existed"],
        content=backup_content["content"],
    )


def restore_codex_rules(rules_path: Path, snapshot: CodexRulesSnapshot) -> None:
    if not snapshot.existed:
        rules_path.unlink(missing_ok=True)
        return
    rules_path.parent.mkdir(parents=True, exist_ok=True)
    rules_path.write_text(snapshot.content, encoding="utf-8")


def generate_codex_execpolicy_rules(allowed_bash_commands: list[str]) -> str:
    rules_lines: list[str] = []
    for command in allowed_bash_commands:
        pattern = parse_command_to_execpolicy_pattern(command)
        rules_lines.append(f'prefix_rule(pattern={pattern!r}, decision="allow")')
    return "\n".join(rules_lines) + "\n"


def parse_command_to_execpolicy_pattern(command: str) -> list[str]:
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


def write_codex_rules_atomically(rules_path: Path, content: str) -> None:
    rules_path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = rules_path.with_suffix(".rules.tmp")
    try:
        temp_path.write_text(content, encoding="utf-8")
        temp_path.replace(rules_path)
    except Exception:
        temp_path.unlink(missing_ok=True)
        raise
