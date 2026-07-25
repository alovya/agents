from __future__ import annotations

import contextlib
import json
import os
import shutil
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING, Any, Iterator

if TYPE_CHECKING:
    from ralph.agent_backends import AgentBackend


CURSOR_WORKER_CONFIG_SEED_FILENAMES = (
    ".credentials.json",
    "settings.json",
    "config.json",
    "AGENTS.md",
)


def build_cursor_agent_backend(agent_command: str | None) -> "AgentBackend":
    from ralph.agent_backends import AgentBackend, read_default_cursor_agent_command
    from ralph.codex_backend import require_agent_config_dir_from_environment_variable

    agent_config_dir = require_agent_config_dir_from_environment_variable("CURSOR_CONFIG_DIR")
    return AgentBackend(
        backend_name="cursor",
        command_name=agent_command or read_default_cursor_agent_command(),
        agent_config_dir=agent_config_dir,
        agent_home_environment_variable="CURSOR_CONFIG_DIR",
    )


@contextlib.contextmanager
def prepare_cursor_worker_home(master_agent_backend: "AgentBackend") -> Iterator["AgentBackend"]:
    from ralph.agent_backends import AgentBackend

    master_cursor_config_dir = master_agent_backend.agent_config_dir
    with tempfile.TemporaryDirectory(prefix="ralph-cursor-home-") as worker_home_dir:
        worker_cursor_config_dir = Path(worker_home_dir).resolve()
        _copy_cursor_worker_seed_files(
            master_cursor_config_dir=master_cursor_config_dir,
            worker_cursor_config_dir=worker_cursor_config_dir,
        )
        _copy_cursor_worker_skills(
            master_cursor_config_dir=master_cursor_config_dir,
            worker_cursor_config_dir=worker_cursor_config_dir,
        )
        yield AgentBackend(
            backend_name=master_agent_backend.backend_name,
            command_name=master_agent_backend.command_name,
            agent_config_dir=worker_cursor_config_dir,
            agent_home_environment_variable=master_agent_backend.agent_home_environment_variable,
        )


def build_cursor_command_tail(allowed_bash_commands: list[str]) -> list[str]:
    command_tail = [
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
    ]
    command_tail += build_cursor_allowed_tools(allowed_bash_commands)
    command_tail += [
        "--no-session-persistence",
    ]
    return command_tail


def build_direct_cursor_command(
    agent_backend: "AgentBackend",
    repo_path: Path,
) -> list[str]:
    return [
        agent_backend.command_name,
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
        *_build_direct_cursor_allowed_tools(),
        "--no-session-persistence",
        "-p",
        str(repo_path),
    ]


def _build_direct_cursor_allowed_tools() -> list[str]:
    return ["Read", "Glob", "Grep", "Edit", "MultiEdit", "Write", "Bash"]


def _copy_cursor_worker_seed_files(master_cursor_config_dir: Path, worker_cursor_config_dir: Path) -> None:
    for seed_filename in CURSOR_WORKER_CONFIG_SEED_FILENAMES:
        master_seed_path = master_cursor_config_dir / seed_filename
        worker_seed_path = worker_cursor_config_dir / seed_filename
        if master_seed_path.is_file():
            shutil.copy2(master_seed_path, worker_seed_path)


def _copy_cursor_worker_skills(master_cursor_config_dir: Path, worker_cursor_config_dir: Path) -> None:
    master_skills_path = master_cursor_config_dir / "skills"
    worker_skills_path = worker_cursor_config_dir / "skills"
    if master_skills_path.is_dir():
        shutil.copytree(master_skills_path, worker_skills_path, symlinks=False, ignore_dangling_symlinks=True)


def build_cursor_allowed_tools(allowed_bash_commands: list[str]) -> list[str]:
    allowed_tools = ["Read", "Glob", "Grep", "Edit", "MultiEdit", "Write", "Bash"]
    allowed_tools += [
        f"Bash({command})"
        for command in allowed_bash_commands
    ]
    return allowed_tools


def format_cursor_stream_event_for_human(
    raw_line: str,
    emitted_texts: set[str] | None = None,
) -> list[str]:
    if not raw_line.strip():
        return []

    try:
        event = json.loads(raw_line)
    except json.JSONDecodeError:
        return [f"Malformed Cursor stream-json: {raw_line}"]

    if not isinstance(event, dict):
        return [f"Unexpected Cursor stream-json value: {raw_line}"]

    event_type = event.get("type")
    if event_type == "assistant":
        return _format_cursor_assistant_event_for_human(event)
    if event_type == "user":
        return _format_cursor_user_event_for_human(event)
    if event_type == "result":
        return _format_cursor_result_event_for_human(event, emitted_texts)
    return _format_noisy_cursor_event_for_human_when_it_contains_an_error(event)


