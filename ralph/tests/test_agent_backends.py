from __future__ import annotations

import json
from pathlib import Path

import pytest

from ralph.agent_backends import (
    AgentBackend,
    build_worker_allowed_bash_commands,
    run_command_and_save_agent_transcripts,
    run_command_and_tee_output,
    select_agent_backend_config,
)


def test_codex_backend_uses_ralph_agent_command_before_codex_specific_default(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    codex_home_path = tmp_path / "codex-home"
    codex_home_path.mkdir()
    monkeypatch.setenv("CODEX_HOME", str(codex_home_path))
    monkeypatch.setenv("RALPH_AGENT_COMMAND", "custom-agent")
    monkeypatch.setenv("RALPH_CODEX_COMMAND", "custom-codex")

    backend_config = select_agent_backend_config(agent_backend="codex", agent_command=None)

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

    backend_config = select_agent_backend_config(agent_backend="codex", agent_command=None)

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

    backend_config = select_agent_backend_config(agent_backend="codex", agent_command="override-agent")

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

    backend_config = select_agent_backend_config(agent_backend="codex", agent_command=None)

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

    backend_config = select_agent_backend_config(agent_backend="claude", agent_command=None)

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

    backend_config = select_agent_backend_config(agent_backend="claude", agent_command=None)

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

    backend_config = select_agent_backend_config(agent_backend="claude", agent_command=None)

    assert backend_config.command_name == "claude"


def test_build_worker_allowed_bash_commands_combines_controller_and_plan_commands() -> None:
    task = {
        "allowed_bash_commands": ["rg *", "sed -n *"],
        "verification_commands": ["python -m pytest ralph/tests/test_run_ralph_loop.py"],
    }

    allowed_bash_commands = build_worker_allowed_bash_commands(task)

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


def test_run_command_and_tee_output_writes_to_terminal_and_file(
    tmp_path: Path,
    capsys,
) -> None:
    output_path = tmp_path / "agent-output.txt"

    completed_process = run_command_and_tee_output(
        command=["bash", "-lc", "printf 'before\\n'; cat; printf 'after\\n'"],
        input_text="middle\n",
        output_path=output_path,
    )

    assert completed_process.returncode == 0
    assert completed_process.stdout == "before\nmiddle\nafter\n"
    assert output_path.read_text(encoding="utf-8") == "before\nmiddle\nafter\n"
    assert capsys.readouterr().out == "before\nmiddle\nafter\n"


def test_run_command_and_save_agent_transcripts_keeps_codex_transcript_plain(
    tmp_path: Path,
    capsys,
) -> None:
    output_path = tmp_path / "agent-output.txt"
    backend_config = AgentBackend(
        backend_name="codex",
        command_name="bash",
        agent_state_dir=tmp_path / "codex-home",
        agent_home_environment_variable="CODEX_HOME",
    )

    completed_process = run_command_and_save_agent_transcripts(
        command=["bash", "-lc", "printf 'before\\n'; cat; printf 'after\\n'"],
        input_text="middle\n",
        output_path=output_path,
        backend_config=backend_config,
        tee_output=True,
    )

    assert completed_process.returncode == 0
    assert completed_process.stdout == "before\nmiddle\nafter\n"
    assert output_path.read_text(encoding="utf-8") == "before\nmiddle\nafter\n"
    assert not (tmp_path / "agent-output.raw.jsonl").exists()
    assert capsys.readouterr().out == "before\nmiddle\nafter\n"


def test_run_command_and_save_agent_transcripts_keeps_claude_raw_stream_and_readable_transcript(
    tmp_path: Path,
    capsys,
) -> None:
    output_path = tmp_path / "agent-output.txt"
    raw_output_path = tmp_path / "agent-output.raw.jsonl"
    backend_config = AgentBackend(
        backend_name="claude",
        command_name="/workspace/venv/bin/python",
        agent_state_dir=tmp_path / "claude-config",
        agent_home_environment_variable="CLAUDE_CONFIG_DIR",
    )
    raw_stream = "\n".join([
        _serialise_claude_stream_event({
            "type": "assistant",
            "message": {
                "content": [
                    {"type": "text", "text": "I found the failing test."},
                ],
            },
        }),
        _serialise_claude_stream_event({
            "type": "assistant",
            "message": {
                "content": [
                    {
                        "type": "tool_use",
                        "name": "Bash",
                        "input": {"command": "pytest ralph/tests/test_agent_backends.py"},
                    },
                ],
            },
        }),
        _serialise_claude_stream_event({
            "type": "result",
            "result": "Finished investigating.\n<promise>BLOCKED</promise>",
        }),
    ]) + "\n"
    python_code = f"import sys; sys.stdin.read(); sys.stdout.write({raw_stream!r})"

    completed_process = run_command_and_save_agent_transcripts(
        command=["/workspace/venv/bin/python", "-c", python_code],
        input_text="prompt ignored by this fake agent\n",
        output_path=output_path,
        backend_config=backend_config,
        tee_output=True,
    )

    readable_transcript = "\n".join([
        "I found the failing test.",
        "Tool use: Bash (command: pytest ralph/tests/test_agent_backends.py)",
        "Finished investigating.",
        "<promise>BLOCKED</promise>",
        "",
    ])

    assert completed_process.returncode == 0
    assert completed_process.stdout == raw_stream
    assert raw_output_path.read_text(encoding="utf-8") == raw_stream
    assert output_path.read_text(encoding="utf-8") == readable_transcript
    assert capsys.readouterr().out == readable_transcript


def _serialise_claude_stream_event(event: dict[str, object]) -> str:
    return json.dumps(event)
