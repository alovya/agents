from __future__ import annotations

import json
import os
import shlex
import subprocess
from pathlib import Path

import pytest
import yaml

from ralph.run_ralph_loop import (
    AgentBackend,
    AgentResult,
    CODEX_RULES_BACKUP_FILENAME,
    CodexRulesSnapshot,
    DEFAULT_NOTION_TRACKER_STATE_PATH,
    DEFAULT_RALPH_HOME_PATH,
    RalphJob,
    TaskSelection,
    WORKER_AGENT_BINARY_PATH,
    WORKER_HOME_PATH,
    WORKER_TEMP_PATH,
    _accept_worker_completed_task,
    _backend_permission_setup,
    _build_agent_visibility_smoke_test_prompt,
    _build_bwrap_agent_command,
    _build_notion_task_creation_command,
    _build_worker_allowed_bash_commands,
    _codex_permission_setup,
    _codex_rules_path,
    _create_task_directory,
    _extract_created_notion_task_id,
    _extract_claude_stream_result_text,
    _find_ralph_job,
    _find_interrupted_codex_rules_backup,
    _generate_codex_execpolicy_rules,
    _log_completed_worker_to_notion,
    _log_failed_verification_to_notion,
    _log_slice_start_to_notion,
    _log_worker_promise_to_notion,
    main,
    _materialise_planned_notion_task_before_worker_launch,
    _mark_task_done,
    _parse_command_to_execpolicy_pattern,
    _prepare_notion_task_before_worker_runs_task,
    _parse_arguments,
    _parse_agent_promise,
    _read_codex_rules_backup,
    _read_tasks_from_ledger,
    _recover_interrupted_codex_rules,
    _reject_worker_visible_path_that_overlaps_hidden_state,
    _refuse_unsafe_starting_state,
    _render_agent_prompt,
    _resolve_ralph_home_path,
    _resolve_python_venv_path,
    _require_codex_home_path,
    _restore_codex_rules,
    _run_agent_visibility_smoke_test,
    _run_command_and_tee_output,
    _select_next_task_from_plan_and_ledger,
    _select_agent_backend_config,
    _snapshot_codex_rules,
    _write_codex_rules_atomically,
    _write_codex_rules_backup,
    _write_yaml_file,
)


def test_direct_script_help_remains_runnable_from_repo_root() -> None:
    repo_path = Path(__file__).resolve().parents[2]

    completed_process = subprocess.run(
        ["/workspace/venv/bin/python", "ralph/run_ralph_loop.py", "--help"],
        cwd=repo_path,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )

    assert completed_process.returncode == 0
    assert "Run Ralph task loops with sliced plan context." in completed_process.stdout
    assert "run" in completed_process.stdout
    assert "smoke-test" in completed_process.stdout


def test_package_invocation_help_remains_runnable() -> None:
    repo_path = Path(__file__).resolve().parents[2]

    completed_process = subprocess.run(
        ["/workspace/venv/bin/python", "-m", "ralph.run_ralph_loop", "--help"],
        cwd=repo_path,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )

    assert completed_process.returncode == 0
    assert "Run Ralph task loops with sliced plan context." in completed_process.stdout
    assert "run" in completed_process.stdout
    assert "smoke-test" in completed_process.stdout


def test_extracts_only_active_plan_slice() -> None:
    ledger = _build_example_ledger()
    plan_text = _build_example_plan()

    selection = _select_next_task_from_plan_and_ledger(ledger, plan_text)

    assert selection.task["id"] == "R1"
    assert "First task context." in selection.active_task_plan_context
    assert "Second task context." not in selection.active_task_plan_context
    assert selection.task["allowed_bash_commands"] == ["rg *", "sed -n *"]
    assert selection.task["verification_commands"] == ["test -f src/parser.py"]


def test_rejects_missing_plan_slice() -> None:
    plan_text = """
<!-- ralph-shared:start -->
Shared context.
<!-- ralph-shared:end -->
"""

    with pytest.raises(ValueError, match="missing Ralph task blocks"):
        _select_next_task_from_plan_and_ledger(_build_example_ledger(), plan_text)


def test_rejects_task_plan_without_allowed_bash_block() -> None:
    plan_text = """
<!-- ralph-shared:start -->
Shared context.
<!-- ralph-shared:end -->

<!-- ralph-task:start R1 -->
First task context.

<!-- ralph-verification:start -->
- test -f src/parser.py
<!-- ralph-verification:end -->
<!-- ralph-task:end R1 -->

<!-- ralph-task:start R2 -->
Second task context.

<!-- ralph-allowed-bash:start -->
- rg *
<!-- ralph-allowed-bash:end -->

<!-- ralph-verification:start -->
- python -m pytest tests/test_cli.py
<!-- ralph-verification:end -->
<!-- ralph-task:end R2 -->
"""

    with pytest.raises(ValueError, match="exactly one ralph-allowed-bash block"):
        _select_next_task_from_plan_and_ledger(_build_example_ledger(), plan_text)


def test_rejects_task_plan_without_verification_block() -> None:
    plan_text = """
<!-- ralph-shared:start -->
Shared context.
<!-- ralph-shared:end -->

<!-- ralph-task:start R1 -->
First task context.

<!-- ralph-allowed-bash:start -->
- rg *
<!-- ralph-allowed-bash:end -->
<!-- ralph-task:end R1 -->

<!-- ralph-task:start R2 -->
Second task context.

<!-- ralph-allowed-bash:start -->
- rg *
<!-- ralph-allowed-bash:end -->

<!-- ralph-verification:start -->
- python -m pytest tests/test_cli.py
<!-- ralph-verification:end -->
<!-- ralph-task:end R2 -->
"""

    with pytest.raises(ValueError, match="exactly one ralph-verification block"):
        _select_next_task_from_plan_and_ledger(_build_example_ledger(), plan_text)


def test_selects_dependency_ready_task() -> None:
    ledger = _build_example_ledger()
    ledger["tasks"][0]["status"] = "done"

    selection = _select_next_task_from_plan_and_ledger(ledger, _build_example_plan())

    assert selection.task["id"] == "R2"
    assert selection.task["verification_commands"] == ["python -m pytest tests/test_cli.py"]


def test_selects_first_pending_task_after_skipping_pending_task_with_unfinished_dependencies() -> None:
    ledger = _build_ledger_where_first_pending_task_waits_and_second_pending_task_is_ready()

    selection = _select_next_task_from_plan_and_ledger(ledger, _build_three_task_plan())

    assert selection.task["id"] == "R2"
    assert selection.active_task_plan_context.strip().startswith("Second task context.")


def test_parses_exactly_one_promise() -> None:
    assert _parse_agent_promise("done\n<promise>DONE</promise>") == "DONE"
    assert _parse_agent_promise(
        "\n".join(
            [
                "<promise>DONE</promise>",
                "<promise>BLOCKED</promise>",
                "<promise>ABORT</promise>",
                "final answer",
                "<promise>DONE</promise>",
            ]
        )
    ) == "DONE"
    with pytest.raises(RuntimeError, match="Expected one final"):
        _parse_agent_promise("No promise here.")


def test_parse_args_streams_agent_output_by_default() -> None:
    arguments = _parse_arguments([
        "run",
        "--repo-path",
        "/tmp/repo",
        "--job-name",
        "example",
    ])

    assert arguments.tee_agent_output is True


def test_parse_args_can_disable_agent_output_teeing() -> None:
    arguments = _parse_arguments([
        "run",
        "--repo-path",
        "/tmp/repo",
        "--job-name",
        "example",
        "--no-tee-agent-output",
    ])

    assert arguments.tee_agent_output is False


def test_parse_args_accepts_python_venv() -> None:
    arguments = _parse_arguments([
        "run",
        "--repo-path",
        "/tmp/repo",
        "--job-name",
        "example",
        "--python-venv",
        "/tmp/tooling-venv",
    ])

    assert arguments.python_venv == "/tmp/tooling-venv"