def extract_cursor_stream_result_text(raw_output: str) -> str:
    result_text: str | None = None
    final_assistant_text: str | None = None
    malformed_lines: list[str] = []
    for line in raw_output.splitlines():
        if not line.strip():
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            malformed_lines.append(line)
            continue

        if event.get("type") == "result" and isinstance(event.get("result"), str):
            result_text = event["result"]
        if event.get("type") == "assistant":
            assistant_text = _extract_text_from_cursor_assistant_event(event)
            if assistant_text:
                final_assistant_text = assistant_text

    if result_text is not None:
        return result_text
    if final_assistant_text is not None:
        return final_assistant_text
    if malformed_lines:
        raise RuntimeError("Cursor stream-json output contained malformed JSON lines.")
    raise RuntimeError("Cursor stream-json output did not include a result or assistant text event.")


def _format_cursor_assistant_event_for_human(event: dict[str, Any]) -> list[str]:
    transcript_lines: list[str] = []
    for content_block in _extract_cursor_content_blocks(event):
        if content_block.get("type") == "text" and isinstance(content_block.get("text"), str):
            transcript_lines.extend(_split_transcript_text_into_lines(content_block["text"]))
        if content_block.get("type") == "tool_use":
            transcript_lines.append(_format_cursor_tool_use_block_for_human(content_block))
    return transcript_lines


def _format_cursor_user_event_for_human(event: dict[str, Any]) -> list[str]:
    transcript_lines: list[str] = []
    for content_block in _extract_cursor_content_blocks(event):
        if content_block.get("type") == "tool_result":
            transcript_lines.extend(_format_cursor_tool_result_block_for_human(content_block))
    return transcript_lines


def _format_cursor_result_event_for_human(
    event: dict[str, Any],
    emitted_texts: set[str] | None,
) -> list[str]:
    result_text = event.get("result")
    if not isinstance(result_text, str) or not result_text:
        return _format_noisy_cursor_event_for_human_when_it_contains_an_error(event)
    if emitted_texts is not None and result_text in emitted_texts:
        return []
    return _split_transcript_text_into_lines(result_text)


def _format_noisy_cursor_event_for_human_when_it_contains_an_error(event: dict[str, Any]) -> list[str]:
    error_text = _extract_cursor_error_text(event)
    if not error_text:
        return []
    return _split_transcript_text_into_lines(f"Cursor stream error: {error_text}")


def _extract_text_from_cursor_assistant_event(event: dict[str, Any]) -> str:
    return "".join(
        content_block["text"]
        for content_block in _extract_cursor_content_blocks(event)
        if content_block.get("type") == "text"
        and isinstance(content_block.get("text"), str)
    )


def _extract_cursor_content_blocks(event: dict[str, Any]) -> list[dict[str, Any]]:
    message = event.get("message")
    if isinstance(message, dict):
        content_blocks = message.get("content")
    else:
        content_blocks = event.get("content")
    if not isinstance(content_blocks, list):
        return []
    return [
        content_block
        for content_block in content_blocks
        if isinstance(content_block, dict)
    ]


def _format_cursor_tool_use_block_for_human(content_block: dict[str, Any]) -> str:
    tool_name = content_block.get("name")
    if not isinstance(tool_name, str) or not tool_name:
        tool_name = "unknown tool"

    useful_input_parts = _format_useful_cursor_tool_input_parts(content_block.get("input"))
    if not useful_input_parts:
        return f"Tool use: {tool_name}"
    return f"Tool use: {tool_name} ({', '.join(useful_input_parts)})"


def _format_useful_cursor_tool_input_parts(tool_input: Any) -> list[str]:
    if not isinstance(tool_input, dict):
        return []

    useful_input_parts: list[str] = []
    for key in ("command", "description", "file_path", "path", "pattern", "url"):
        value = tool_input.get(key)
        if isinstance(value, str) and value:
            useful_input_parts.append(f"{key}: {_shorten_cursor_transcript_value(value)}")
    return useful_input_parts


def _format_cursor_tool_result_block_for_human(content_block: dict[str, Any]) -> list[str]:
    result_text = _extract_cursor_tool_result_text(content_block)
    if not result_text:
        return []

    prefix = "Tool error" if content_block.get("is_error") is True else "Tool result"
    result_lines = _split_transcript_text_into_lines(result_text)
    if len(result_lines) == 1:
        return [f"{prefix}: {result_lines[0]}"]
    return [f"{prefix}:"] + result_lines


def _extract_cursor_tool_result_text(content_block: dict[str, Any]) -> str:
    content = content_block.get("content")
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return ""

    text_parts: list[str] = []
    for nested_content_block in content:
        if (
            isinstance(nested_content_block, dict)
            and nested_content_block.get("type") == "text"
            and isinstance(nested_content_block.get("text"), str)
        ):
            text_parts.append(nested_content_block["text"])
    return "\n".join(text_parts)


def _extract_cursor_error_text(event: dict[str, Any]) -> str:
    for key in ("error", "message", "stderr"):
        value = event.get(key)
        if isinstance(value, str) and value:
            return value
        if isinstance(value, dict) and isinstance(value.get("message"), str):
            return value["message"]
    return ""


def _split_transcript_text_into_lines(text: str) -> list[str]:
    return [line for line in text.splitlines() if line]


def _shorten_cursor_transcript_value(value: str, max_length: int = 160) -> str:
    single_line_value = " ".join(value.splitlines())
    if len(single_line_value) <= max_length:
        return single_line_value
    return f"{single_line_value[:max_length - 3]}..."
