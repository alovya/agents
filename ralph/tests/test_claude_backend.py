from __future__ import annotations

import json
from pathlib import Path

from ralph.agent_backends import AgentBackend
from ralph.claude_backend import (
    CLAUDE_WORKER_CONFIG_SEED_FILENAMES,
    extract_claude_stream_result_text,
    format_claude_stream_event_for_human,
    prepare_claude_worker_home,
)


def test_prepare_claude_worker_home_seeds_config_files_and_skills(tmp_path: Path) -> None:
    master_claude_config_dir = tmp_path / "master-claude-config"
    external_skill_path = tmp_path / "external-ralph-skill"
    master_claude_config_dir.mkdir()
    external_skill_path.mkdir()
    _write_claude_seed_files(master_claude_config_dir)
    (master_claude_config_dir / ".claude.json").write_text("noisy local state", encoding="utf-8")
    (master_claude_config_dir / "history.jsonl").write_text("history", encoding="utf-8")
    (master_claude_config_dir / "projects").mkdir()
    (master_claude_config_dir / "sessions").mkdir()
    (master_claude_config_dir / "skills").mkdir()
    (master_claude_config_dir / "skills" / "ralph").symlink_to(external_skill_path)
    (external_skill_path / "SKILL.md").write_text("Ralph skill", encoding="utf-8")
    master_agent_backend = AgentBackend(
        backend_name="claude",
        command_name="claude",
        agent_config_dir=master_claude_config_dir,
        agent_home_environment_variable="CLAUDE_CONFIG_DIR",
    )

    with prepare_claude_worker_home(master_agent_backend) as worker_agent_backend:
        worker_claude_config_dir = worker_agent_backend.agent_config_dir
        worker_skill_path = worker_claude_config_dir / "skills" / "ralph"

        assert worker_agent_backend.backend_name == "claude"
        assert worker_agent_backend.command_name == "claude"
        assert worker_agent_backend.agent_home_environment_variable == "CLAUDE_CONFIG_DIR"
        assert worker_claude_config_dir != master_claude_config_dir
        assert _read_claude_seed_files(worker_claude_config_dir) == _read_claude_seed_files(
            master_claude_config_dir
        )
        assert worker_skill_path.is_dir()
        assert not worker_skill_path.is_symlink()
        assert (worker_skill_path / "SKILL.md").read_text(encoding="utf-8") == "Ralph skill"
        assert not (worker_claude_config_dir / ".claude.json").exists()
        assert not (worker_claude_config_dir / "history.jsonl").exists()
        assert not (worker_claude_config_dir / "projects").exists()
        assert not (worker_claude_config_dir / "sessions").exists()

    assert not worker_claude_config_dir.exists()


def test_format_claude_stream_event_for_human_emits_assistant_text_as_plain_lines() -> None:
    claude_says_what_the_worker_is_doing = _serialise_claude_event({
        "type": "assistant",
        "message": {
            "content": [
                {"type": "text", "text": "I found the failing test.\nI am patching it now."},
            ],
        },
    })

    assert format_claude_stream_event_for_human(claude_says_what_the_worker_is_doing) == [
        "I found the failing test.",
        "I am patching it now.",
    ]


def test_format_claude_stream_event_for_human_summarises_tool_use_without_dumping_json() -> None:
    claude_announces_a_bash_command = _serialise_claude_event({
        "type": "assistant",
        "message": {
            "content": [
                {
                    "type": "tool_use",
                    "name": "Bash",
                    "input": {
                        "command": "rg format_claude_stream_event_for_human ralph",
                        "description": "Find the formatter call sites",
                        "irrelevant_large_payload": {"this": "should not be dumped"},
                    },
                },
            ],
        },
    })

    assert format_claude_stream_event_for_human(claude_announces_a_bash_command) == [
        (
            "Tool use: Bash "
            "(command: rg format_claude_stream_event_for_human ralph, "
            "description: Find the formatter call sites)"
        ),
    ]