def test_parse_args_defaults_to_codex_backend_without_eager_command_resolution(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("RALPH_AGENT_COMMAND", "custom-agent")
    monkeypatch.setenv("RALPH_CODEX_COMMAND", "custom-codex")

    arguments = _parse_arguments([
        "run",
        "--repo-path",
        "/tmp/repo",
        "--job-name",
        "example",
    ])

    assert arguments.agent_backend == "codex"
    assert arguments.agent_command is None


def test_parse_args_accepts_agent_backend_for_run_and_smoke_test() -> None:
    run_arguments = _parse_arguments([
        "run",
        "--repo-path",
        "/tmp/repo",
        "--job-name",
        "example",
        "--agent-backend",
        "claude",
    ])
    smoke_arguments = _parse_arguments([
        "smoke-test",
        "--repo-path",
        "/tmp/repo",
        "--agent-backend",
        "claude",
    ])

    assert run_arguments.agent_backend == "claude"
    assert smoke_arguments.agent_backend == "claude"


def test_codex_backend_uses_ralph_agent_command_before_codex_specific_default(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    codex_home_path = tmp_path / "codex-home"
    codex_home_path.mkdir()
    monkeypatch.setenv("CODEX_HOME", str(codex_home_path))
    monkeypatch.setenv("RALPH_AGENT_COMMAND", "custom-agent")
    monkeypatch.setenv("RALPH_CODEX_COMMAND", "custom-codex")

    backend_config = _select_agent_backend_config(agent_backend="codex", agent_command=None)

    assert backend_config.command_name == "custom-agent"


def test_codex_backend_uses_codex_specific_default_before_binary_name(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    codex_home_path = tmp_path / "codex-home"
    codex_home_path.mkdir()
    monkeypatch.setenv("CODEX_HOME", str(codex_home_path))
    monkeypatch.delenv("RALPH_AGENT_COMMAND", raising=False)
    monkeypatch.setenv("RALPH_CODEX_COMMAND", "custom-codex")

    backend_config = _select_agent_backend_config(agent_backend="codex", agent_command=None)

    assert backend_config.command_name == "custom-codex"


def test_agent_command_override_wins_after_backend_selection(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    codex_home_path = tmp_path / "codex-home"
    codex_home_path.mkdir()
    monkeypatch.setenv("CODEX_HOME", str(codex_home_path))
    monkeypatch.setenv("RALPH_AGENT_COMMAND", "custom-agent")
    monkeypatch.setenv("RALPH_CODEX_COMMAND", "custom-codex")

    backend_config = _select_agent_backend_config(agent_backend="codex", agent_command="override-agent")

    assert backend_config.command_name == "override-agent"


def test_codex_backend_falls_back_to_codex_binary_name(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    codex_home_path = tmp_path / "codex-home"
    codex_home_path.mkdir()
    monkeypatch.setenv("CODEX_HOME", str(codex_home_path))
    monkeypatch.delenv("RALPH_AGENT_COMMAND", raising=False)
    monkeypatch.delenv("RALPH_CODEX_COMMAND", raising=False)

    backend_config = _select_agent_backend_config(agent_backend="codex", agent_command=None)

    assert backend_config.command_name == "codex"


def test_claude_backend_uses_ralph_agent_command_before_claude_specific_default(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    claude_config_dir_path = tmp_path / "claude-config"
    claude_config_dir_path.mkdir()
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(claude_config_dir_path))
    monkeypatch.setenv("RALPH_AGENT_COMMAND", "custom-agent")
    monkeypatch.setenv("RALPH_CLAUDE_COMMAND", "custom-claude")

    backend_config = _select_agent_backend_config(agent_backend="claude", agent_command=None)

    assert backend_config.command_name == "custom-agent"


def test_claude_backend_uses_claude_specific_default_before_binary_name(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    claude_config_dir_path = tmp_path / "claude-config"
    claude_config_dir_path.mkdir()
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(claude_config_dir_path))
    monkeypatch.delenv("RALPH_AGENT_COMMAND", raising=False)
    monkeypatch.setenv("RALPH_CLAUDE_COMMAND", "custom-claude")

    backend_config = _select_agent_backend_config(agent_backend="claude", agent_command=None)

    assert backend_config.command_name == "custom-claude"


def test_claude_backend_falls_back_to_claude_binary_name(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    claude_config_dir_path = tmp_path / "claude-config"
    claude_config_dir_path.mkdir()
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(claude_config_dir_path))
    monkeypatch.delenv("RALPH_AGENT_COMMAND", raising=False)
    monkeypatch.delenv("RALPH_CLAUDE_COMMAND", raising=False)

    backend_config = _select_agent_backend_config(agent_backend="claude", agent_command=None)

    assert backend_config.command_name == "claude"


def test_resolve_ralph_home_path_defaults_to_workspace(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("RALPH_HOME", raising=False)

    assert _resolve_ralph_home_path() == DEFAULT_RALPH_HOME_PATH


def test_resolve_ralph_home_path_accepts_explicit_override(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ralph_home_path = tmp_path / "ralph-home"
    monkeypatch.setenv("RALPH_HOME", str(ralph_home_path))

    assert _resolve_ralph_home_path() == ralph_home_path


def test_find_ralph_job_uses_workspace_home_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("RALPH_HOME", raising=False)

    job = _find_ralph_job("example")

    assert job.job_path == Path("/workspace/.ralph/jobs/example")
    assert job.plan_path == Path("/workspace/.ralph/jobs/example/PLAN.md")


def test_find_ralph_job_uses_explicit_ralph_home(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ralph_home_path = tmp_path / "ralph-home"
    monkeypatch.setenv("RALPH_HOME", str(ralph_home_path))

    job = _find_ralph_job("example")

    assert job.job_path == ralph_home_path / "jobs" / "example"


def test_smoke_test_resolves_repo_path_before_running_sandbox_check(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo_path = tmp_path / "target-repo"
    repo_path.mkdir()
    observed_repo_paths: list[Path] = []

    def run_agent_visibility_smoke_test_mock(
        repo_path: Path,
        agent_backend: str,
        agent_command: str | None,
        python_venv_path: Path | None,
    ) -> None:
        observed_repo_paths.append(repo_path)

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        "ralph.run_ralph_loop._run_agent_visibility_smoke_test",
        run_agent_visibility_smoke_test_mock,
    )

    main([
        "smoke-test",
        "--repo-path",
        "target-repo",
        "--agent-command",
        "agent-cli",
    ])

    assert observed_repo_paths == [repo_path]


def test_run_command_and_tee_output_writes_to_terminal_and_file(
    tmp_path: Path,
    capsys,
) -> None:
    output_path = tmp_path / "agent-output.txt"

    completed_process = _run_command_and_tee_output(
        command=["bash", "-lc", "printf 'before\\n'; cat; printf 'after\\n'"],
        input_text="middle\n",
        output_path=output_path,
    )

    assert completed_process.returncode == 0
    assert completed_process.stdout == "before\nmiddle\nafter\n"
    assert output_path.read_text(encoding="utf-8") == "before\nmiddle\nafter\n"
    assert capsys.readouterr().out == "before\nmiddle\nafter\n"


def test_create_task_directory_prefixes_task_id(tmp_path: Path) -> None:
    task_path = _create_task_directory(tmp_path, "R1")

    assert task_path.name.startswith("R1_")
    assert task_path.is_dir()


def test_create_task_directory_sanitizes_task_id(tmp_path: Path) -> None:
    task_path = _create_task_directory(tmp_path, "R 1/cleanup")

    assert task_path.name.startswith("R-1-cleanup_")
    assert task_path.is_dir()


def test_render_agent_prompt_excludes_unrelated_task_slice(tmp_path: Path) -> None:
    ledger = _build_example_ledger()
    selection = TaskSelection(
        task=ledger["tasks"][0],
        shared_plan_context="Shared context.",
        active_task_plan_context="First task context.",
    )

    prompt = _render_agent_prompt(
        repo_path=tmp_path,
        ledger=ledger,
        selection=selection,
        python_venv_path=None,
    )

    assert "First task context." in prompt
    assert "Second task context." not in prompt
    assert "/.ralph" not in prompt
    assert "Codex" not in prompt


def test_render_agent_prompt_keeps_plan_instructions_without_duplicating_ledger_prose(tmp_path: Path) -> None:
    ledger = _build_example_ledger()
    ledger["tasks"][0]["context"] = "Duplicated task prose from ledger YAML."
    selection = TaskSelection(
        task=ledger["tasks"][0],
        shared_plan_context="Shared context.",
        active_task_plan_context="Task instructions kept from PLAN.md.",
    )

    prompt = _render_agent_prompt(
        repo_path=tmp_path,
        ledger=ledger,
        selection=selection,
        python_venv_path=None,
    )

    assert "Task instructions kept from PLAN.md." in prompt
    assert "Duplicated task prose from ledger YAML." not in prompt


def test_render_agent_prompt_documents_python_venv(tmp_path: Path) -> None:
    ledger = _build_example_ledger()
    selection = TaskSelection(
        task=ledger["tasks"][0],
        shared_plan_context="Shared context.",
        active_task_plan_context="First task context.",
    )
    python_venv_path = tmp_path / "venv"

    prompt = _render_agent_prompt(
        repo_path=tmp_path,
        ledger=ledger,
        selection=selection,
        python_venv_path=python_venv_path,
    )

    assert f"Python venv: {python_venv_path}" in prompt
    assert "already first on PATH" in prompt
    assert "ntt" not in prompt
    assert "Notion" not in prompt


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
    _write_executable_shim(bwrap_path)
    _write_executable_shim(agent_path)
    monkeypatch.setenv("PATH", str(bin_path))
    monkeypatch.setenv("CODEX_HOME", str(codex_home_path))

    backend_config = _select_agent_backend_config(agent_backend="codex", agent_command="agent-cli")
    command = _build_bwrap_agent_command(
        repo_path=tmp_path,
        backend_config=backend_config,
        python_venv_path=python_venv_path,
    )

    assert command[0] == str(bwrap_path)
    assert _contains_subsequence(command, ["--ro-bind", str(agent_path), str(WORKER_AGENT_BINARY_PATH)])
    assert str(WORKER_AGENT_BINARY_PATH) in command
    assert _contains_subsequence(command, ["--proc", "/proc"])
    assert _contains_subsequence(command, ["--ro-bind", "/usr", "/usr"])
    for compatibility_path in [Path("/bin"), Path("/lib"), Path("/lib64"), Path("/sbin")]:
        if compatibility_path.is_symlink():
            assert _contains_subsequence(command, ["--symlink", os.readlink(compatibility_path), str(compatibility_path)])
        else:
            assert _contains_subsequence(command, ["--ro-bind", str(compatibility_path), str(compatibility_path)])
    assert _contains_subsequence(command, ["--ro-bind", "/etc/hosts", "/etc/hosts"])
    assert _contains_subsequence(
        command,
        ["--ro-bind", str(Path("/etc/resolv.conf").resolve()), "/etc/resolv.conf"],
    )
    assert _contains_subsequence(command, ["--ro-bind", "/etc/nsswitch.conf", "/etc/nsswitch.conf"])
    assert _contains_subsequence(command, ["--ro-bind", "/etc/ld.so.cache", "/etc/ld.so.cache"])
    assert _contains_subsequence(
        command,
        ["--ro-bind", "/etc/ssl/certs/ca-certificates.crt", "/etc/ssl/certs/ca-certificates.crt"],
    )
    assert _contains_subsequence(command, ["--bind", str(codex_home_path), str(codex_home_path)])
    assert _contains_subsequence(command, ["--tmpfs", str(codex_home_path / ".tmp")])
    assert _contains_subsequence(command, ["--ro-bind", str(python_venv_path), str(python_venv_path)])
    assert _contains_subsequence(command, ["--setenv", "VIRTUAL_ENV", str(python_venv_path)])
    assert _contains_subsequence(command, ["--setenv", "SSL_CERT_FILE", "/etc/ssl/certs/ca-certificates.crt"])
    assert str(python_venv_path / "bin") in command[command.index("PATH") + 1].split(":")[0]


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
    _write_executable_shim(bwrap_path)
    _write_executable_shim(agent_path)
    monkeypatch.setenv("PATH", str(bin_path))
    monkeypatch.setenv("CODEX_HOME", str(codex_home_path))
    monkeypatch.setenv("NOTION_API_KEY", "secret-notion-token")
    monkeypatch.setenv("OPENAI_API_KEY", "secret-openai-token")
    monkeypatch.setenv("SSH_AUTH_SOCK", "/tmp/ssh-agent.sock")

    backend_config = _select_agent_backend_config(agent_backend="codex", agent_command="agent-cli")
    command = _build_bwrap_agent_command(
        repo_path=repo_path,
        backend_config=backend_config,
        python_venv_path=None,
    )

    assert ["--ro-bind", "/", "/"] not in _command_windows(command, 3)
    assert _contains_subsequence(command, ["--tmpfs", "/"])
    assert _contains_subsequence(command, ["--bind", str(repo_path), str(repo_path)])
    assert _contains_subsequence(command, ["--bind", str(codex_home_path), str(codex_home_path)])
    assert _contains_subsequence(command, ["--ro-bind", str(agent_path), str(WORKER_AGENT_BINARY_PATH)])
    assert _contains_subsequence(command, ["--clearenv"])
    assert _contains_subsequence(command, ["--setenv", "HOME", str(WORKER_HOME_PATH)])
    assert _contains_subsequence(command, ["--setenv", "TMPDIR", str(WORKER_TEMP_PATH)])
    assert _contains_subsequence(command, ["--setenv", "CODEX_HOME", str(codex_home_path)])
    assert _contains_subsequence(command, ["--setenv", "XDG_CONFIG_HOME", str(WORKER_HOME_PATH / ".config")])
    assert "--unsetenv" not in command
    assert str(Path.home() / ".notion-task-tracker") not in command
    assert "secret-notion-token" not in command
    assert "secret-openai-token" not in command
    assert str(Path.home() / ".local") not in command[command.index("PATH") + 1]
    assert "--ignore-user-config" not in command


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
    _write_executable_shim(bwrap_path)
    _write_executable_shim(claude_path)
    monkeypatch.setenv("PATH", str(bin_path))
    monkeypatch.setenv("CODEX_HOME", str(codex_home_path))
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(claude_config_dir_path))

    backend_config = _select_agent_backend_config(agent_backend="claude", agent_command=None)
    command = _build_bwrap_agent_command(
        repo_path=repo_path,
        backend_config=backend_config,
        python_venv_path=None,
    )

    assert _contains_subsequence(command, ["--bind", str(claude_config_dir_path), str(claude_config_dir_path)])
    assert _contains_subsequence(command, ["--setenv", "CLAUDE_CONFIG_DIR", str(claude_config_dir_path)])
    assert not _contains_subsequence(command, ["--bind", str(codex_home_path), str(codex_home_path)])
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
    _write_executable_shim(bwrap_path)
    _write_executable_shim(codex_path)
    monkeypatch.setenv("PATH", str(bin_path))
    monkeypatch.setenv("CODEX_HOME", str(codex_home_path))

    backend_config = _select_agent_backend_config(agent_backend="codex", agent_command=None)
    command = _build_bwrap_agent_command(
        repo_path=repo_path,
        backend_config=backend_config,
        python_venv_path=None,
    )

    assert _contains_subsequence(command, ["--ro-bind", str(codex_path), str(WORKER_AGENT_BINARY_PATH)])


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
    _write_executable_shim(bwrap_path)
    _write_executable_shim(claude_path)
    monkeypatch.setenv("PATH", str(bin_path))
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(claude_config_dir_path))

    backend_config = _select_agent_backend_config(agent_backend="claude", agent_command=None)
    command = _build_bwrap_agent_command(
        repo_path=repo_path,
        backend_config=backend_config,
        python_venv_path=None,
        allowed_bash_commands=[
            "python -m pytest ralph/tests/test_run_ralph_loop.py",
            "git add .",
            "git commit --no-verify -m *",
            "git rev-parse HEAD",
        ],
    )

    assert _contains_subsequence(command, ["--ro-bind", str(claude_path), str(WORKER_AGENT_BINARY_PATH)])
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


def test_extract_claude_stream_result_text_prefers_result_event() -> None:
    raw_output = "\n".join([
        json.dumps({
            "type": "assistant",
            "message": {
                "content": [
                    {"type": "text", "text": "partial answer"},
                ],
            },
        }),
        json.dumps({
            "type": "result",
            "result": "final answer\n<promise>BLOCKED</promise>",
        }),
    ])

    assert _extract_claude_stream_result_text(raw_output) == "final answer\n<promise>BLOCKED</promise>"


def test_extract_claude_stream_result_text_falls_back_to_final_assistant_event() -> None:
    raw_output = "\n".join([
        json.dumps({
            "type": "assistant",
            "message": {
                "content": [
                    {"type": "text", "text": "first answer"},
                ],
            },
        }),
        json.dumps({
            "type": "assistant",
            "message": {
                "content": [
                    {"type": "text", "text": "final answer"},
                ],
            },
        }),
    ])

    assert _extract_claude_stream_result_text(raw_output) == "final answer"


def test_build_worker_allowed_bash_commands_combines_controller_and_plan_commands() -> None:
    task = {
        "allowed_bash_commands": ["rg *", "sed -n *"],
        "verification_commands": ["python -m pytest ralph/tests/test_run_ralph_loop.py"],
    }

    allowed_bash_commands = _build_worker_allowed_bash_commands(task)

    assert allowed_bash_commands == [
        "git status",
        "git status --short",
        "git diff",
        "git diff --staged",
        "git ls-files",
        "git add .",
        "git commit --no-verify -m *",
        "git rev-parse HEAD",
        "rg *",
        "sed -n *",
        "python -m pytest ralph/tests/test_run_ralph_loop.py",
    ]


def test_build_agent_visibility_smoke_test_prompt_checks_sandbox_contract(tmp_path: Path) -> None:
    repo_path = tmp_path / "target repo"
    agent_state_dir = tmp_path / "codex home"
    python_venv_path = tmp_path / "tool venv"

    prompt = _build_agent_visibility_smoke_test_prompt(
        repo_path=repo_path,
        backend_config=_build_test_backend_config(
            backend_name="codex",
            agent_state_dir=agent_state_dir,
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
    assert str(agent_state_dir) in prompt
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
    prompt = _build_agent_visibility_smoke_test_prompt(
        repo_path=tmp_path / "target-repo",
        backend_config=_build_test_backend_config(
            backend_name="codex",
            agent_state_dir=tmp_path / "codex-home",
            agent_home_environment_variable="CODEX_HOME",
        ),
        python_venv_path=None,
    )

    assert "VIRTUAL_ENV" not in prompt
    assert "printf blocked" not in prompt


def test_build_agent_visibility_smoke_test_prompt_does_not_reject_explicit_mounts(tmp_path: Path) -> None:
    prompt = _build_agent_visibility_smoke_test_prompt(
        repo_path=tmp_path / "target-repo",
        backend_config=_build_test_backend_config(
            backend_name="codex",
            agent_state_dir=Path("/workspace/.codex"),
            agent_home_environment_variable="CODEX_HOME",
        ),
        python_venv_path=None,
    )

    assert "test ! -e /workspace/.codex" not in prompt
    assert f'test "${{CODEX_HOME-}}" = {shlex.quote("/workspace/.codex")}' in prompt


def test_build_agent_visibility_smoke_test_prompt_hides_unselected_backend_state(tmp_path: Path) -> None:
    prompt = _build_agent_visibility_smoke_test_prompt(
        repo_path=tmp_path / "target-repo",
        backend_config=_build_test_backend_config(
            backend_name="claude",
            agent_state_dir=Path("/workspace/.claude"),
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
        _run_agent_visibility_smoke_test(
            repo_path=missing_repo_path,
            agent_backend="codex",
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
        "ralph.run_ralph_loop._build_sensitive_paths_that_workers_must_not_see",
        lambda: [sensitive_state_path],
    )

    with pytest.raises(ValueError, match="Target repo must not overlap"):
        _run_agent_visibility_smoke_test(
            repo_path=repo_path,
            agent_backend="codex",
            agent_command="agent-cli",
            python_venv_path=None,
        )


def test_worker_visible_path_check_rejects_hidden_state_overlap_but_accepts_normal_repo_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    normal_repo_path = tmp_path / "target-repo"
    hidden_state_path = tmp_path / "hidden-state"
    normal_repo_path.mkdir()
    hidden_state_path.mkdir()
    monkeypatch.setattr(
        "ralph.run_ralph_loop._build_sensitive_paths_that_workers_must_not_see",
        lambda: [hidden_state_path],
    )

    _reject_worker_visible_path_that_overlaps_hidden_state(
        path=normal_repo_path,
        role="Target repo",
    )

    with pytest.raises(ValueError, match="Target repo must not overlap"):
        _reject_worker_visible_path_that_overlaps_hidden_state(
            path=hidden_state_path,
            role="Target repo",
        )


def test_refuse_unsafe_starting_state_rejects_sensitive_repo_mount(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo_path = _initialise_git_repo(tmp_path / "target-repo")
    job = _create_job_with_ledger(tmp_path, _build_example_ledger())
    sensitive_state_path = repo_path / ".aws"
    sensitive_state_path.mkdir()
    monkeypatch.setattr(
        "ralph.run_ralph_loop._build_sensitive_paths_that_workers_must_not_see",
        lambda: [sensitive_state_path],
    )

    with pytest.raises(ValueError, match="Target repo must not overlap"):
        _refuse_unsafe_starting_state(repo_path, job)


def test_refuse_unsafe_starting_state_accepts_public_ralph_examples(tmp_path: Path) -> None:
    repo_path = _initialise_git_repo(tmp_path / "target-repo")
    job = _create_job_with_ledger(tmp_path, _build_example_ledger())
    example_plan_path = repo_path / "ralph" / "examples" / "PLAN.md"
    example_plan_path.parent.mkdir(parents=True)
    example_plan_path.write_text("Example Ralph plan.")
    _run_git(repo_path, "add", ".")
    _run_git(repo_path, "commit", "-m", "Add example Ralph plan")

    _refuse_unsafe_starting_state(repo_path, job)


def test_require_codex_home_path_rejects_missing_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("CODEX_HOME", raising=False)

    with pytest.raises(RuntimeError, match="CODEX_HOME must be set"):
        _require_codex_home_path()


def test_require_codex_home_path_accepts_exact_codex_home(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    codex_home_path = tmp_path / ".codex"
    codex_home_path.mkdir()
    monkeypatch.setenv("CODEX_HOME", str(codex_home_path))
    monkeypatch.setattr(
        "ralph.run_ralph_loop._build_sensitive_paths_that_workers_must_not_see",
        lambda: [codex_home_path],
    )

    assert _require_codex_home_path() == codex_home_path


def test_require_codex_home_path_accepts_symlink_to_exact_codex_home(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    codex_home_path = tmp_path / ".codex"
    codex_home_link_path = tmp_path / "codex-link"
    codex_home_path.mkdir()
    codex_home_link_path.symlink_to(codex_home_path)
    monkeypatch.setenv("CODEX_HOME", str(codex_home_link_path))
    monkeypatch.setattr(
        "ralph.run_ralph_loop._build_sensitive_paths_that_workers_must_not_see",
        lambda: [codex_home_path],
    )

    assert _require_codex_home_path() == codex_home_path


def test_require_codex_home_path_rejects_broad_sensitive_parent(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    codex_home_path = tmp_path / "workspace"
    sensitive_state_path = codex_home_path / ".aws"
    sensitive_state_path.mkdir(parents=True)
    monkeypatch.setenv("CODEX_HOME", str(codex_home_path))
    monkeypatch.setattr(
        "ralph.run_ralph_loop._build_sensitive_paths_that_workers_must_not_see",
        lambda: [codex_home_path / ".codex", sensitive_state_path],
    )

    with pytest.raises(ValueError, match="CODEX_HOME must not overlap"):
        _require_codex_home_path()


def test_resolve_python_venv_path_rejects_sensitive_path_overlap(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sensitive_state_path = tmp_path / "sensitive-state"
    python_venv_path = sensitive_state_path / "tool-venv"
    _create_python_venv_shape(python_venv_path)
    monkeypatch.setattr(
        "ralph.run_ralph_loop._build_sensitive_paths_that_workers_must_not_see",
        lambda: [sensitive_state_path],
    )

    with pytest.raises(ValueError, match="Python venv must not overlap"):
        _resolve_python_venv_path(str(python_venv_path))


def test_resolve_python_venv_path_accepts_non_sensitive_helper_venv(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    python_venv_path = tmp_path / "tool-venv"
    _create_python_venv_shape(python_venv_path)
    monkeypatch.setattr(
        "ralph.run_ralph_loop._build_sensitive_paths_that_workers_must_not_see",
        lambda: [tmp_path / "sensitive-state"],
    )

    assert _resolve_python_venv_path(str(python_venv_path)) == python_venv_path


def test_marks_task_done_without_mutating_input() -> None:
    ledger = _build_example_ledger()

    updated_ledger = _mark_task_done(ledger, "R1")

    assert ledger["tasks"][0]["status"] == "pending"
    assert updated_ledger["tasks"][0]["status"] == "done"
    assert "completed_at" in updated_ledger["tasks"][0]


def test_accepts_worker_completed_task_after_worker_verifies_and_commits(
    tmp_path: Path,
) -> None:
    repo_path = _initialise_git_repo(tmp_path / "target-repo")
    ledger = _build_example_ledger()
    job = _create_job_with_ledger(tmp_path, ledger)
    task_path = tmp_path / "task"
    parser_path = repo_path / "src" / "parser.py"
    parser_path.parent.mkdir()
    parser_path.write_text("def parse_value(value):\n    return value\n")
    _run_git(repo_path, "add", ".")
    _run_git(repo_path, "commit", "--no-verify", "-m", "Ralph: R1 Add parser")
    worker_commit_hash = _run_git(repo_path, "rev-parse", "HEAD").strip()
    agent_output = "\n".join(
        [
            "RALPH_VERIFICATION_BEGIN",
            "$ test -f src/parser.py",
            "RALPH_VERIFICATION_END",
            f"RALPH_COMMIT {worker_commit_hash}",
            "<promise>DONE</promise>",
        ]
    )

    accepted_commit_hash = _accept_worker_completed_task(
        repo_path=repo_path,
        job=job,
        ledger=ledger,
        selection=_select_first_task(ledger),
        task_path=task_path,
        agent_output=agent_output,
    )

    committed_subject = _run_git(repo_path, "log", "--format=%s", "-1").strip()

    assert accepted_commit_hash == worker_commit_hash
    assert committed_subject == "Ralph: R1 Add parser"
    assert yaml.safe_load(job.ledger_path.read_text())["tasks"][0]["status"] == "done"
    assert "$ test -f src/parser.py" in task_path.joinpath("verification-output.txt").read_text()
    assert task_path.joinpath("commit.txt").read_text() == worker_commit_hash


def test_accept_worker_completed_task_rejects_uncommitted_worker_changes(
    tmp_path: Path,
) -> None:
    repo_path = _initialise_git_repo(tmp_path / "target-repo")
    ledger = _build_example_ledger()
    job = _create_job_with_ledger(tmp_path, ledger)
    task_path = tmp_path / "task"
    parser_path = repo_path / "src" / "parser.py"
    parser_path.parent.mkdir()
    parser_path.write_text("def parse_value(value):\n    return value\n")
    _run_git(repo_path, "add", ".")
    _run_git(repo_path, "commit", "--no-verify", "-m", "Ralph: R1 Add parser")
    worker_commit_hash = _run_git(repo_path, "rev-parse", "HEAD").strip()
    parser_path.write_text("def parse_value(value):\n    return value.strip()\n")
    agent_output = "\n".join(
        [
            "RALPH_VERIFICATION_BEGIN",
            "$ test -f src/parser.py",
            "RALPH_VERIFICATION_END",
            f"RALPH_COMMIT {worker_commit_hash}",
            "<promise>DONE</promise>",
        ]
    )

    with pytest.raises(RuntimeError, match="uncommitted target repo changes"):
        _accept_worker_completed_task(
            repo_path=repo_path,
            job=job,
            ledger=ledger,
            selection=_select_first_task(ledger),
            task_path=task_path,
            agent_output=agent_output,
        )

    assert yaml.safe_load(job.ledger_path.read_text())["tasks"][0]["status"] == "pending"
    assert "$ test -f src/parser.py" in task_path.joinpath("verification-output.txt").read_text()
    assert task_path.joinpath("commit.txt").read_text() == worker_commit_hash


def test_accept_worker_completed_task_rejects_missing_verification_transcript(
    tmp_path: Path,
) -> None:
    repo_path = _initialise_git_repo(tmp_path / "target-repo")
    ledger = _build_example_ledger()
    job = _create_job_with_ledger(tmp_path, ledger)

    with pytest.raises(RuntimeError, match="verification transcript entries"):
        _accept_worker_completed_task(
            repo_path=repo_path,
            job=job,
            ledger=ledger,
            selection=_select_first_task(ledger),
            task_path=tmp_path / "task",
            agent_output="\n".join(
                [
                    "RALPH_VERIFICATION_BEGIN",
                    "$ python -m pytest",
                    "RALPH_VERIFICATION_END",
                    f"RALPH_COMMIT {_run_git(repo_path, 'rev-parse', 'HEAD').strip()}",
                    "<promise>DONE</promise>",
                ]
            ),
        )

    assert yaml.safe_load(job.ledger_path.read_text())["tasks"][0]["status"] == "pending"


def test_materialises_planned_notion_task_under_existing_alovya_parent(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ledger = _build_ledger_with_planned_notion_task(related_to="ALOVYA-89")
    job = _create_job_with_ledger(tmp_path, ledger)
    task_path = tmp_path / "task"
    task_path.mkdir()
    observed_commands: list[list[str]] = []

    def run_notion_tracker_command_mock(command: list[str]) -> subprocess.CompletedProcess[str]:
        observed_commands.append(command)
        return subprocess.CompletedProcess(
            args=command,
            returncode=0,
            stdout=json.dumps({"completed_operations": ["update_properties:task:ALOVYA-90"]}),
        )

    monkeypatch.setattr("ralph.run_ralph_loop._resolve_notion_tracker_command_path", lambda: "ntt")
    monkeypatch.setattr("ralph.run_ralph_loop._run_notion_tracker_command", run_notion_tracker_command_mock)

    updated_ledger = _materialise_planned_notion_task_before_worker_launch(
        job=job,
        ledger=ledger,
        task=ledger["tasks"][0],
        task_path=task_path,
    )

    assert updated_ledger["tasks"][0]["notion_task"]["materialized_task_id"] == "ALOVYA-90"
    assert yaml.safe_load(job.ledger_path.read_text())["tasks"][0]["notion_task"]["materialized_task_id"] == "ALOVYA-90"
    assert observed_commands == [[
        "ntt",
        "--child",
        "--parent-ticket-number",
        "89",
        "--title",
        "Add parser",
        "--content-path",
        str(task_path / "notion-create-content.json"),
        "--tracker-state-path",
        str(DEFAULT_NOTION_TRACKER_STATE_PATH),
        "--output-path",
        str(task_path / "notion-create-output.json"),
    ]]


def test_materialises_planned_notion_task_after_related_ralph_task_exists(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ledger = _build_ledger_with_planned_notion_task(related_to="R1", task_id="R2")
    ledger["tasks"].insert(0, {
        "id": "R1",
        "title": "Prepare parent",
        "status": "done",
        "depends_on": [],
        "notion_task": {
            "planned": True,
            "relationship": "child",
            "related_to": "ALOVYA-89",
            "title": "Prepare parent",
            "materialized_task_id": "ALOVYA-90",
        },
    })
    ledger["tasks"][1]["depends_on"] = ["R1"]
    job = _create_job_with_ledger(tmp_path, ledger)
    task_path = tmp_path / "task"
    task_path.mkdir()
    observed_commands: list[list[str]] = []

    def run_notion_tracker_command_mock(command: list[str]) -> subprocess.CompletedProcess[str]:
        observed_commands.append(command)
        return subprocess.CompletedProcess(
            args=command,
            returncode=0,
            stdout=json.dumps({"completed_operations": ["update_properties:task:ALOVYA-91"]}),
        )

    monkeypatch.setattr("ralph.run_ralph_loop._resolve_notion_tracker_command_path", lambda: "ntt")
    monkeypatch.setattr("ralph.run_ralph_loop._run_notion_tracker_command", run_notion_tracker_command_mock)

    updated_ledger = _materialise_planned_notion_task_before_worker_launch(
        job=job,
        ledger=ledger,
        task=ledger["tasks"][1],
        task_path=task_path,
    )

    assert updated_ledger["tasks"][1]["notion_task"]["materialized_task_id"] == "ALOVYA-91"
    assert "--parent-ticket-number" in observed_commands[0]
    assert observed_commands[0][observed_commands[0].index("--parent-ticket-number") + 1] == "90"
    assert observed_commands[0][observed_commands[0].index("--tracker-state-path") + 1] == str(DEFAULT_NOTION_TRACKER_STATE_PATH)


def test_materialising_planned_notion_task_blocks_when_related_ralph_task_is_not_materialised(
    tmp_path: Path,
) -> None:
    ledger = _build_ledger_with_planned_notion_task(related_to="R1", task_id="R2")
    ledger["tasks"].insert(0, {
        "id": "R1",
        "title": "Prepare parent",
        "status": "done",
        "depends_on": [],
        "notion_task": {
            "planned": True,
            "relationship": "child",
            "related_to": "ALOVYA-89",
            "title": "Prepare parent",
            "materialized_task_id": None,
        },
    })
    ledger["tasks"][1]["depends_on"] = ["R1"]
    job = _create_job_with_ledger(tmp_path, ledger)
    task_path = tmp_path / "task"
    task_path.mkdir()

    with pytest.raises(RuntimeError, match="must materialise its Notion task"):
        _materialise_planned_notion_task_before_worker_launch(
            job=job,
            ledger=ledger,
            task=ledger["tasks"][1],
            task_path=task_path,
        )


def test_prepare_notion_task_blocks_worker_launch_when_notion_tracker_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ledger = _build_ledger_with_planned_notion_task(related_to="ALOVYA-89")
    job = _create_job_with_ledger(tmp_path, ledger)
    task_path = tmp_path / "task"
    task_path.mkdir()

    def run_notion_tracker_command_mock(command: list[str]) -> subprocess.CompletedProcess[str]:
        raise RuntimeError("Notion task tracker command failed")

    monkeypatch.setattr("ralph.run_ralph_loop._resolve_notion_tracker_command_path", lambda: "ntt")
    monkeypatch.setattr("ralph.run_ralph_loop._run_notion_tracker_command", run_notion_tracker_command_mock)

    with pytest.raises(RuntimeError, match="Notion task tracker command failed"):
        _prepare_notion_task_before_worker_runs_task(
            job=job,
            ledger=ledger,
            selection=_select_first_task(ledger),
            task_path=task_path,
        )

    assert yaml.safe_load(job.ledger_path.read_text())["tasks"][0]["notion_task"]["materialized_task_id"] is None


def test_controller_logs_slice_start_to_notion(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    selection = _select_first_task(_build_ledger_with_materialised_notion_task())
    observed_content = _capture_notion_log_content(monkeypatch)

    _log_slice_start_to_notion(selection=selection, task_path=tmp_path)

    assert observed_content["subheading"] == "Ralph R1 started"
    assert "Goal: Add parser" in observed_content["blocks"][0]["text"]
    assert "verification_commands" in observed_content["blocks"][1]["text"]
    assert observed_content["command"][observed_content["command"].index("--tracker-state-path") + 1] == str(
        DEFAULT_NOTION_TRACKER_STATE_PATH
    )


def test_controller_logs_blocked_worker_promise_to_notion(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    selection = _select_first_task(_build_ledger_with_materialised_notion_task())
    observed_content = _capture_notion_log_content(monkeypatch)

    _log_worker_promise_to_notion(
        selection=selection,
        task_path=tmp_path,
        promise="BLOCKED",
        agent_output="Missing dependency",
    )

    assert observed_content["subheading"] == "Worker returned BLOCKED"
    assert observed_content["blocks"][1]["text"] == "Missing dependency"


def test_controller_logs_failed_verification_to_notion(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    selection = _select_first_task(_build_ledger_with_materialised_notion_task())
    verification_output_path = tmp_path / "verification-output.txt"
    verification_output_path.write_text("$ pytest\nfailed\n")
    observed_content = _capture_notion_log_content(monkeypatch)

    _log_failed_verification_to_notion(selection=selection, task_path=tmp_path)

    assert observed_content["subheading"] == "Verification failed"
    assert observed_content["blocks"][1]["text"] == "$ pytest\nfailed\n"


def test_controller_logs_successful_verification_and_commit_to_notion(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    selection = _select_first_task(_build_ledger_with_materialised_notion_task())
    (tmp_path / "promise.txt").write_text("DONE")
    (tmp_path / "verification-output.txt").write_text("$ pytest\npassed\n")
    observed_content = _capture_notion_log_content(monkeypatch)

    _log_completed_worker_to_notion(
        selection=selection,
        task_path=tmp_path,
        changed_files=["M src/parser.py"],
        commit_hash="abc123",
    )

    assert observed_content["subheading"] == "Ralph R1 completed"
    assert observed_content["blocks"][0]["text"] == "Worker promise: DONE"
    assert observed_content["blocks"][1]["text"] == "M src/parser.py"
    assert observed_content["blocks"][2]["text"] == "$ pytest\npassed\n"
    assert observed_content["blocks"][3]["text"] == "Commit hash: abc123"


def test_extract_created_notion_task_id_uses_output_file_and_excludes_related_task(
    tmp_path: Path,
) -> None:
    output_path = tmp_path / "ntt-output.json"
    output_path.write_text(json.dumps({
        "completed_operations": [
            "update_timeline_log:task:ALOVYA-89:2026-06-18",
            "update_properties:task:ALOVYA-90",
        ]
    }))

    assert _extract_created_notion_task_id("", output_path, "ALOVYA-89") == "ALOVYA-90"


def test_build_notion_task_creation_command_builds_sibling_command(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("ralph.run_ralph_loop._resolve_notion_tracker_command_path", lambda: "ntt")

    command = _build_notion_task_creation_command(
        relationship="sibling",
        related_notion_task_id="ALOVYA-89",
        title="Add parser",
        content_path=tmp_path / "content.json",
        output_path=tmp_path / "output.json",
    )

    assert command == [
        "ntt",
        "--sibling",
        "--sibling-ticket-number",
        "89",
        "--title",
        "Add parser",
        "--content-path",
        str(tmp_path / "content.json"),
        "--tracker-state-path",
        str(DEFAULT_NOTION_TRACKER_STATE_PATH),
        "--output-path",
        str(tmp_path / "output.json"),
    ]


@pytest.mark.parametrize(
    ("mutate_ledger", "expected_message"),
    [
        (lambda ledger: ledger["tasks"][1]["notion_task"].__setitem__("planned", "yes"), "planned"),
        (lambda ledger: ledger["tasks"][1]["notion_task"].__setitem__("relationship", "parent"), "relationship"),
        (lambda ledger: ledger["tasks"][1]["notion_task"].__setitem__("related_to", ""), "related_to"),
        (lambda ledger: ledger["tasks"][1]["notion_task"].__setitem__("title", ""), "title"),
        (lambda ledger: ledger["tasks"][1]["notion_task"].__setitem__("materialized_task_id", "R1"), "materialized_task_id"),
        (lambda ledger: ledger["tasks"][1]["notion_task"].__setitem__("related_to", "R3"), "unknown Ralph task"),
        (lambda ledger: ledger["tasks"][1]["notion_task"].__setitem__("related_to", "R1"), "must depend on related Ralph task"),
    ],
)
def test_read_tasks_rejects_malformed_notion_task_entries(mutate_ledger, expected_message: str) -> None:
    ledger = _build_ledger_with_planned_notion_task(related_to="ALOVYA-89", task_id="R2")
    ledger["tasks"].insert(0, {
        "id": "R1",
        "title": "Prepare parent",
        "status": "pending",
        "depends_on": [],
    })
    mutate_ledger(ledger)

    with pytest.raises(ValueError, match=expected_message):
        _read_tasks_from_ledger(ledger)


def test_generate_codex_execpolicy_rules_renders_prefix_rule_syntax() -> None:
    allowed_bash_commands = ["rg pattern", "sed -n 1p"]

    rules = _generate_codex_execpolicy_rules(allowed_bash_commands)

    assert rules == (
        "prefix_rule(pattern=['rg', 'pattern'], decision=\"allow\")\n"
        "prefix_rule(pattern=['sed', '-n', '1p'], decision=\"allow\")\n"
    )


def test_parse_command_to_execpolicy_pattern_strips_final_wildcard() -> None:
    assert _parse_command_to_execpolicy_pattern("rg *") == ["rg"]
    assert _parse_command_to_execpolicy_pattern("sed -n *") == ["sed", "-n"]
    assert _parse_command_to_execpolicy_pattern("git commit --no-verify -m *") == [
        "git", "commit", "--no-verify", "-m"
    ]


def test_parse_command_to_execpolicy_pattern_preserves_literal_arguments() -> None:
    assert _parse_command_to_execpolicy_pattern("python -m pytest tests/test_run.py") == [
        "python", "-m", "pytest", "tests/test_run.py"
    ]


def test_parse_command_to_execpolicy_pattern_rejects_non_final_wildcard() -> None:
    with pytest.raises(ValueError, match="only allowed as the final token"):
        _parse_command_to_execpolicy_pattern("git * commit")


def test_parse_command_to_execpolicy_pattern_rejects_command_only_wildcard() -> None:
    with pytest.raises(ValueError, match="cannot be only a wildcard"):
        _parse_command_to_execpolicy_pattern("*")


def test_write_codex_rules_atomically_creates_rules_directory(tmp_path: Path) -> None:
    rules_path = tmp_path / "rules" / "default.rules"

    _write_codex_rules_atomically(rules_path, "prefix_rule(pattern=['rg'], decision=\"allow\")\n")

    assert rules_path.is_file()
    assert rules_path.read_text() == "prefix_rule(pattern=['rg'], decision=\"allow\")\n"


def test_write_codex_rules_atomically_replaces_existing_rules(tmp_path: Path) -> None:
    rules_path = tmp_path / "rules" / "default.rules"
    rules_path.parent.mkdir(parents=True)
    rules_path.write_text("old rules content")

    _write_codex_rules_atomically(rules_path, "new rules content")

    assert rules_path.read_text() == "new rules content"


def test_write_codex_rules_atomically_leaves_no_temp_file_after_success(tmp_path: Path) -> None:
    rules_path = tmp_path / "rules" / "default.rules"

    _write_codex_rules_atomically(rules_path, "content")

    temp_path = rules_path.with_suffix(".rules.tmp")
    assert not temp_path.exists()


def test_snapshot_codex_rules_captures_existing_content(tmp_path: Path) -> None:
    rules_path = tmp_path / "rules" / "default.rules"
    rules_path.parent.mkdir(parents=True)
    rules_path.write_text("original rules")

    snapshot = _snapshot_codex_rules(rules_path)

    assert snapshot.existed is True
    assert snapshot.content == "original rules"


def test_snapshot_codex_rules_records_absence(tmp_path: Path) -> None:
    rules_path = tmp_path / "rules" / "default.rules"

    snapshot = _snapshot_codex_rules(rules_path)

    assert snapshot.existed is False
    assert snapshot.content is None


def test_restore_codex_rules_recreates_original_content(tmp_path: Path) -> None:
    rules_path = tmp_path / "rules" / "default.rules"
    rules_path.parent.mkdir(parents=True)
    rules_path.write_text("modified rules")

    _restore_codex_rules(rules_path, CodexRulesSnapshot(existed=True, content="original rules"))

    assert rules_path.read_text() == "original rules"


def test_restore_codex_rules_removes_rules_when_originally_absent(tmp_path: Path) -> None:
    rules_path = tmp_path / "rules" / "default.rules"
    rules_path.parent.mkdir(parents=True)
    rules_path.write_text("generated rules")

    _restore_codex_rules(rules_path, CodexRulesSnapshot(existed=False, content=None))

    assert not rules_path.exists()


def test_write_and_read_codex_rules_backup(tmp_path: Path) -> None:
    marker_path = tmp_path / "task" / CODEX_RULES_BACKUP_FILENAME
    original_snapshot = CodexRulesSnapshot(existed=True, content="original rules")

    _write_codex_rules_backup(marker_path, original_snapshot)
    recovered_snapshot = _read_codex_rules_backup(marker_path)

    assert recovered_snapshot.existed is True
    assert recovered_snapshot.content == "original rules"


def test_codex_rules_backup_location_under_ralph_task_directory(tmp_path: Path) -> None:
    task_path = tmp_path / "tasks" / "R1_20260621T120000Z"
    task_path.mkdir(parents=True)
    marker_path = task_path / CODEX_RULES_BACKUP_FILENAME

    _write_codex_rules_backup(marker_path, CodexRulesSnapshot(existed=False, content=None))

    assert marker_path.is_file()
    assert marker_path.parent == task_path


def test_find_interrupted_codex_rules_backup_returns_backup_path(tmp_path: Path) -> None:
    job = _create_job_with_ledger(tmp_path, _build_example_ledger())
    task_path = job.tasks_path / "R1_20260621T120000Z"
    task_path.mkdir(parents=True)
    marker_path = task_path / CODEX_RULES_BACKUP_FILENAME
    marker_path.write_text('{"existed": true, "content": "original"}')

    found_marker = _find_interrupted_codex_rules_backup(job)

    assert found_marker == marker_path


def test_find_interrupted_codex_rules_backup_returns_none_when_absent(tmp_path: Path) -> None:
    job = _create_job_with_ledger(tmp_path, _build_example_ledger())
    job.tasks_path.mkdir(parents=True, exist_ok=True)

    found_marker = _find_interrupted_codex_rules_backup(job)

    assert found_marker is None


def test_recover_interrupted_codex_rules_restores_and_raises(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    codex_home_path = tmp_path / "codex-home"
    codex_home_path.mkdir()
    rules_path = _codex_rules_path(codex_home_path)
    rules_path.parent.mkdir(parents=True)
    rules_path.write_text("generated rules")

    job = _create_job_with_ledger(tmp_path, _build_example_ledger())
    task_path = job.tasks_path / "R1_20260621T120000Z"
    task_path.mkdir(parents=True)
    marker_path = task_path / CODEX_RULES_BACKUP_FILENAME
    marker_path.write_text('{"existed": true, "content": "original rules"}')

    monkeypatch.setenv("CODEX_HOME", str(codex_home_path))

    with pytest.raises(RuntimeError, match="Recovered Codex rules left by interrupted worker"):
        _recover_interrupted_codex_rules(job)

    assert rules_path.read_text() == "original rules"
    assert not marker_path.exists()


def test_recover_interrupted_codex_rules_removes_rules_when_originally_absent(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    codex_home_path = tmp_path / "codex-home"
    codex_home_path.mkdir()
    rules_path = _codex_rules_path(codex_home_path)
    rules_path.parent.mkdir(parents=True)
    rules_path.write_text("generated rules")

    job = _create_job_with_ledger(tmp_path, _build_example_ledger())
    task_path = job.tasks_path / "R1_20260621T120000Z"
    task_path.mkdir(parents=True)
    marker_path = task_path / CODEX_RULES_BACKUP_FILENAME
    marker_path.write_text('{"existed": false, "content": null}')

    monkeypatch.setenv("CODEX_HOME", str(codex_home_path))

    with pytest.raises(RuntimeError, match="Recovered Codex rules left by interrupted worker"):
        _recover_interrupted_codex_rules(job)

    assert not rules_path.exists()
    assert not marker_path.exists()


def test_codex_permission_setup_writes_temporary_rules_then_restores_original_rules(
    tmp_path: Path,
) -> None:
    codex_home_path = tmp_path / "codex-home"
    task_path = tmp_path / "task"
    rules_path = _codex_rules_path(codex_home_path)
    codex_home_path.mkdir()
    task_path.mkdir()
    rules_path.parent.mkdir(parents=True)
    rules_path.write_text("original rules", encoding="utf-8")
    observed_rules_inside_context: list[str] = []
    observed_backup_inside_context: list[bool] = []

    backend_config = AgentBackend(
        backend_name="codex",
        command_name="codex",
        agent_state_dir=codex_home_path,
        agent_home_environment_variable="CODEX_HOME",
    )

    with _codex_permission_setup(
        backend_config=backend_config,
        allowed_bash_commands=["rg *"],
        task_path=task_path,
    ):
        observed_rules_inside_context.append(rules_path.read_text(encoding="utf-8"))
        observed_backup_inside_context.append(
            (task_path / CODEX_RULES_BACKUP_FILENAME).is_file()
        )

    assert observed_backup_inside_context == [True]
    assert observed_rules_inside_context == ["prefix_rule(pattern=['rg'], decision=\"allow\")\n"]
    assert rules_path.read_text(encoding="utf-8") == "original rules"
    assert not (task_path / CODEX_RULES_BACKUP_FILENAME).exists()


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
    _write_executable_shim(bwrap_path)
    _write_executable_shim(codex_path)
    monkeypatch.setenv("PATH", str(bin_path))
    monkeypatch.setenv("CODEX_HOME", str(codex_home_path))

    backend_config = _select_agent_backend_config(agent_backend="codex", agent_command=None)
    command = _build_bwrap_agent_command(
        repo_path=repo_path,
        backend_config=backend_config,
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


def test_accepts_example_ledger() -> None:
    example_ledger_path = Path(__file__).resolve().parents[1] / "examples" / "ledger.yaml"
    ledger = yaml.safe_load(example_ledger_path.read_text())

    assert _read_tasks_from_ledger(ledger)


@pytest.mark.parametrize("command_policy_key", ["allowed_bash_commands", "verification_commands"])
def test_read_tasks_rejects_command_policy_in_ledger(command_policy_key: str) -> None:
    ledger = _build_example_ledger()
    ledger["tasks"][0][command_policy_key] = ["rg *"]

    with pytest.raises(ValueError, match=f"must keep {command_policy_key} in PLAN.md"):
        _read_tasks_from_ledger(ledger)


def _build_example_ledger() -> dict[str, object]:
    return {
        "version": 1,
        "job_name": "example",
        "tasks": [
            {
                "id": "R1",
                "title": "Add parser",
                "status": "pending",
                "depends_on": [],
                "touchable_paths": ["src/parser.py"],
            },
            {
                "id": "R2",
                "title": "Add command line entrypoint",
                "status": "pending",
                "depends_on": ["R1"],
                "touchable_paths": ["src/cli.py"],
            },
        ],
    }


def _build_ledger_where_first_pending_task_waits_and_second_pending_task_is_ready() -> dict[str, object]:
    return {
        "version": 1,
        "job_name": "example",
        "tasks": [
            {
                "id": "R0",
                "title": "Prepare dependency",
                "status": "blocked",
                "depends_on": [],
                "touchable_paths": ["src/dependency.py"],
            },
            {
                "id": "R1",
                "title": "Wait for dependency",
                "status": "pending",
                "depends_on": ["R0"],
                "touchable_paths": ["src/waiting.py"],
            },
            {
                "id": "R2",
                "title": "First ready task",
                "status": "pending",
                "depends_on": [],
                "touchable_paths": ["src/first_ready.py"],
            },
            {
                "id": "R3",
                "title": "Second ready task",
                "status": "pending",
                "depends_on": [],
                "touchable_paths": ["src/second_ready.py"],
            },
        ],
    }


def _build_example_plan() -> str:
    return """
<!-- ralph-shared:start -->
Shared context.
<!-- ralph-shared:end -->

<!-- ralph-task:start R1 -->
First task context.

<!-- ralph-allowed-bash:start -->
- rg *
- sed -n *
<!-- ralph-allowed-bash:end -->

<!-- ralph-verification:start -->
- test -f src/parser.py
<!-- ralph-verification:end -->
<!-- ralph-task:end R1 -->

<!-- ralph-task:start R2 -->
Second task context.

<!-- ralph-allowed-bash:start -->
- rg *
- sed -n *
<!-- ralph-allowed-bash:end -->

<!-- ralph-verification:start -->
- python -m pytest tests/test_cli.py
<!-- ralph-verification:end -->
<!-- ralph-task:end R2 -->
"""


def _build_three_task_plan() -> str:
    return """
<!-- ralph-shared:start -->
Shared context.
<!-- ralph-shared:end -->

<!-- ralph-task:start R0 -->
Dependency task context.

<!-- ralph-allowed-bash:start -->
- rg *
<!-- ralph-allowed-bash:end -->

<!-- ralph-verification:start -->
- test -f src/dependency.py
<!-- ralph-verification:end -->
<!-- ralph-task:end R0 -->

<!-- ralph-task:start R1 -->
Waiting task context.

<!-- ralph-allowed-bash:start -->
- rg *
<!-- ralph-allowed-bash:end -->

<!-- ralph-verification:start -->
- test -f src/waiting.py
<!-- ralph-verification:end -->
<!-- ralph-task:end R1 -->

<!-- ralph-task:start R2 -->
Second task context.

<!-- ralph-allowed-bash:start -->
- rg *
<!-- ralph-allowed-bash:end -->

<!-- ralph-verification:start -->
- test -f src/first_ready.py
<!-- ralph-verification:end -->
<!-- ralph-task:end R2 -->

<!-- ralph-task:start R3 -->
Third task context.

<!-- ralph-allowed-bash:start -->
- rg *
<!-- ralph-allowed-bash:end -->

<!-- ralph-verification:start -->
- test -f src/second_ready.py
<!-- ralph-verification:end -->
<!-- ralph-task:end R3 -->
"""


def _build_ledger_with_planned_notion_task(related_to: str, task_id: str = "R1") -> dict[str, object]:
    return {
        "version": 1,
        "job_name": "example",
        "tasks": [
            {
                "id": task_id,
                "title": "Add parser",
                "status": "pending",
                "depends_on": [],
                "touchable_paths": ["src/parser.py"],
                "notion_task": {
                    "planned": True,
                    "relationship": "child",
                    "related_to": related_to,
                    "title": "Add parser",
                    "materialized_task_id": None,
                },
            }
        ],
    }


def _build_ledger_with_materialised_notion_task() -> dict[str, object]:
    ledger = _build_ledger_with_planned_notion_task(related_to="ALOVYA-89")
    ledger["tasks"][0]["notion_task"]["materialized_task_id"] = "ALOVYA-90"
    return ledger


def _capture_notion_log_content(monkeypatch: pytest.MonkeyPatch) -> dict[str, object]:
    observed_content: dict[str, object] = {}

    def run_notion_tracker_command_mock(command: list[str]) -> subprocess.CompletedProcess[str]:
        content_path = Path(command[command.index("--content-path") + 1])
        observed_content.update(json.loads(content_path.read_text(encoding="utf-8")))
        observed_content["command"] = command
        return subprocess.CompletedProcess(args=command, returncode=0, stdout="{}")

    monkeypatch.setattr("ralph.run_ralph_loop._resolve_notion_tracker_command_path", lambda: "ntt")
    monkeypatch.setattr("ralph.run_ralph_loop._run_notion_tracker_command", run_notion_tracker_command_mock)
    return observed_content


def _contains_subsequence(command: list[str], expected: list[str]) -> bool:
    return any(
        command[index:index + len(expected)] == expected
        for index in range(len(command) - len(expected) + 1)
    )


def _build_test_backend_config(
    backend_name: str,
    agent_state_dir: Path,
    agent_home_environment_variable: str,
) -> AgentBackend:
    return AgentBackend(
        backend_name=backend_name,
        command_name=f"{backend_name}-cli",
        agent_state_dir=agent_state_dir,
        agent_home_environment_variable=agent_home_environment_variable,
    )


def _command_windows(command: list[str], size: int) -> list[list[str]]:
    return [
        command[index:index + size]
        for index in range(len(command) - size + 1)
    ]


def _select_first_task(ledger: dict[str, object]) -> TaskSelection:
    return TaskSelection(
        task={
            **ledger["tasks"][0],
            "allowed_bash_commands": ["rg *", "sed -n *"],
            "verification_commands": ["test -f src/parser.py"],
        },
        shared_plan_context="Shared context.",
        active_task_plan_context="First task context.",
    )


def _create_job_with_ledger(tmp_path: Path, ledger: dict[str, object]) -> RalphJob:
    job_path = tmp_path / "job"
    job = RalphJob(
        job_name="example",
        job_path=job_path,
        plan_path=job_path / "PLAN.md",
        ledger_path=job_path / "ledger.yaml",
        tasks_path=job_path / "tasks",
    )
    job_path.mkdir()
    _write_yaml_file(job.ledger_path, ledger)
    return job


def _initialise_git_repo(repo_path: Path) -> Path:
    repo_path.mkdir()
    _run_git(repo_path, "init")
    _run_git(repo_path, "config", "user.email", "ralph-test@example.com")
    _run_git(repo_path, "config", "user.name", "Ralph Test")
    readme_path = repo_path / "README.md"
    readme_path.write_text("Ralph test repository\n")
    _run_git(repo_path, "add", ".")
    _run_git(repo_path, "commit", "-m", "Initial commit")
    return repo_path


def _create_python_venv_shape(python_venv_path: Path) -> None:
    python_path = python_venv_path / "bin" / "python"
    python_path.parent.mkdir(parents=True)
    python_path.write_text("")


def _write_executable_shim(shim_path: Path) -> None:
    shim_path.write_text("#!/bin/sh\nexit 0\n")
    shim_path.chmod(0o755)


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


def _quote_shell_path(path: Path) -> str:
    return shlex.quote(str(path))
