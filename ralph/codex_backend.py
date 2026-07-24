from __future__ import annotations

import contextlib
import json
import os
import shlex
import shutil
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING, Iterator

if TYPE_CHECKING:
    from ralph.agent_backends import AgentBackend


CODEX_WORKER_HOME_SEED_FILENAMES = (
    "auth.json",
    ".credentials.json",
    "config.toml",
    "AGENTS.md",
    "installation_id",
    "version.json",
)


def build_codex_agent_backend(agent_command: str | None) -> "AgentBackend":
    from ralph.agent_backends import AgentBackend, read_default_codex_agent_command

    agent_config_dir = require_agent_config_dir_from_environment_variable("CODEX_HOME")
    return AgentBackend(
        backend_name="codex",
        command_name=agent_command or read_default_codex_agent_command(),
        agent_config_dir=agent_config_dir,
        agent_home_environment_variable="CODEX_HOME",
    )


def build_codex_command_tail(repo_path: Path) -> list[str]:
    return [
        "--ask-for-approval",
        "never",
        "exec",
        "-C",
        str(repo_path),
        "--sandbox",
        "danger-full-access",
        "--ephemeral",
        "-",
    ]


def build_direct_codex_command(
    agent_backend: "AgentBackend",
    repo_path: Path,
    tool_virtual_environment_path: Path,
    controller_path: str,
) -> list[str]:
    return [
        agent_backend.command_name,
        "--config",
        f"shell_environment_policy.set.PATH={json.dumps(controller_path)}",
        "--config",
        (
            "shell_environment_policy.set.VIRTUAL_ENV="
            f"{json.dumps(str(tool_virtual_environment_path))}"
        ),
        "--ask-for-approval",
        "never",
        "exec",
        "-C",
        str(repo_path),
        "--sandbox",
        "danger-full-access",
        "--ephemeral",
        "-",
    ]


@contextlib.contextmanager
def prepare_codex_worker_home(master_agent_backend: "AgentBackend") -> Iterator["AgentBackend"]:
    from ralph.agent_backends import AgentBackend

    master_codex_home_path = master_agent_backend.agent_config_dir
    with tempfile.TemporaryDirectory(prefix="ralph-codex-home-") as worker_home_dir:
        worker_codex_home_path = Path(worker_home_dir).resolve()
        _copy_codex_worker_seed_files(
            master_codex_home_path=master_codex_home_path,
            worker_codex_home_path=worker_codex_home_path,
        )
        _copy_codex_worker_skills(
            master_codex_home_path=master_codex_home_path,
            worker_codex_home_path=worker_codex_home_path,
        )
        _create_codex_worker_runtime_dirs(worker_codex_home_path)
        read_only_home_mounts = _prepare_codex_worker_packages(
            master_codex_home_path=master_codex_home_path,
            worker_codex_home_path=worker_codex_home_path,
        )
        yield AgentBackend(
            backend_name=master_agent_backend.backend_name,
            command_name=master_agent_backend.command_name,
            agent_config_dir=worker_codex_home_path,
            agent_home_environment_variable=master_agent_backend.agent_home_environment_variable,
            read_only_home_mounts=read_only_home_mounts,
        )


def require_codex_home_path() -> Path:
    return require_agent_config_dir_from_environment_variable("CODEX_HOME")


def require_agent_config_dir_from_environment_variable(variable_name: str) -> Path:
    from ralph.sandbox import (
        build_sensitive_paths_that_workers_must_not_see,
        paths_overlap,
        paths_resolve_to_same_location,
    )

    configured_path = os.environ.get(variable_name)
    if not configured_path:
        raise RuntimeError(f"{variable_name} must be set before running Ralph agents.")

    agent_config_dir = Path(configured_path).expanduser().resolve()
    if not agent_config_dir.is_dir():
        raise RuntimeError(f"{variable_name} does not exist: {agent_config_dir}")
    _refuse_agent_config_dir_that_exposes_other_sensitive_state(
        agent_config_dir=agent_config_dir,
        variable_name=variable_name,
    )
    return agent_config_dir


