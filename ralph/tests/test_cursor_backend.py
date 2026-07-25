from __future__ import annotations

import json
from pathlib import Path

from ralph.agent_backends import AgentBackend
from ralph.cursor_backend import (
    CURSOR_WORKER_CONFIG_SEED_FILENAMES,
    extract_cursor_stream_result_text,
    format_cursor_stream_event_for_human,
    prepare_cursor_worker_home,
)


def test_prepare_cursor_worker_home_seeds_config_files_and_skills(tmp_path: Path) -> None:
    master_cursor_config_dir = tmp_path / "master-cursor-config"
    external_skill_path = tmp_path / "external-ralph-skill"
    master_cursor_config_dir.mkdir()
    external_skill_path.mkdir()
    _write_cursor_seed_files(master_cursor_config_dir)
    (master_cursor_config_dir / ".cursor.json").write_text("noisy local state", encoding="utf-8")
    (master_cursor_config_dir / "history.jsonl").write_text("history", encoding="utf-8")
    (master_cursor_config_dir / "projects").mkdir()
    (master_cursor_config_dir / "sessions").mkdir()
    (master_cursor_config_dir / "skills").mkdir()
    (master_cursor_config_dir / "skills" / "ralph").symlink_to(external_skill_path)
    (master_cursor_config_dir / "skills" / "missing").symlink_to(tmp_path / "missing-skill")
    (external_skill_path / "SKILL.md").write_text("Ralph skill", encoding="utf-8")
    master_agent_backend = AgentBackend(
        backend_name="cursor",
        command_name="cursor",
        agent_config_dir=master_cursor_config_dir,
        agent_home_environment_variable="CURSOR_CONFIG_DIR",
    )

    with prepare_cursor_worker_home(master_agent_backend) as worker_agent_backend:
        worker_cursor_config_dir = worker_agent_backend.agent_config_dir
        worker_skill_path = worker_cursor_config_dir / "skills" / "ralph"

        assert worker_agent_backend.backend_name == "cursor"
        assert worker_agent_backend.command_name == "cursor"
        assert worker_agent_backend.agent_home_environment_variable == "CURSOR_CONFIG_DIR"
        assert worker_cursor_config_dir != master_cursor_config_dir
        assert _read_cursor_seed_files(worker_cursor_config_dir) == _read_cursor_seed_files(
            master_cursor_config_dir
        )
        assert worker_skill_path.is_dir()
        assert not worker_skill_path.is_symlink()
        assert (worker_skill_path / "SKILL.md").read_text(encoding="utf-8") == "Ralph skill"
        assert not (worker_cursor_config_dir / "skills" / "missing").exists()
        assert not (worker_cursor_config_dir / ".cursor.json").exists()
        assert not (worker_cursor_config_dir / "history.jsonl").exists()
        assert not (worker_cursor_config_dir / "projects").exists()
        assert not (worker_cursor_config_dir / "sessions").exists()

    assert not worker_cursor_config_dir.exists()


def test_format_cursor_stream_event_for_human_emits_assistant_text_as_plain_lines() -> None:
    cursor_says_what_the_worker_is_doing = _serialise_cursor_event({
        "type": "assistant",
        "message": {
            "content": [
                {"type": "text", "text": "I found the failing test.\nI am patching it now."},
            ],
        },
    })

    assert format_cursor_stream_event_for_human(cursor_says_what_the_worker_is_doing) == [
        "I found the failing test.",
        "I am patching it now.",
    ]


def test_format_cursor_stream_event_for_human_summarises_tool_use_without_dumping_json() -> None:
    cursor_announces_a_bash_command = _serialise_cursor_event({
        "type": "assistant",
        "message": {
            "content": [
                {
                    "type": "tool_use",
                    "name": "Bash",
                    "input": {
                        "command": "rg format_cursor_stream_event_for_human ralph",
                        "description": "Find the formatter call sites",
                        "irrelevant_large_payload": {"this": "should not be dumped"},
                    },
                },
            ],
        },
    })

    assert format_cursor_stream_event_for_human(cursor_announces_a_bash_command) == [
        (
            "Tool use: Bash "
            "(command: rg format_cursor_stream_event_for_human ralph, "
            "description: Find the formatter call sites)"
        ),
    ]


