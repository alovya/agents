from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ralph.claude_backend import (
    build_claude_backend_config,
    build_claude_command_tail,
    extract_claude_stream_result_text,
)
from ralph.codex_backend import (
    build_codex_backend_config,
    build_codex_command_tail,
)


@dataclass(frozen=True)
class AgentResult:
    promise: str
    output: str


@dataclass(frozen=True)
class AgentBackend:
    backend_name: str
    command_name: str
    agent_state_dir: Path
    agent_home_environment_variable: str


ALWAYS_ALLOWED_WORKER_BASH_COMMANDS = [
    "git status",
    "git status --short",
    "git diff",
    "git diff --staged",
    "git ls-files",
    "git add .",
    "git commit --no-verify -m *",
    "git rev-parse HEAD",
]


def select_agent_backend_config(
    agent_backend: str,
    agent_command: str | None,
) -> AgentBackend:
    if agent_backend == "codex":
        return build_codex_backend_config(agent_command)
    if agent_backend == "claude":
        return build_claude_backend_config(agent_command)
    raise ValueError(f"Unsupported agent backend: {agent_backend}")


def build_agent_command_tail(
    backend_config: AgentBackend,
    repo_path: Path,
    allowed_bash_commands: list[str],
) -> list[str]:
    if backend_config.backend_name == "codex":
        return build_codex_command_tail(repo_path)
    if backend_config.backend_name == "claude":
        return build_claude_command_tail(allowed_bash_commands)
    raise ValueError(f"Unsupported agent backend: {backend_config.backend_name}")


def extract_agent_result_text(backend_config: AgentBackend, raw_output: str) -> str:
    if backend_config.backend_name != "claude":
        return raw_output
    return extract_claude_stream_result_text(raw_output)


def build_worker_allowed_bash_commands(task: dict[str, Any]) -> list[str]:
    allowed_commands = list(ALWAYS_ALLOWED_WORKER_BASH_COMMANDS)
    allowed_commands += list(task.get("allowed_bash_commands") or [])
    allowed_commands += list(task.get("verification_commands") or [])
    return list(dict.fromkeys(allowed_commands))


def read_default_codex_agent_command() -> str:
    return os.environ.get("RALPH_AGENT_COMMAND", os.environ.get("RALPH_CODEX_COMMAND", "codex"))


def read_default_claude_agent_command() -> str:
    return os.environ.get("RALPH_AGENT_COMMAND", os.environ.get("RALPH_CLAUDE_COMMAND", "claude"))


def run_command_and_tee_output(
    command: list[str],
    input_text: str,
    output_path: Path,
) -> subprocess.CompletedProcess[str]:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_chunks: list[str] = []
    with output_path.open("w", encoding="utf-8") as output_file:
        process = subprocess.Popen(
            command,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )

        if process.stdin is None or process.stdout is None:
            raise RuntimeError("Could not open agent stdin/stdout pipes.")

        process.stdin.write(input_text)
        process.stdin.close()

        for line in process.stdout:
            print(line, end="", flush=True)
            output_file.write(line)
            output_file.flush()
            output_chunks.append(line)

    return_code = process.wait()
    output = "".join(output_chunks)
    return subprocess.CompletedProcess(
        args=command,
        returncode=return_code,
        stdout=output,
    )
