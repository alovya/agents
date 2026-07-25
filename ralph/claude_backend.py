from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from ralph.agent_backends import AgentBackend


def build_claude_agent_backend(agent_command: str | None) -> "AgentBackend":
    from ralph.agent_backends import AgentBackend, DEFAULT_CLAUDE_COMMAND
    from ralph.codex_backend import require_agent_config_dir_from_environment_variable

    agent_config_dir = require_agent_config_dir_from_environment_variable("CLAUDE_CONFIG_DIR")
    return AgentBackend(
        backend_name="claude",
        command_name=agent_command or DEFAULT_CLAUDE_COMMAND,
        agent_config_dir=agent_config_dir,
        agent_home_environment_variable="CLAUDE_CONFIG_DIR",
    )


def build_direct_claude_command(
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
        *_build_direct_claude_allowed_tools(),
        "--no-session-persistence",
        "-p",
        str(repo_path),
    ]


def _build_direct_claude_allowed_tools() -> list[str]:
    return ["Read", "Glob", "Grep", "Edit", "MultiEdit", "Write", "Bash"]


def format_claude_stream_event_for_human(
    raw_line: str,
    emitted_texts: set[str] | None = None,
) -> list[str]:
    """Format a Claude stream-json event line for human-readable output.

    Example raw input lines (from `claude --print --verbose --output-format stream-json`):

        {"type":"system","subtype":"init","cwd":"/workspace/agents","session_id":"7c57107f-...","model":"claude-opus-4-5","permissionMode":"default",...}

        {"type":"assistant","message":{"model":"claude-opus-4-5-20251101","role":"assistant","content":[{"type":"thinking","thinking":"The user just wants..."},{"type":"text","text":"Hello!"}],"stop_reason":null,...},"session_id":"..."}

        {"type":"user","message":{"role":"user","content":[{"type":"tool_result","tool_use_id":"toolu_01...","content":"1\\tfrom __future__..."}]},"session_id":"..."}

        {"type":"result","subtype":"success","result":"Hello! How can I help you today?","duration_ms":2413,"usage":{...},...}
    """
    if not raw_line.strip():
        return []

    try:
        event = json.loads(raw_line)
    except json.JSONDecodeError:
        return [f"Malformed Claude stream-json: {raw_line}"]

    if not isinstance(event, dict):
        return [f"Unexpected Claude stream-json value: {raw_line}"]

    event_type = event.get("type")
    if event_type == "assistant":
        return _format_claude_assistant_event_for_human(event)
    if event_type == "user":
        return _format_claude_user_event_for_human(event)
    if event_type == "result":
        return _format_claude_result_event_for_human(event, emitted_texts)
    return _format_noisy_claude_event_for_human_when_it_contains_an_error(event)


def extract_claude_stream_result_text(raw_output: str) -> str:
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
            assistant_text = _extract_text_from_claude_assistant_event(event)
            if assistant_text:
                final_assistant_text = assistant_text

    if result_text is not None:
        return result_text
    if final_assistant_text is not None:
        return final_assistant_text
    if malformed_lines:
        raise RuntimeError("Claude stream-json output contained malformed JSON lines.")
    raise RuntimeError("Claude stream-json output did not include a result or assistant text event.")


def _format_claude_assistant_event_for_human(event: dict[str, Any]) -> list[str]:
    transcript_lines: list[str] = []
    for content_block in _extract_claude_content_blocks(event):
        if content_block.get("type") == "text" and isinstance(content_block.get("text"), str):
            transcript_lines.extend(_split_transcript_text_into_lines(content_block["text"]))
        if content_block.get("type") == "tool_use":
            transcript_lines.append(_format_claude_tool_use_block_for_human(content_block))
    return transcript_lines


def _format_claude_user_event_for_human(event: dict[str, Any]) -> list[str]:
    transcript_lines: list[str] = []
    for content_block in _extract_claude_content_blocks(event):
        if content_block.get("type") == "tool_result":
            transcript_lines.extend(_format_claude_tool_result_block_for_human(content_block))
    return transcript_lines


def _format_claude_result_event_for_human(
    event: dict[str, Any],
    emitted_texts: set[str] | None,
) -> list[str]:
    result_text = event.get("result")
    if not isinstance(result_text, str) or not result_text:
        return _format_noisy_claude_event_for_human_when_it_contains_an_error(event)
    if emitted_texts is not None and result_text in emitted_texts:
        return []
    return _split_transcript_text_into_lines(result_text)


def _format_noisy_claude_event_for_human_when_it_contains_an_error(event: dict[str, Any]) -> list[str]:
    error_text = _extract_claude_error_text(event)
    if not error_text:
        return []
    return _split_transcript_text_into_lines(f"Claude stream error: {error_text}")


def _extract_text_from_claude_assistant_event(event: dict[str, Any]) -> str:
    return "".join(
        content_block["text"]
        for content_block in _extract_claude_content_blocks(event)
        if content_block.get("type") == "text"
        and isinstance(content_block.get("text"), str)
    )


def _extract_claude_content_blocks(event: dict[str, Any]) -> list[dict[str, Any]]:
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


def _format_claude_tool_use_block_for_human(content_block: dict[str, Any]) -> str:
    tool_name = content_block.get("name")
    if not isinstance(tool_name, str) or not tool_name:
        tool_name = "unknown tool"

    useful_input_parts = _format_useful_claude_tool_input_parts(content_block.get("input"))
    if not useful_input_parts:
        return f"Tool use: {tool_name}"
    return f"Tool use: {tool_name} ({', '.join(useful_input_parts)})"


def _format_useful_claude_tool_input_parts(tool_input: Any) -> list[str]:
    if not isinstance(tool_input, dict):
        return []

    useful_input_parts: list[str] = []
    for key in ("command", "description", "file_path", "path", "pattern", "url"):
        value = tool_input.get(key)
        if isinstance(value, str) and value:
            useful_input_parts.append(f"{key}: {_shorten_claude_transcript_value(value)}")
    return useful_input_parts


def _format_claude_tool_result_block_for_human(content_block: dict[str, Any]) -> list[str]:
    result_text = _extract_claude_tool_result_text(content_block)
    if not result_text:
        return []

    prefix = "Tool error" if content_block.get("is_error") is True else "Tool result"
    result_lines = _split_transcript_text_into_lines(result_text)
    if len(result_lines) == 1:
        return [f"{prefix}: {result_lines[0]}"]
    return [f"{prefix}:"] + result_lines


def _extract_claude_tool_result_text(content_block: dict[str, Any]) -> str:
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


def _extract_claude_error_text(event: dict[str, Any]) -> str:
    for key in ("error", "message", "stderr"):
        value = event.get(key)
        if isinstance(value, str) and value:
            return value
        if isinstance(value, dict) and isinstance(value.get("message"), str):
            return value["message"]
    return ""


def _split_transcript_text_into_lines(text: str) -> list[str]:
    return [line for line in text.splitlines() if line]


def _shorten_claude_transcript_value(value: str, max_length: int = 160) -> str:
    single_line_value = " ".join(value.splitlines())
    if len(single_line_value) <= max_length:
        return single_line_value
    return f"{single_line_value[:max_length - 3]}..."
