from __future__ import annotations

from pathlib import Path

import pytest

from ralph.agent_backends import AgentBackend
from ralph.codex_backend import (
    build_direct_codex_command,
    require_codex_home_path,
)


def test_build_direct_codex_command_keeps_git_writable_for_worker_commits(
    tmp_path: Path,
) -> None:
    codex_home_path = tmp_path / "codex-home"
    repo_path = tmp_path / "repo"
    tool_virtual_environment_path = tmp_path / "tool venv"
    controller_path = f"{tool_virtual_environment_path}/bin:/usr/bin:/bin"
    agent_backend = AgentBackend(
        backend_name="codex",
        command_name="/usr/bin/codex",
        agent_config_dir=codex_home_path,
        agent_home_environment_variable="CODEX_HOME",
    )

    assert build_direct_codex_command(
        agent_backend=agent_backend,
        repo_path=repo_path,
        tool_virtual_environment_path=tool_virtual_environment_path,
        controller_path=controller_path,
    ) == [
        "/usr/bin/codex",
        "--config",
        f'shell_environment_policy.set.PATH="{controller_path}"',
        "--config",
        (
            "shell_environment_policy.set.VIRTUAL_ENV="
            f'"{tool_virtual_environment_path}"'
        ),
        "--ask-for-approval",
        "never",
        "exec",
        "--json",
        "-C",
        str(repo_path),
        "--sandbox",
        "danger-full-access",
        "--ephemeral",
        "-",
    ]


def test_require_codex_home_path_rejects_missing_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("CODEX_HOME", raising=False)

    with pytest.raises(RuntimeError, match="CODEX_HOME must be set"):
        require_codex_home_path()


def test_require_codex_home_path_accepts_existing_codex_home(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    codex_home_path = tmp_path / ".codex"
    codex_home_path.mkdir()
    monkeypatch.setenv("CODEX_HOME", str(codex_home_path))

    assert require_codex_home_path() == codex_home_path


def test_require_codex_home_path_resolves_symlinked_codex_home(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    codex_home_path = tmp_path / ".codex"
    codex_home_link_path = tmp_path / "codex-link"
    codex_home_path.mkdir()
    codex_home_link_path.symlink_to(codex_home_path)
    monkeypatch.setenv("CODEX_HOME", str(codex_home_link_path))

    assert require_codex_home_path() == codex_home_path