def test_format_claude_stream_event_for_human_emits_tool_result_output() -> None:
    claude_receives_command_output = _serialise_claude_event({
        "type": "user",
        "message": {
            "content": [
                {
                    "type": "tool_result",
                    "content": "collected 2 items\n2 passed",
                    "is_error": False,
                },
            ],
        },
    })

    assert format_claude_stream_event_for_human(claude_receives_command_output) == [
        "Tool result:",
        "collected 2 items",
        "2 passed",
    ]


def test_format_claude_stream_event_for_human_emits_tool_result_errors() -> None:
    claude_receives_command_error = _serialise_claude_event({
        "type": "user",
        "message": {
            "content": [
                {
                    "type": "tool_result",
                    "content": [{"type": "text", "text": "pytest failed"}],
                    "is_error": True,
                },
            ],
        },
    })

    assert format_claude_stream_event_for_human(claude_receives_command_error) == [
        "Tool error: pytest failed",
    ]


def test_format_claude_stream_event_for_human_emits_result_text_when_it_is_new() -> None:
    claude_finishes_with_a_final_answer = _serialise_claude_event({
        "type": "result",
        "result": "Implemented formatter\n<promise>DONE</promise>",
    })

    assert format_claude_stream_event_for_human(claude_finishes_with_a_final_answer) == [
        "Implemented formatter",
        "<promise>DONE</promise>",
    ]


def test_format_claude_stream_event_for_human_suppresses_result_text_already_seen() -> None:
    claude_repeats_the_final_assistant_answer = _serialise_claude_event({
        "type": "result",
        "result": "Implemented formatter\n<promise>DONE</promise>",
    })

    assert format_claude_stream_event_for_human(
        claude_repeats_the_final_assistant_answer,
        emitted_texts={"Implemented formatter\n<promise>DONE</promise>"},
    ) == []


def test_format_claude_stream_event_for_human_suppresses_noisy_partial_and_hook_events() -> None:
    claude_reports_partial_stream_bookkeeping = _serialise_claude_event({
        "type": "content_block_delta",
        "delta": {"type": "text_delta", "text": "noisy partial text"},
    })
    claude_reports_successful_hook_bookkeeping = _serialise_claude_event({
        "type": "hook",
        "hook_event_name": "PreToolUse",
    })

    assert format_claude_stream_event_for_human(claude_reports_partial_stream_bookkeeping) == []
    assert format_claude_stream_event_for_human(claude_reports_successful_hook_bookkeeping) == []


def test_format_claude_stream_event_for_human_preserves_useful_errors_from_noisy_events() -> None:
    claude_reports_a_hook_error = _serialise_claude_event({
        "type": "hook",
        "hook_event_name": "PreToolUse",
        "error": {"message": "permission hook failed"},
    })

    assert format_claude_stream_event_for_human(claude_reports_a_hook_error) == [
        "Claude stream error: permission hook failed",
    ]


def test_format_claude_stream_event_for_human_preserves_malformed_json() -> None:
    assert format_claude_stream_event_for_human("this is not json") == [
        "Malformed Claude stream-json: this is not json",
    ]


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

    assert extract_claude_stream_result_text(raw_output) == "final answer\n<promise>BLOCKED</promise>"


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

    assert extract_claude_stream_result_text(raw_output) == "final answer"


def _serialise_claude_event(event: dict[str, object]) -> str:
    return json.dumps(event)


def _write_claude_seed_files(claude_config_dir: Path) -> None:
    for seed_filename in CLAUDE_WORKER_CONFIG_SEED_FILENAMES:
        (claude_config_dir / seed_filename).write_text(f"{seed_filename} content", encoding="utf-8")


def _read_claude_seed_files(claude_config_dir: Path) -> dict[str, str]:
    return {
        seed_filename: (claude_config_dir / seed_filename).read_text(encoding="utf-8")
        for seed_filename in CLAUDE_WORKER_CONFIG_SEED_FILENAMES
    }