def _refuse_agent_config_dir_that_exposes_other_sensitive_state(agent_config_dir: Path, variable_name: str) -> None:
    from ralph.sandbox import (
        build_sensitive_paths_that_workers_must_not_see,
        paths_overlap,
        paths_resolve_to_same_location,
    )

    for sensitive_path in build_sensitive_paths_that_workers_must_not_see():
        if paths_resolve_to_same_location(left_path=agent_config_dir, right_path=sensitive_path):
            continue
        if paths_overlap(left_path=agent_config_dir, right_path=sensitive_path):
            raise ValueError(
                f"{variable_name} must not overlap other worker-hidden sensitive state: "
                f"{agent_config_dir} overlaps {sensitive_path}"
            )


def _copy_codex_worker_seed_files(master_codex_home_path: Path, worker_codex_home_path: Path) -> None:
    for seed_filename in CODEX_WORKER_HOME_SEED_FILENAMES:
        master_seed_path = master_codex_home_path / seed_filename
        worker_seed_path = worker_codex_home_path / seed_filename
        if master_seed_path.is_file():
            shutil.copy2(master_seed_path, worker_seed_path)


def _copy_codex_worker_skills(master_codex_home_path: Path, worker_codex_home_path: Path) -> None:
    master_skills_path = master_codex_home_path / "skills"
    worker_skills_path = worker_codex_home_path / "skills"
    if master_skills_path.is_dir():
        shutil.copytree(master_skills_path, worker_skills_path, symlinks=False)


def _create_codex_worker_runtime_dirs(worker_codex_home_path: Path) -> None:
    (worker_codex_home_path / ".tmp").mkdir(parents=True, exist_ok=True)
    (worker_codex_home_path / "rules").mkdir(parents=True, exist_ok=True)


def _prepare_codex_worker_packages(
    master_codex_home_path: Path,
    worker_codex_home_path: Path,
) -> tuple["AgentHomeMount", ...]:
    from ralph.agent_backends import AgentHomeMount

    master_standalone_path = master_codex_home_path / "packages" / "standalone"
    worker_standalone_path = worker_codex_home_path / "packages" / "standalone"
    master_releases_path = master_standalone_path / "releases"
    worker_releases_path = worker_standalone_path / "releases"

    if not master_standalone_path.exists():
        return ()

    worker_standalone_path.mkdir(parents=True, exist_ok=True)
    _copy_codex_standalone_install_lock(
        master_standalone_path=master_standalone_path,
        worker_standalone_path=worker_standalone_path,
    )
    if not master_releases_path.is_dir():
        return ()

    _link_codex_worker_current_release(
        master_standalone_path=master_standalone_path,
        master_releases_path=master_releases_path,
        worker_standalone_path=worker_standalone_path,
        worker_releases_path=worker_releases_path,
    )
    return (
        AgentHomeMount(
            host_path=master_releases_path,
            worker_path=worker_releases_path,
        ),
    )


def _copy_codex_standalone_install_lock(master_standalone_path: Path, worker_standalone_path: Path) -> None:
    master_install_lock_path = master_standalone_path / "install.lock"
    worker_install_lock_path = worker_standalone_path / "install.lock"
    if master_install_lock_path.is_file():
        shutil.copy2(master_install_lock_path, worker_install_lock_path)


def _link_codex_worker_current_release(
    master_standalone_path: Path,
    master_releases_path: Path,
    worker_standalone_path: Path,
    worker_releases_path: Path,
) -> None:
    master_current_path = master_standalone_path / "current"
    if not master_current_path.exists():
        return

    master_current_release_path = master_current_path.resolve()
    if not master_current_release_path.is_relative_to(master_releases_path):
        return

    worker_current_release_path = worker_releases_path / master_current_release_path.relative_to(master_releases_path)
    worker_current_path = worker_standalone_path / "current"
    worker_current_path.symlink_to(worker_current_release_path)


@contextlib.contextmanager
def codex_permission_setup(
    agent_backend: "AgentBackend",
    allowed_bash_commands: list[str],
    task_path: Path,
) -> Iterator[None]:
    codex_home_path = agent_backend.agent_config_dir
    rules_path = codex_rules_path(codex_home_path)

    try:
        generated_rules = generate_codex_execpolicy_rules(allowed_bash_commands)
        write_codex_rules_atomically(rules_path, generated_rules)
        yield
    finally:
        rules_path.unlink(missing_ok=True)


def codex_rules_path(codex_home_path: Path) -> Path:
    return codex_home_path / "rules" / "default.rules"


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