def test_format_cursor_stream_event_for_human_emits_tool_result_output() -> None:
    cursor_receives_command_output = _serialise_cursor_event({
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

    assert format_cursor_stream_event_for_human(cursor_receives_command_output) == [
        "Tool result:",
        "collected 2 items",
        "2 passed",
    ]


def test_format_cursor_stream_event_for_human_emits_tool_result_errors() -> None:
    cursor_receives_command_error = _serialise_cursor_event({
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

    assert format_cursor_stream_event_for_human(cursor_receives_command_error) == [
        "Tool error: pytest failed",
    ]


def test_format_cursor_stream_event_for_human_emits_result_text_when_it_is_new() -> None:
    cursor_finishes_with_a_final_answer = _serialise_cursor_event({
        "type": "result",
        "result": "Implemented formatter\n<promise>DONE</promise>",
    })

    assert format_cursor_stream_event_for_human(cursor_finishes_with_a_final_answer) == [
        "Implemented formatter",
        "<promise>DONE</promise>",
    ]


def test_format_cursor_stream_event_for_human_suppresses_result_text_already_seen() -> None:
    cursor_repeats_the_final_assistant_answer = _serialise_cursor_event({
        "type": "result",
        "result": "Implemented formatter\n<promise>DONE</promise>",
    })

    assert format_cursor_stream_event_for_human(
        cursor_repeats_the_final_assistant_answer,
        emitted_texts={"Implemented formatter\n<promise>DONE</promise>"},
    ) == []


def test_format_cursor_stream_event_for_human_suppresses_noisy_partial_and_hook_events() -> None:
    cursor_reports_partial_stream_bookkeeping = _serialise_cursor_event({
        "type": "content_block_delta",
        "delta": {"type": "text_delta", "text": "noisy partial text"},
    })
    cursor_reports_successful_hook_bookkeeping = _serialise_cursor_event({
        "type": "hook",
        "hook_event_name": "PreToolUse",
    })

    assert format_cursor_stream_event_for_human(cursor_reports_partial_stream_bookkeeping) == []
    assert format_cursor_stream_event_for_human(cursor_reports_successful_hook_bookkeeping) == []


def test_format_cursor_stream_event_for_human_preserves_useful_errors_from_noisy_events() -> None:
    cursor_reports_a_hook_error = _serialise_cursor_event({
        "type": "hook",
        "hook_event_name": "PreToolUse",
        "error": {"message": "permission hook failed"},
    })

    assert format_cursor_stream_event_for_human(cursor_reports_a_hook_error) == [
        "Cursor stream error: permission hook failed",
    ]


def test_format_cursor_stream_event_for_human_preserves_malformed_json() -> None:
    assert format_cursor_stream_event_for_human("this is not json") == [
        "Malformed Cursor stream-json: this is not json",
    ]


def test_extract_cursor_stream_result_text_prefers_result_event() -> None:
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

    assert extract_cursor_stream_result_text(raw_output) == "final answer\n<promise>BLOCKED</promise>"


def test_extract_cursor_stream_result_text_falls_back_to_final_assistant_event() -> None:
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

    assert extract_cursor_stream_result_text(raw_output) == "final answer"


def _serialise_cursor_event(event: dict[str, object]) -> str:
    return json.dumps(event)


def _write_cursor_seed_files(cursor_config_dir: Path) -> None:
    for seed_filename in CURSOR_WORKER_CONFIG_SEED_FILENAMES:
        (cursor_config_dir / seed_filename).write_text(f"{seed_filename} content", encoding="utf-8")


def _read_cursor_seed_files(cursor_config_dir: Path) -> dict[str, str]:
    return {
        seed_filename: (cursor_config_dir / seed_filename).read_text(encoding="utf-8")
        for seed_filename in CURSOR_WORKER_CONFIG_SEED_FILENAMES
    }
