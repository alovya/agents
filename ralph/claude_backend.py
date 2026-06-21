from __future__ import annotations

import json
import os
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from ralph.agent_backends import AgentBackend


def build_claude_backend_config(agent_command: str | None) -> "AgentBackend":
    from ralph.agent_backends import AgentBackend, read_default_claude_agent_command
    from ralph.codex_backend import require_agent_state_dir_from_environment_variable

    agent_state_dir = require_agent_state_dir_from_environment_variable("CLAUDE_CONFIG_DIR")
    return AgentBackend(
        backend_name="claude",
        command_name=agent_command or read_default_claude_agent_command(),
        agent_state_dir=agent_state_dir,
        agent_home_environment_variable="CLAUDE_CONFIG_DIR",
    )


def build_claude_command_tail(allowed_bash_commands: list[str]) -> list[str]:
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
    command_tail += build_claude_allowed_tools(allowed_bash_commands)
    command_tail += [
        "--no-session-persistence",
    ]
    return command_tail


def build_claude_allowed_tools(allowed_bash_commands: list[str]) -> list[str]:
    allowed_tools = ["Read", "Glob", "Grep", "Edit", "MultiEdit", "Write"]
    allowed_tools += [
        f"Bash({command})"
        for command in allowed_bash_commands
    ]
    return allowed_tools


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


def _extract_text_from_claude_assistant_event(event: dict[str, Any]) -> str:
    message = event.get("message")
    if not isinstance(message, dict):
        return ""
    content_blocks = message.get("content")
    if not isinstance(content_blocks, list):
        return ""
    return "".join(
        content_block["text"]
        for content_block in content_blocks
        if isinstance(content_block, dict)
        and content_block.get("type") == "text"
        and isinstance(content_block.get("text"), str)
    )
