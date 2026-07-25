from __future__ import annotations

import json
import os
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from ralph.agent_backends import AgentBackend


def build_codex_agent_backend(agent_command: str | None) -> "AgentBackend":
    from ralph.agent_backends import AgentBackend, read_default_codex_agent_command

    agent_config_dir = require_agent_config_dir_from_environment_variable("CODEX_HOME")
    return AgentBackend(
        backend_name="codex",
        command_name=agent_command or read_default_codex_agent_command(),
        agent_config_dir=agent_config_dir,
        agent_home_environment_variable="CODEX_HOME",
    )


def build_direct_codex_command(
    agent_backend: "AgentBackend",
    repo_path: Path,
    tool_virtual_environment_path: Path,
    controller_path: str,
) -> list[str]:
    return [
        agent_backend.command_name,
        "--config",
        f"shell_environment_policy.set.PATH={json.dumps(controller_path)}",
        "--config",
        (
            "shell_environment_policy.set.VIRTUAL_ENV="
            f"{json.dumps(str(tool_virtual_environment_path))}"
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


def extract_codex_stream_result_text(raw_output: str) -> str:
    final_agent_message: str | None = None
    malformed_lines: list[str] = []
    for line in raw_output.splitlines():
        if not line.strip():
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            malformed_lines.append(line)
            continue

        agent_message = _extract_completed_codex_agent_message(event)
        if agent_message:
            final_agent_message = agent_message

    if final_agent_message is not None:
        return final_agent_message
    if malformed_lines:
        raise RuntimeError("Codex JSON Lines output contained malformed JSON lines.")
    raise RuntimeError("Codex JSON Lines output did not include a completed agent message.")


def format_codex_stream_event_for_human(raw_line: str) -> list[str]:
    """Format a Codex stream-json event line for human-readable output.

    Example raw input lines (from `codex exec --json`):

        {"type":"thread.started","thread_id":"019f9a54-49e9-7653-90b4-9948dd726128"}

        {"type":"turn.started"}

        {"type":"item.completed","item":{"id":"item_0","type":"agent_message","text":"Hello!"}}

        {"type":"turn.completed","usage":{"input_tokens":19038,"cached_input_tokens":11008,"output_tokens":6,...}}
    """
    try:
        event = json.loads(raw_line)
    except json.JSONDecodeError:
        return ["Codex stream error: malformed JSON line"]

    agent_message = _extract_completed_codex_agent_message(event)
    if agent_message:
        return _split_codex_transcript_text_into_lines(agent_message)

    error_text = _extract_codex_error_text(event)
    if error_text:
        return _split_codex_transcript_text_into_lines(f"Codex stream error: {error_text}")
    return []


def _extract_completed_codex_agent_message(event: dict[str, Any]) -> str:
    if event.get("type") != "item.completed":
        return ""
    item = event.get("item")
    if not isinstance(item, dict) or item.get("type") != "agent_message":
        return ""
    text = item.get("text")
    return text if isinstance(text, str) else ""


def _extract_codex_error_text(event: dict[str, Any]) -> str:
    if event.get("type") not in {"error", "turn.failed"}:
        return ""
    for key in ("message", "error"):
        value = event.get(key)
        if isinstance(value, str) and value:
            return value
        if isinstance(value, dict) and isinstance(value.get("message"), str):
            return value["message"]
    return ""


def _split_codex_transcript_text_into_lines(text: str) -> list[str]:
    return [line for line in text.splitlines() if line]


def require_codex_home_path() -> Path:
    return require_agent_config_dir_from_environment_variable("CODEX_HOME")


def require_agent_config_dir_from_environment_variable(variable_name: str) -> Path:
    configured_path = os.environ.get(variable_name)
    if not configured_path:
        raise RuntimeError(f"{variable_name} must be set before running Ralph agents.")

    agent_config_dir = Path(configured_path).expanduser().resolve()
    if not agent_config_dir.is_dir():
        raise RuntimeError(f"{variable_name} does not exist: {agent_config_dir}")
    return agent_config_dir
