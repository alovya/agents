from __future__ import annotations

import os
import subprocess
import shlex
from pathlib import Path

import pytest

from ralph.agent_backends import AgentBackend, AgentHomeMount, select_agent_backend
from ralph.sandbox import (
    DEFAULT_RALPH_HOME_PATH,
    WORKER_AGENT_BINARY_PATH,
    WORKER_HOME_PATH,
    WORKER_TEMP_PATH,
    build_agent_visibility_smoke_test_prompt,
    build_bwrap_agent_command,
    reject_worker_visible_path_that_overlaps_hidden_state,
    resolve_python_venv_path,
    resolve_ralph_home_path,
    run_agent_visibility_smoke_test,
)
from ralph.tests.conftest import (
    build_test_agent_backend,
    command_windows,
    contains_subsequence,
    create_python_venv_shape,
    write_executable_shim,
)


def test_resolve_ralph_home_path_defaults_to_workspace(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("RALPH_HOME", raising=False)

    assert resolve_ralph_home_path() == DEFAULT_RALPH_HOME_PATH


def test_resolve_ralph_home_path_accepts_explicit_override(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ralph_home_path = tmp_path / "ralph-home"
    monkeypatch.setenv("RALPH_HOME", str(ralph_home_path))

    assert resolve_ralph_home_path() == ralph_home_path


def test_build_bwrap_command_mounts_python_venv_from_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bin_path = tmp_path / "bin"
    bwrap_path = bin_path / "bwrap"
    agent_path = bin_path / "agent-cli"
    codex_home_path = tmp_path / "codex-home"
    python_venv_path = tmp_path / "venv"
    bin_path.mkdir()
    codex_home_path.mkdir()
    codex_home_path.joinpath(".tmp").mkdir()
    python_venv_path.mkdir()
    write_executable_shim(bwrap_path)
    write_executable_shim(agent_path)
    monkeypatch.setenv("PATH", str(bin_path))
    monkeypatch.setenv("CODEX_HOME", str(codex_home_path))

    agent_backend = select_agent_backend(agent_backend_name="codex", agent_command="agent-cli")
    command = build_bwrap_agent_command(
        repo_path=tmp_path,
        agent_backend=agent_backend,
        python_venv_path=python_venv_path,
    )

    assert command[0] == str(bwrap_path)
    assert contains_subsequence(command, ["--ro-bind", str(agent_path), str(WORKER_AGENT_BINARY_PATH)])
    assert str(WORKER_AGENT_BINARY_PATH) in command
    assert contains_subsequence(command, ["--proc", "/proc"])
    assert contains_subsequence(command, ["--ro-bind", "/usr", "/usr"])
    for compatibility_path in [Path("/bin"), Path("/lib"), Path("/lib64"), Path("/sbin")]:
        if compatibility_path.is_symlink():
            assert contains_subsequence(command, ["--symlink", os.readlink(compatibility_path), str(compatibility_path)])
        else:
            assert contains_subsequence(command, ["--ro-bind", str(compatibility_path), str(compatibility_path)])
    assert contains_subsequence(command, ["--ro-bind", "/etc/hosts", "/etc/hosts"])
    assert contains_subsequence(
        command,
        ["--ro-bind", str(Path("/etc/resolv.conf").resolve()), "/etc/resolv.conf"],
    )
    assert contains_subsequence(command, ["--ro-bind", "/etc/nsswitch.conf", "/etc/nsswitch.conf"])
    assert contains_subsequence(command, ["--ro-bind", "/etc/os-release", "/etc/os-release"])
    assert contains_subsequence(command, ["--ro-bind", "/etc/ld.so.cache", "/etc/ld.so.cache"])
    assert contains_subsequence(
        command,
        ["--ro-bind", "/etc/ssl/certs/ca-certificates.crt", "/etc/ssl/certs/ca-certificates.crt"],
    )
    assert contains_subsequence(command, ["--bind", str(codex_home_path), str(codex_home_path)])
    assert contains_subsequence(command, ["--tmpfs", str(codex_home_path / ".tmp")])
    assert contains_subsequence(command, ["--ro-bind", str(python_venv_path), str(python_venv_path)])
    assert contains_subsequence(command, ["--setenv", "VIRTUAL_ENV", str(python_venv_path)])
    assert contains_subsequence(command, ["--setenv", "SSL_CERT_FILE", "/etc/ssl/certs/ca-certificates.crt"])
    assert str(python_venv_path / "bin") in command[command.index("PATH") + 1].split(":")[0]


def test_build_bwrap_command_adds_visible_allowed_command_dirs_to_worker_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bin_path = tmp_path / "bin"
    bwrap_path = bin_path / "bwrap"
    agent_path = bin_path / "agent-cli"
    codex_home_path = tmp_path / "codex-home"
    repo_path = tmp_path / "target-repo"
    rg_path = repo_path / "tools" / "rg"
    bin_path.mkdir()
    repo_path.mkdir()
    rg_path.parent.mkdir()
    codex_home_path.mkdir()
    write_executable_shim(bwrap_path)
    write_executable_shim(agent_path)
    write_executable_shim(rg_path)
    monkeypatch.setenv("PATH", os.pathsep.join([str(bin_path), str(rg_path.parent)]))
    monkeypatch.setenv("CODEX_HOME", str(codex_home_path))

    agent_backend = select_agent_backend(agent_backend_name="codex", agent_command="agent-cli")
    command = build_bwrap_agent_command(
        repo_path=repo_path,
        agent_backend=agent_backend,
        python_venv_path=None,
        allowed_bash_commands=["rg *"],
    )

    assert str(rg_path.parent) in command[command.index("PATH") + 1].split(":")


def test_build_bwrap_command_ignores_allowed_command_dirs_hidden_from_worker(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bin_path = tmp_path / "bin"
    bwrap_path = bin_path / "bwrap"
    agent_path = bin_path / "agent-cli"
    hidden_tool_path = tmp_path / "outside-repo" / "rg"
    codex_home_path = tmp_path / "codex-home"
    repo_path = tmp_path / "target-repo"
    bin_path.mkdir()
    repo_path.mkdir()
    hidden_tool_path.parent.mkdir()
    codex_home_path.mkdir()
    write_executable_shim(bwrap_path)
    write_executable_shim(agent_path)
    write_executable_shim(hidden_tool_path)
    monkeypatch.setenv("PATH", os.pathsep.join([str(bin_path), str(hidden_tool_path.parent)]))
    monkeypatch.setenv("CODEX_HOME", str(codex_home_path))

    agent_backend = select_agent_backend(agent_backend_name="codex", agent_command="agent-cli")
    command = build_bwrap_agent_command(
        repo_path=repo_path,
        agent_backend=agent_backend,
        python_venv_path=None,
        allowed_bash_commands=["rg *"],
    )

    assert str(hidden_tool_path.parent) not in command[command.index("PATH") + 1].split(":")


def test_build_bwrap_command_uses_allowlisted_worker_environment(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bin_path = tmp_path / "bin"
    bwrap_path = bin_path / "bwrap"
    agent_path = bin_path / "agent-cli"
    repo_path = tmp_path / "target-repo"
    codex_home_path = tmp_path / "codex-home"
    bin_path.mkdir()
    repo_path.mkdir()
    codex_home_path.mkdir()
    write_executable_shim(bwrap_path)
    write_executable_shim(agent_path)
    monkeypatch.setenv("PATH", str(bin_path))
    monkeypatch.setenv("CODEX_HOME", str(codex_home_path))
    monkeypatch.setenv("NOTION_API_KEY", "secret-notion-token")
    monkeypatch.setenv("OPENAI_API_KEY", "secret-openai-token")
    monkeypatch.setenv("SSH_AUTH_SOCK", "/tmp/ssh-agent.sock")

    agent_backend = select_agent_backend(agent_backend_name="codex", agent_command="agent-cli")
    command = build_bwrap_agent_command(
        repo_path=repo_path,
        agent_backend=agent_backend,
        python_venv_path=None,
    )

    assert ["--ro-bind", "/", "/"] not in command_windows(command, 3)
    assert contains_subsequence(command, ["--tmpfs", "/"])
    assert contains_subsequence(command, ["--bind", str(repo_path), str(repo_path)])
    assert contains_subsequence(command, ["--bind", str(codex_home_path), str(codex_home_path)])
    assert contains_subsequence(command, ["--ro-bind", str(agent_path), str(WORKER_AGENT_BINARY_PATH)])
    assert contains_subsequence(command, ["--clearenv"])
    assert contains_subsequence(command, ["--setenv", "HOME", str(WORKER_HOME_PATH)])
    assert contains_subsequence(command, ["--setenv", "TMPDIR", str(WORKER_TEMP_PATH)])
    assert contains_subsequence(command, ["--setenv", "CODEX_HOME", str(codex_home_path)])
    assert contains_subsequence(command, ["--setenv", "XDG_CONFIG_HOME", str(WORKER_HOME_PATH / ".config")])
    assert "--unsetenv" not in command
    assert str(Path.home() / ".notion-task-tracker") not in command
    assert "secret-notion-token" not in command
    assert "secret-openai-token" not in command
    assert str(Path.home() / ".local") not in command[command.index("PATH") + 1]
    assert "--ignore-user-config" not in command


def test_build_bwrap_command_mounts_read_only_worker_home_paths_after_writable_home(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bin_path = tmp_path / "bin"
    bwrap_path = bin_path / "bwrap"
    agent_path = bin_path / "agent-cli"
    master_codex_home_path = tmp_path / "master-codex-home"
    worker_codex_home_path = tmp_path / "worker-codex-home"
    master_package_releases_path = master_codex_home_path / "packages" / "standalone" / "releases"
    worker_package_releases_path = worker_codex_home_path / "packages" / "standalone" / "releases"
    repo_path = tmp_path / "target-repo"
    bin_path.mkdir()
    repo_path.mkdir()
    worker_codex_home_path.mkdir()
    master_package_releases_path.mkdir(parents=True)
    write_executable_shim(bwrap_path)
    write_executable_shim(agent_path)
    monkeypatch.setenv("PATH", str(bin_path))

    agent_backend = AgentBackend(
        backend_name="codex",
        command_name="agent-cli",
        agent_config_dir=worker_codex_home_path,
        agent_home_environment_variable="CODEX_HOME",
        read_only_home_mounts=(
            AgentHomeMount(
                host_path=master_package_releases_path,
                worker_path=worker_package_releases_path,
            ),
        ),
    )

    command = build_bwrap_agent_command(
        repo_path=repo_path,
        agent_backend=agent_backend,
        python_venv_path=None,
    )

    writable_home_bind_index = command.index(str(worker_codex_home_path))
    read_only_releases_mount_index = command.index(str(master_package_releases_path))
    assert writable_home_bind_index < read_only_releases_mount_index
    assert contains_subsequence(
        command,
        ["--bind", str(worker_codex_home_path), str(worker_codex_home_path)],
    )
    assert contains_subsequence(
        command,
        ["--ro-bind", str(master_package_releases_path), str(worker_package_releases_path)],
    )
    assert not contains_subsequence(
        command,
        ["--bind", str(master_codex_home_path), str(master_codex_home_path)],
    )
    assert not contains_subsequence(
        command,
        ["--ro-bind", str(master_codex_home_path), str(master_codex_home_path)],
    )
    assert "plugins" not in command
    assert "cache" not in command


def test_build_bwrap_command_uses_claude_worker_environment(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bin_path = tmp_path / "bin"
    bwrap_path = bin_path / "bwrap"
    claude_path = bin_path / "claude"
    repo_path = tmp_path / "target-repo"
    codex_home_path = tmp_path / "codex-home"
    claude_config_dir_path = tmp_path / "claude-config"
    bin_path.mkdir()
    repo_path.mkdir()
    codex_home_path.mkdir()
    claude_config_dir_path.mkdir()
    write_executable_shim(bwrap_path)
    write_executable_shim(claude_path)
    monkeypatch.setenv("PATH", str(bin_path))
    monkeypatch.setenv("CODEX_HOME", str(codex_home_path))
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(claude_config_dir_path))

    agent_backend = select_agent_backend(agent_backend_name="claude", agent_command=None)
    command = build_bwrap_agent_command(
        repo_path=repo_path,
        agent_backend=agent_backend,
        python_venv_path=None,
    )

    assert contains_subsequence(command, ["--bind", str(claude_config_dir_path), str(claude_config_dir_path)])
    assert contains_subsequence(command, ["--setenv", "CLAUDE_CONFIG_DIR", str(claude_config_dir_path)])
    assert not contains_subsequence(command, ["--bind", str(codex_home_path), str(codex_home_path)])
    assert "CODEX_HOME" not in command


def test_build_bwrap_agent_command_mounts_codex_binary(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bin_path = tmp_path / "bin"
    bwrap_path = bin_path / "bwrap"
    codex_path = bin_path / "codex"
    repo_path = tmp_path / "target-repo"
    codex_home_path = tmp_path / "codex-home"
    bin_path.mkdir()
    repo_path.mkdir()
    codex_home_path.mkdir()
    write_executable_shim(bwrap_path)
    write_executable_shim(codex_path)
    monkeypatch.setenv("PATH", str(bin_path))
    monkeypatch.setenv("CODEX_HOME", str(codex_home_path))

    agent_backend = select_agent_backend(agent_backend_name="codex", agent_command=None)
    command = build_bwrap_agent_command(
        repo_path=repo_path,
        agent_backend=agent_backend,
        python_venv_path=None,
    )

    assert contains_subsequence(command, ["--ro-bind", str(codex_path), str(WORKER_AGENT_BINARY_PATH)])


def test_build_bwrap_agent_command_uses_claude_command_tail(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bin_path = tmp_path / "bin"
    bwrap_path = bin_path / "bwrap"
    claude_path = bin_path / "claude"
    repo_path = tmp_path / "target-repo"
    claude_config_dir_path = tmp_path / "claude-config"
    bin_path.mkdir()
    repo_path.mkdir()
    claude_config_dir_path.mkdir()
    write_executable_shim(bwrap_path)
    write_executable_shim(claude_path)
    monkeypatch.setenv("PATH", str(bin_path))
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(claude_config_dir_path))

    agent_backend = select_agent_backend(agent_backend_name="claude", agent_command=None)
    command = build_bwrap_agent_command(
        repo_path=repo_path,
        agent_backend=agent_backend,
        python_venv_path=None,
        allowed_bash_commands=[
            "python -m pytest ralph/tests/test_run_ralph_loop.py",
            "git add .",
            "git commit --no-verify -m *",
            "git rev-parse HEAD",
        ],
    )

    assert contains_subsequence(command, ["--ro-bind", str(claude_path), str(WORKER_AGENT_BINARY_PATH)])
    claude_index = len(command) - 1 - list(reversed(command)).index(str(WORKER_AGENT_BINARY_PATH))
    assert command[claude_index:] == [
        str(WORKER_AGENT_BINARY_PATH),
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
        "Read",
        "Glob",
        "Grep",
        "Edit",
        "MultiEdit",
        "Write",
        "Bash(python -m pytest ralph/tests/test_run_ralph_loop.py)",
        "Bash(git add .)",
        "Bash(git commit --no-verify -m *)",
        "Bash(git rev-parse HEAD)",
        "--no-session-persistence",
    ]
    assert "bypassPermissions" not in command
    assert "--dangerously-skip-permissions" not in command


def test_build_bwrap_agent_command_keeps_codex_command_tail_with_ask_for_approval_untrusted(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bin_path = tmp_path / "bin"
    bwrap_path = bin_path / "bwrap"
    codex_path = bin_path / "codex"
    repo_path = tmp_path / "target-repo"
    codex_home_path = tmp_path / "codex-home"
    bin_path.mkdir()
    repo_path.mkdir()
    codex_home_path.mkdir()
    write_executable_shim(bwrap_path)
    write_executable_shim(codex_path)
    monkeypatch.setenv("PATH", str(bin_path))
    monkeypatch.setenv("CODEX_HOME", str(codex_home_path))

    agent_backend = select_agent_backend(agent_backend_name="codex", agent_command=None)
    command = build_bwrap_agent_command(
        repo_path=repo_path,
        agent_backend=agent_backend,
        python_venv_path=None,
    )

    codex_index = len(command) - 1 - list(reversed(command)).index(str(WORKER_AGENT_BINARY_PATH))
    assert command[codex_index:] == [
        str(WORKER_AGENT_BINARY_PATH),
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
    assert "--ignore-rules" not in command


def test_build_agent_visibility_smoke_test_prompt_checks_sandbox_contract(tmp_path: Path) -> None:
    repo_path = tmp_path / "target repo"
    agent_config_dir = tmp_path / "codex home"
    python_venv_path = tmp_path / "tool venv"

    prompt = build_agent_visibility_smoke_test_prompt(
        repo_path=repo_path,
        agent_backend=build_test_agent_backend(
            backend_name="codex",
            agent_config_dir=agent_config_dir,
            agent_home_environment_variable="CODEX_HOME",
        ),
        python_venv_path=python_venv_path,
    )

    assert "RALPH_SANDBOX_OK" in prompt
    assert f"test ! -e {shlex.quote(str(Path.home() / '.ralph'))}" in prompt
    assert f"test ! -e {shlex.quote(str(Path.home() / '.notion-task-tracker'))}" in prompt
    assert f"test ! -e {shlex.quote(str(Path.home() / '.aws'))}" in prompt
    assert f"test ! -e {shlex.quote(str(Path.home() / '.claude'))}" in prompt
    assert "test ! -e /workspace/.ralph" in prompt
    assert "test ! -e /workspace/.codex" in prompt
    assert "test ! -e /workspace/.aws" in prompt
    assert "test ! -e /workspace/.claude" in prompt
    assert "test ! -e /workspace/.docker" in prompt
    assert "test ! -e /workspace/.kube" in prompt
    assert 'test -z "${NOTION_API_KEY:-}"' in prompt
    assert 'test -z "${OPENAI_API_KEY:-}"' in prompt
    assert 'test "${CODEX_HOME-}" =' in prompt
    assert str(agent_config_dir) in prompt
    assert 'test -z "${CLAUDE_CONFIG_DIR:-}"' in prompt
    assert "mkdir" in prompt
    assert "rmdir" in prompt
    assert str(repo_path / ".ralph-sandbox-write-test-dir") in prompt
    assert "test -d" in prompt
    assert "/proc/self/mountinfo" in prompt
    assert "ralph_found_read_only_mount" in prompt
    assert 'test "$VIRTUAL_ENV" =' in prompt
    assert str(python_venv_path) in prompt
    assert "BASH_ENV" not in prompt


def test_build_agent_visibility_smoke_test_prompt_skips_venv_checks_when_absent(tmp_path: Path) -> None:
    prompt = build_agent_visibility_smoke_test_prompt(
        repo_path=tmp_path / "target-repo",
        agent_backend=build_test_agent_backend(
            backend_name="codex",
            agent_config_dir=tmp_path / "codex-home",
            agent_home_environment_variable="CODEX_HOME",
        ),
        python_venv_path=None,
    )

    assert "VIRTUAL_ENV" not in prompt
    assert "printf blocked" not in prompt


def test_build_agent_visibility_smoke_test_prompt_does_not_reject_explicit_mounts(tmp_path: Path) -> None:
    prompt = build_agent_visibility_smoke_test_prompt(
        repo_path=tmp_path / "target-repo",
        agent_backend=build_test_agent_backend(
            backend_name="codex",
            agent_config_dir=Path("/workspace/.codex"),
            agent_home_environment_variable="CODEX_HOME",
        ),
        python_venv_path=None,
    )

    assert "test ! -e /workspace/.codex" not in prompt
    assert f'test "${{CODEX_HOME-}}" = {shlex.quote("/workspace/.codex")}' in prompt


def test_build_agent_visibility_smoke_test_prompt_hides_unselected_backend_state(tmp_path: Path) -> None:
    prompt = build_agent_visibility_smoke_test_prompt(
        repo_path=tmp_path / "target-repo",
        agent_backend=build_test_agent_backend(
            backend_name="claude",
            agent_config_dir=Path("/workspace/.claude"),
            agent_home_environment_variable="CLAUDE_CONFIG_DIR",
        ),
        python_venv_path=None,
    )

    assert "test ! -e /workspace/.claude" not in prompt
    assert "test ! -e /workspace/.codex" in prompt
    assert f'test "${{CLAUDE_CONFIG_DIR-}}" = {shlex.quote("/workspace/.claude")}' in prompt
    assert 'test -z "${CODEX_HOME:-}"' in prompt


def test_run_agent_visibility_smoke_test_rejects_missing_repo(tmp_path: Path) -> None:
    missing_repo_path = tmp_path / "missing-repo"

    with pytest.raises(FileNotFoundError, match="Target repo does not exist"):
        run_agent_visibility_smoke_test(
            repo_path=missing_repo_path,
            agent_backend_name="codex",
            agent_command="agent-cli",
            python_venv_path=None,
        )


def test_run_agent_visibility_smoke_test_rejects_sensitive_repo_mount(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo_path = tmp_path / "workspace"
    sensitive_state_path = repo_path / ".aws"
    sensitive_state_path.mkdir(parents=True)
    monkeypatch.setattr(
        "ralph.sandbox.build_sensitive_paths_that_workers_must_not_see",
        lambda: [sensitive_state_path],
    )

    with pytest.raises(ValueError, match="Target repo must not overlap"):
        run_agent_visibility_smoke_test(
            repo_path=repo_path,
            agent_backend_name="codex",
            agent_command="agent-cli",
            python_venv_path=None,
        )


def test_run_agent_visibility_smoke_test_uses_prepared_codex_worker_home(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    master_codex_home_path = tmp_path / "master-codex-home"
    repo_path = tmp_path / "target-repo"
    master_codex_home_path.mkdir()
    repo_path.mkdir()
    monkeypatch.setenv("CODEX_HOME", str(master_codex_home_path))
    monkeypatch.setattr(
        "ralph.sandbox.build_sensitive_paths_that_workers_must_not_see",
        lambda: [master_codex_home_path],
    )

    observed_worker_agent_backend: dict[str, AgentBackend] = {}
    observed_prompt: list[str] = []

    def build_bwrap_agent_command_mock(
        repo_path: Path,
        agent_backend: AgentBackend,
        python_venv_path: Path | None,
        allowed_bash_commands: list[str] | None = None,
    ) -> list[str]:
        observed_worker_agent_backend["bwrap"] = agent_backend
        return ["fake-bwrap-command"]

    def subprocess_run_mock(
        command: list[str],
        input: str,
        text: bool,
        stdout: int,
        stderr: int,
        check: bool,
    ) -> subprocess.CompletedProcess[str]:
        observed_prompt.append(input)
        return subprocess.CompletedProcess(
            args=command,
            returncode=0,
            stdout="RALPH_SANDBOX_OK\n",
        )

    monkeypatch.setattr(
        "ralph.sandbox.build_bwrap_agent_command",
        build_bwrap_agent_command_mock,
    )
    monkeypatch.setattr("ralph.sandbox.subprocess.run", subprocess_run_mock)

    run_agent_visibility_smoke_test(
        repo_path=repo_path,
        agent_backend_name="codex",
        agent_command="codex",
        python_venv_path=None,
    )

    worker_codex_home_path = observed_worker_agent_backend["bwrap"].agent_config_dir
    assert worker_codex_home_path != master_codex_home_path
    assert f"test ! -e {shlex.quote(str(master_codex_home_path))}" in observed_prompt[0]
    assert (
        f'test "${{CODEX_HOME-}}" = {shlex.quote(str(worker_codex_home_path))}'
        in observed_prompt[0]
    )
    assert not worker_codex_home_path.exists()


def test_worker_visible_path_check_rejects_hidden_state_overlap_but_accepts_normal_repo_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    normal_repo_path = tmp_path / "target-repo"
    hidden_state_path = tmp_path / "hidden-state"
    normal_repo_path.mkdir()
    hidden_state_path.mkdir()
    monkeypatch.setattr(
        "ralph.sandbox.build_sensitive_paths_that_workers_must_not_see",
        lambda: [hidden_state_path],
    )

    reject_worker_visible_path_that_overlaps_hidden_state(
        path=normal_repo_path,
        role="Target repo",
    )

    with pytest.raises(ValueError, match="Target repo must not overlap"):
        reject_worker_visible_path_that_overlaps_hidden_state(
            path=hidden_state_path,
            role="Target repo",
        )


def test_resolve_python_venv_path_rejects_sensitive_path_overlap(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sensitive_state_path = tmp_path / "sensitive-state"
    python_venv_path = sensitive_state_path / "tool-venv"
    create_python_venv_shape(python_venv_path)
    monkeypatch.setattr(
        "ralph.sandbox.build_sensitive_paths_that_workers_must_not_see",
        lambda: [sensitive_state_path],
    )

    with pytest.raises(ValueError, match="Python venv must not overlap"):
        resolve_python_venv_path(str(python_venv_path))


def test_resolve_python_venv_path_accepts_non_sensitive_helper_venv(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    python_venv_path = tmp_path / "tool-venv"
    create_python_venv_shape(python_venv_path)
    monkeypatch.setattr(
        "ralph.sandbox.build_sensitive_paths_that_workers_must_not_see",
        lambda: [tmp_path / "sensitive-state"],
    )

    assert resolve_python_venv_path(str(python_venv_path)) == python_venv_path
