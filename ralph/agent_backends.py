from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass
from pathlib import Path

from ralph.claude_backend import (
    build_claude_agent_backend,
    extract_claude_stream_result_text,
    format_claude_stream_event_for_human,
)
from ralph.codex_backend import (
    build_codex_agent_backend,
    extract_codex_stream_result_text,
    format_codex_stream_event_for_human,
)
from ralph.cursor_backend import (
    build_cursor_agent_backend,
    extract_cursor_stream_result_text,
    format_cursor_stream_event_for_human,
)


@dataclass(frozen=True)
class AgentResult:
    promise: str
    output: str


@dataclass(frozen=True)
class AgentBackend:
    backend_name: str
    command_name: str
    agent_config_dir: Path
    agent_home_environment_variable: str


@dataclass(frozen=True)
class AgentTranscriptStrategy:
    backend_name: str
    raw_output_path: Path
    human_output_path: Path


def select_agent_backend(
    agent_backend_name: str,
    agent_command: str | None,
) -> AgentBackend:
    if agent_backend_name == "codex":
        return build_codex_agent_backend(agent_command)
    if agent_backend_name == "claude":
        return build_claude_agent_backend(agent_command)
    if agent_backend_name == "cursor":
        return build_cursor_agent_backend(agent_command)
    raise ValueError(f"Unsupported agent backend: {agent_backend_name}")


def extract_agent_result_text(agent_backend: AgentBackend, raw_output: str) -> str:
    if agent_backend.backend_name == "codex":
        return extract_codex_stream_result_text(raw_output)
    if agent_backend.backend_name == "claude":
        return extract_claude_stream_result_text(raw_output)
    if agent_backend.backend_name == "cursor":
        return extract_cursor_stream_result_text(raw_output)
    return raw_output


def read_default_codex_agent_command() -> str:
    codex_home_path = Path(os.environ["CODEX_HOME"]).expanduser().resolve()
    standalone_codex_path = codex_home_path / "packages" / "standalone" / "current" / "bin" / "codex"
    if standalone_codex_path.is_file() and os.access(standalone_codex_path, os.X_OK):
        return str(standalone_codex_path)
    raise RuntimeError(f"Codex standalone binary does not exist or is not executable: {standalone_codex_path}")


DEFAULT_CLAUDE_COMMAND = "claude"
DEFAULT_CURSOR_COMMAND = "agent"


def run_command_and_tee_output(
    command: list[str],
    input_text: str,
    output_path: Path,
) -> subprocess.CompletedProcess[str]:
    return _run_command_and_stream_plain_text_transcript(
        command=command,
        input_text=input_text,
        output_path=output_path,
        tee_output=True,
    )


def run_command_and_save_agent_transcripts(
    command: list[str],
    input_text: str,
    output_path: Path,
    agent_backend: AgentBackend,
    tee_output: bool,
) -> subprocess.CompletedProcess[str]:
    transcript_strategy = _choose_agent_transcript_strategy(
        backend_name=agent_backend.backend_name,
        output_path=output_path,
    )

    return _run_command_and_stream_transcripts(
        command=command,
        input_text=input_text,
        transcript_strategy=transcript_strategy,
        tee_output=tee_output,
    )


def _choose_agent_transcript_strategy(
    backend_name: str,
    output_path: Path,
) -> AgentTranscriptStrategy:
    if backend_name == "claude":
        return AgentTranscriptStrategy(
            backend_name=backend_name,
            raw_output_path=output_path.with_suffix(".raw.jsonl"),
            human_output_path=output_path,
        )
    if backend_name == "codex":
        return AgentTranscriptStrategy(
            backend_name=backend_name,
            raw_output_path=output_path.with_suffix(".raw.jsonl"),
            human_output_path=output_path,
        )
    if backend_name == "cursor":
        return AgentTranscriptStrategy(
            backend_name=backend_name,
            raw_output_path=output_path.with_suffix(".raw.jsonl"),
            human_output_path=output_path,
        )
    return AgentTranscriptStrategy(
        backend_name=backend_name,
        raw_output_path=output_path,
        human_output_path=output_path,
    )


def _run_command_and_stream_transcripts(
    command: list[str],
    input_text: str,
    transcript_strategy: AgentTranscriptStrategy,
    tee_output: bool,
) -> subprocess.CompletedProcess[str]:
    if transcript_strategy.raw_output_path == transcript_strategy.human_output_path:
        return _run_command_and_stream_plain_text_transcript(
            command=command,
            input_text=input_text,
            output_path=transcript_strategy.human_output_path,
            tee_output=tee_output,
        )

    return _run_command_and_stream_raw_and_human_transcripts(
        command=command,
        input_text=input_text,
        transcript_strategy=transcript_strategy,
        tee_output=tee_output,
    )


def _run_command_and_stream_plain_text_transcript(
    command: list[str],
    input_text: str,
    output_path: Path,
    tee_output: bool,
) -> subprocess.CompletedProcess[str]:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    raw_output_chunks: list[str] = []
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
            if tee_output:
                print(line, end="", flush=True)
            output_file.write(line)
            output_file.flush()
            raw_output_chunks.append(line)

    return_code = process.wait()
    raw_output = "".join(raw_output_chunks)
    return subprocess.CompletedProcess(
        args=command,
        returncode=return_code,
        stdout=raw_output,
    )


def _run_command_and_stream_raw_and_human_transcripts(
    command: list[str],
    input_text: str,
    transcript_strategy: AgentTranscriptStrategy,
    tee_output: bool,
) -> subprocess.CompletedProcess[str]:
    transcript_strategy.raw_output_path.parent.mkdir(parents=True, exist_ok=True)
    transcript_strategy.human_output_path.parent.mkdir(parents=True, exist_ok=True)
    raw_output_chunks: list[str] = []
    emitted_claude_texts: set[str] = set()

    with (
        transcript_strategy.raw_output_path.open("w", encoding="utf-8") as raw_output_file,
        transcript_strategy.human_output_path.open("w", encoding="utf-8") as human_output_file,
    ):
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

        for raw_line in process.stdout:
            raw_output_file.write(raw_line)
            raw_output_file.flush()
            raw_output_chunks.append(raw_line)

            human_text = _format_agent_stream_line_for_human(
                backend_name=transcript_strategy.backend_name,
                raw_line=raw_line,
                emitted_claude_texts=emitted_claude_texts,
            )
            if not human_text:
                continue

            if tee_output:
                print(human_text, end="", flush=True)
            human_output_file.write(human_text)
            human_output_file.flush()

    return_code = process.wait()
    raw_output = "".join(raw_output_chunks)
    return subprocess.CompletedProcess(
        args=command,
        returncode=return_code,
        stdout=raw_output,
    )


def _format_agent_stream_line_for_human(
    backend_name: str,
    raw_line: str,
    emitted_claude_texts: set[str],
) -> str:
    if backend_name == "codex":
        human_lines = format_codex_stream_event_for_human(raw_line)
        return "".join(f"{human_line}\n" for human_line in human_lines)
    if backend_name == "claude":
        human_lines = format_claude_stream_event_for_human(raw_line, emitted_claude_texts)
        if human_lines:
            emitted_claude_texts.add("\n".join(human_lines))
        return "".join(f"{human_line}\n" for human_line in human_lines)
    if backend_name == "cursor":
        human_lines = format_cursor_stream_event_for_human(raw_line, emitted_claude_texts)
        if human_lines:
            emitted_claude_texts.add("\n".join(human_lines))
        return "".join(f"{human_line}\n" for human_line in human_lines)
    return raw_line
