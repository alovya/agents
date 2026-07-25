from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from ralph.agent_backends import AgentBackend


def build_cursor_agent_backend(agent_command: str | None) -> "AgentBackend":
    from ralph.agent_backends import AgentBackend, DEFAULT_CURSOR_COMMAND
    from ralph.codex_backend import require_agent_config_dir_from_environment_variable

    agent_config_dir = require_agent_config_dir_from_environment_variable("CURSOR_CONFIG_DIR")
    return AgentBackend(
        backend_name="cursor",
        command_name=agent_command or DEFAULT_CURSOR_COMMAND,
        agent_config_dir=agent_config_dir,
        agent_home_environment_variable="CURSOR_CONFIG_DIR",
    )


def build_direct_cursor_command(
    agent_backend: "AgentBackend",
    repo_path: Path,
    model: str | None = None,
) -> list[str]:
    command = [
        agent_backend.command_name,
        "--print",
        "--output-format",
        "stream-json",
        "--force",
        "--workspace",
        str(repo_path),
    ]
    if model:
        command.extend(["--model", model])
    return command


def format_cursor_stream_event_for_human(
    raw_line: str,
    emitted_texts: set[str] | None = None,
) -> list[str]:
    """Format a Cursor stream-json event line for human-readable output.

    Example raw input lines (from `agent --print --output-format stream-json`):

        {"type":"system","subtype":"init","apiKeySource":"login","cwd":"/workspace/agents","session_id":"3ae86715-...","model":"Gemini 3.6 Flash High","permissionMode":"default"}

        {"type":"user","message":{"role":"user","content":[{"type":"text","text":"Say hello"}]},"session_id":"..."}

        {"type":"thinking","subtype":"delta","text":"**Analyzing**\\nI am currently...","session_id":"...","timestamp_ms":1784997722518}

        {"type":"tool_call","subtype":"started","call_id":"0_tool_...","tool_call":{"shellToolCall":{"args":{"command":"git status","workingDirectory":"/workspace/agents",...},"description":"Check git status"},...},"session_id":"..."}

        {"type":"tool_call","subtype":"completed","call_id":"0_tool_...","tool_call":{"shellToolCall":{"result":{"failure":{"exitCode":0,"stdout":"..."},...},...},...},"session_id":"..."}

        {"type":"assistant","message":{"role":"assistant","content":[{"type":"text","text":"Hello! How can I help you today?"}]},"session_id":"..."}

        {"type":"result","subtype":"success","duration_ms":4175,"result":"Hello! How can I help you today?","usage":{"inputTokens":14855,"outputTokens":9,...},...}
    """
    if not raw_line.strip():
        return []

    try:
        event = json.loads(raw_line)
    except json.JSONDecodeError:
        return [f"Malformed Cursor stream-json: {raw_line}"]

    if not isinstance(event, dict):
        return [f"Unexpected Cursor stream-json value: {raw_line}"]

    event_type = event.get("type")
    event_subtype = event.get("subtype")

    if event_type == "system" and event_subtype == "init":
        model = event.get("model", "unknown")
        return [f"Cursor session started with model: {model}"]

    if event_type == "thinking" and event_subtype == "delta":
        text = event.get("text", "")
        if text and emitted_texts is not None:
            if text not in emitted_texts:
                emitted_texts.add(text)
                return _split_transcript_text_into_lines(text.strip())
        return []

    if event_type == "tool_call":
        return _format_cursor_tool_call_event_for_human(event)

    if event_type == "result":
        return _format_cursor_result_event_for_human(event, emitted_texts)

    return []


def extract_cursor_stream_result_text(raw_output: str) -> str:
    result_text: str | None = None
    final_thinking_text: str | None = None
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

        if event.get("type") == "thinking" and event.get("subtype") == "delta":
            text = event.get("text", "")
            if text:
                final_thinking_text = text

    if result_text is not None:
        return result_text
    if final_thinking_text is not None:
        return final_thinking_text
    if malformed_lines:
        raise RuntimeError("Cursor stream-json output contained malformed JSON lines.")
    raise RuntimeError("Cursor stream-json output did not include a result or thinking text event.")


def _format_cursor_tool_call_event_for_human(event: dict[str, Any]) -> list[str]:
    subtype = event.get("subtype")
    tool_call = event.get("tool_call", {})

    tool_type, tool_data = _extract_cursor_tool_call_type_and_data(tool_call)
    if not tool_type:
        return []

    if subtype == "started":
        description = tool_data.get("description", "")
        if tool_type == "shellToolCall":
            command = tool_data.get("args", {}).get("command", "")
            if description:
                return [f"Tool use: Shell ({description})"]
            return [f"Tool use: Shell ({_shorten_cursor_transcript_value(command)})"]
        if tool_type == "readToolCall":
            path = tool_data.get("path", "")
            return [f"Tool use: Read ({path})"]
        if tool_type == "writeToolCall":
            path = tool_data.get("path", "")
            return [f"Tool use: Write ({path})"]
        if tool_type == "editToolCall":
            path = tool_data.get("filePath", "")
            return [f"Tool use: Edit ({path})"]
        return [f"Tool use: {tool_type}"]

    if subtype == "completed":
        result = tool_data.get("result", {})
        if tool_type == "shellToolCall":
            exit_code = result.get("failure", {}).get("exitCode")
            if exit_code is not None and exit_code != 0:
                stderr = result.get("failure", {}).get("stderr", "")
                if stderr:
                    return [f"Tool error (exit {exit_code}): {_shorten_cursor_transcript_value(stderr)}"]
                return [f"Tool error: exit code {exit_code}"]
        return []

    return []


def _extract_cursor_tool_call_type_and_data(tool_call: dict[str, Any]) -> tuple[str | None, dict[str, Any]]:
    for key in ("shellToolCall", "readToolCall", "writeToolCall", "editToolCall", "grepToolCall", "globToolCall"):
        if key in tool_call:
            return key, tool_call[key]
    return None, {}


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
