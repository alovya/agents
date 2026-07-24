from __future__ import annotations

import copy
import json
import shutil
import subprocess
from pathlib import Path
from typing import Any

import yaml

from ralph.plan_selection import (
    TaskSelection,
    find_task_by_id,
    is_alovya_task_id,
    read_tasks_from_ledger,
    refresh_task_selection_from_ledger,
    ticket_number_from_alovya_task_id,
)
from ralph.prompt import WORKER_NOTION_WORKLOG_FILENAME


def task_has_planned_notion_pairing(task: dict[str, Any]) -> bool:
    notion_task = task.get("notion_task")
    return isinstance(notion_task, dict) and notion_task.get("planned") is True


def prepare_notion_task_before_worker_runs_task(
    job: Any,
    ledger: dict[str, Any],
    selection: TaskSelection,
    task_path: Path,
) -> tuple[dict[str, Any], TaskSelection]:
    if not task_has_planned_notion_pairing(selection.task):
        return ledger, selection

    ledger_with_materialised_task = materialise_planned_notion_task_before_worker_launch(
        job=job,
        ledger=ledger,
        task=selection.task,
        task_path=task_path,
    )
    refreshed_selection = refresh_task_selection_from_ledger(
        ledger=ledger_with_materialised_task,
        selection=selection,
    )
    log_slice_start_to_notion(selection=refreshed_selection, task_path=task_path)
    return ledger_with_materialised_task, refreshed_selection


def materialise_planned_notion_task_before_worker_launch(
    job: Any,
    ledger: dict[str, Any],
    task: dict[str, Any],
    task_path: Path,
) -> dict[str, Any]:
    notion_task = task["notion_task"]
    if notion_task.get("materialized_task_id"):
        return ledger

    related_notion_task_id = _resolve_related_notion_task_id(
        tasks=read_tasks_from_ledger(ledger),
        related_to=notion_task["related_to"],
    )
    materialised_task_id = _create_planned_notion_task(
        relationship=notion_task["relationship"],
        related_notion_task_id=related_notion_task_id,
        title=notion_task["title"],
        task_path=task_path,
    )
    updated_ledger = _record_materialised_notion_task_id(
        ledger=ledger,
        task_id=task["id"],
        materialised_task_id=materialised_task_id,
    )
    _write_yaml_file(job.ledger_path, updated_ledger)
    return updated_ledger


def log_slice_start_to_notion(selection: TaskSelection, task_path: Path) -> None:
    notion_task_id = materialised_notion_task_id_from_task(selection.task)
    if notion_task_id is None:
        return

    _append_notion_task_log(
        notion_task_id=notion_task_id,
        task_path=task_path,
        log_name="slice-start",
        content={
            "title": f"Ralph {selection.task['id']} started",
            "blocks": [
                {"type": "paragraph", "text": f"Goal: {selection.task['title']}"},
                {"type": "code", "language": "yaml", "text": _dump_yaml({
                    "ralph_task_id": selection.task["id"],
                    "touchable_paths": selection.task.get("touchable_paths") or [],
                    "verification_commands": selection.task.get("verification_commands") or [],
                    "constraints": _worker_launch_constraints(),
                })},
            ],
        },
    )


def log_worker_promise_to_notion(
    selection: TaskSelection,
    task_path: Path,
    promise: str,
    agent_backend_name: str = "codex",
) -> None:
    notion_task_id = materialised_notion_task_id_from_task(selection.task)
    if notion_task_id is None:
        return

    _append_notion_task_log(
        notion_task_id=notion_task_id,
        task_path=task_path,
        log_name=f"worker-{promise.lower()}",
        content={
            "title": f"Worker returned {promise}",
            "blocks": [
                {"type": "paragraph", "text": f"Ralph task {selection.task['id']} stopped before verification."},
                *_build_agent_transcript_reference_blocks(
                    task_path=task_path,
                    agent_backend_name=agent_backend_name,
                ),
            ],
        },
    )


def log_failed_verification_to_notion(
    selection: TaskSelection,
    task_path: Path,
    agent_backend_name: str = "codex",
) -> None:
    notion_task_id = materialised_notion_task_id_from_task(selection.task)
    if notion_task_id is None:
        return

    _append_notion_task_log(
        notion_task_id=notion_task_id,
        task_path=task_path,
        log_name="verification-failed",
        content={
            "title": "Verification failed",
            "blocks": [
                {"type": "paragraph", "text": f"Ralph task {selection.task['id']} returned DONE, then verification failed."},
                {
                    "type": "code",
                    "language": "text",
                    "text": _read_text_if_file_exists(task_path / "verification-output.txt"),
                },
                *_build_agent_transcript_reference_blocks(
                    task_path=task_path,
                    agent_backend_name=agent_backend_name,
                ),
            ],
        },
    )


def log_completed_worker_to_notion(
    selection: TaskSelection,
    task_path: Path,
    changed_files: list[str],
    commit_hash: str,
    agent_backend_name: str = "codex",
) -> None:
    notion_task_id = materialised_notion_task_id_from_task(selection.task)
    if notion_task_id is None:
        return

    _append_notion_task_log(
        notion_task_id=notion_task_id,
        task_path=task_path,
        log_name="worker-completed",
        content={
            "title": f"Ralph {selection.task['id']} completed",
            "blocks": [
                {"type": "code", "language": "text", "text": "\n".join(changed_files) or "No changed files were captured before commit."},
                {
                    "type": "code",
                    "language": "text",
                    "text": _read_text_if_file_exists(task_path / "verification-output.txt"),
                },
                {"type": "paragraph", "text": f"Commit hash: {commit_hash}"},
                *_build_agent_transcript_reference_blocks(
                    task_path=task_path,
                    agent_backend_name=agent_backend_name,
                ),
            ],
        },
    )


def materialised_notion_task_id_from_task(task: dict[str, Any]) -> str | None:
    notion_task = task.get("notion_task")
    if not isinstance(notion_task, dict):
        return None

    materialised_task_id = notion_task.get("materialized_task_id")
    if materialised_task_id:
        return materialised_task_id
    return None


class WorklogValidationError(Exception):
    pass


def validate_worker_worklog(repo_path: Path) -> dict[str, Any]:
    worklog_path = repo_path / WORKER_NOTION_WORKLOG_FILENAME
    if not worklog_path.is_file():
        raise WorklogValidationError(
            f"Worker worklog file not found: {worklog_path}\n"
            f"Workers must write {WORKER_NOTION_WORKLOG_FILENAME} in the repository root before returning DONE, BLOCKED, or ABORT."
        )

    try:
        content = worklog_path.read_text(encoding="utf-8")
    except Exception as error:
        raise WorklogValidationError(f"Could not read worker worklog file: {error}") from error

    try:
        worklog = json.loads(content)
    except json.JSONDecodeError as error:
        raise WorklogValidationError(
            f"Worker worklog is not valid JSON: {error}\n"
            f"Content: {content[:500]}{'...' if len(content) > 500 else ''}"
        ) from error

    if not isinstance(worklog, dict):
        raise WorklogValidationError(
            f"Worker worklog must be a JSON object, got {type(worklog).__name__}."
        )

    _validate_worklog_title(worklog)
    _validate_worklog_blocks(worklog)
    return worklog


def validate_worker_worklog_is_controller_input(repo_path: Path) -> None:
    worklog_path = repo_path / WORKER_NOTION_WORKLOG_FILENAME
    completed_process = subprocess.run(
        ["git", "-C", str(repo_path), "ls-files", "--error-unmatch", "--", WORKER_NOTION_WORKLOG_FILENAME],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )
    if completed_process.returncode == 0:
        raise WorklogValidationError(
            f"Worker worklog must remain untracked for the controller: {worklog_path}"
        )


def _validate_worklog_title(worklog: dict[str, Any]) -> None:
    if "title" not in worklog:
        raise WorklogValidationError("Worker worklog missing required field: title")

    title = worklog["title"]
    if not isinstance(title, str):
        raise WorklogValidationError(
            f"Worker worklog field 'title' must be a string, got {type(title).__name__}."
        )
    if not title.strip():
        raise WorklogValidationError("Worker worklog field 'title' must be a non-empty string.")


def _validate_worklog_blocks(worklog: dict[str, Any]) -> None:
    if "blocks" not in worklog:
        raise WorklogValidationError("Worker worklog missing required field: blocks")

    blocks = worklog["blocks"]
    if not isinstance(blocks, list):
        raise WorklogValidationError(
            f"Worker worklog field 'blocks' must be a list, got {type(blocks).__name__}."
        )
    if not blocks:
        raise WorklogValidationError("Worker worklog field 'blocks' must be a non-empty list.")

    for index, block in enumerate(blocks):
        _validate_worklog_block(block, index)


def _validate_worklog_block(block: Any, index: int) -> None:
    if not isinstance(block, dict):
        raise WorklogValidationError(
            f"Worker worklog blocks[{index}] must be an object, got {type(block).__name__}."
        )

    if "type" not in block:
        raise WorklogValidationError(f"Worker worklog blocks[{index}] missing required field: type")

    block_type = block["type"]
    if block_type not in ("paragraph", "code"):
        raise WorklogValidationError(
            f"Worker worklog blocks[{index}] field 'type' must be 'paragraph' or 'code', got {block_type!r}."
        )

    if "text" not in block:
        raise WorklogValidationError(f"Worker worklog blocks[{index}] missing required field: text")

    text = block["text"]
    if not isinstance(text, str):
        raise WorklogValidationError(
            f"Worker worklog blocks[{index}] field 'text' must be a string, got {type(text).__name__}."
        )
    if not text.strip():
        raise WorklogValidationError(
            f"Worker worklog blocks[{index}] field 'text' must be a non-empty string."
        )

    if block_type == "code":
        if "language" not in block:
            raise WorklogValidationError(
                f"Worker worklog blocks[{index}] is a code block but missing required field: language"
            )
        language = block["language"]
        if not isinstance(language, str):
            raise WorklogValidationError(
                f"Worker worklog blocks[{index}] field 'language' must be a string, got {type(language).__name__}."
            )
        if not language.strip():
            raise WorklogValidationError(
                f"Worker worklog blocks[{index}] field 'language' must be a non-empty string."
            )


def log_validated_worker_worklog_to_notion(
    selection: TaskSelection,
    task_path: Path,
    worklog: dict[str, Any],
) -> None:
    notion_task_id = materialised_notion_task_id_from_task(selection.task)
    if notion_task_id is None:
        return

    _append_notion_task_log(
        notion_task_id=notion_task_id,
        task_path=task_path,
        log_name="worker-worklog",
        content=worklog,
    )


def delete_worker_worklog_file(repo_path: Path) -> None:
    worklog_path = repo_path / WORKER_NOTION_WORKLOG_FILENAME
    if worklog_path.is_file():
        worklog_path.unlink()


def _build_notion_task_creation_command(
    relationship: str,
    related_notion_task_id: str,
    title: str,
    content_path: Path,
    output_path: Path,
) -> list[str]:
    if relationship == "child":
        return [
            _resolve_notion_tracker_command_path(),
            "--child",
            "--parent-ticket-number",
            ticket_number_from_alovya_task_id(related_notion_task_id),
            "--title",
            title,
            "--content-path",
            str(content_path),
            "--output-path",
            str(output_path),
        ]
    if relationship == "sibling":
        return [
            _resolve_notion_tracker_command_path(),
            "--sibling",
            "--sibling-ticket-number",
            ticket_number_from_alovya_task_id(related_notion_task_id),
            "--title",
            title,
            "--content-path",
            str(content_path),
            "--output-path",
            str(output_path),
        ]
    raise ValueError(f"Unsupported Notion relationship: {relationship}")


def _extract_created_notion_task_id(output_path: Path) -> str:
    summary = json.loads(output_path.read_text(encoding="utf-8"))
    notion_operations = summary.get("notion_operations")
    if not isinstance(notion_operations, list):
        raise RuntimeError("NTT task creation summary has no notion_operations list.")

    for index, operation in enumerate(notion_operations[:-1]):
        if not isinstance(operation, str) or not operation.startswith("create_database_task:"):
            continue
        update_operation = notion_operations[index + 1]
        if isinstance(update_operation, str) and update_operation.startswith("update_properties:task:"):
            return update_operation.removeprefix("update_properties:task:")

    raise RuntimeError("NTT task creation summary does not identify the created task.")


def _resolve_related_notion_task_id(tasks: list[dict[str, Any]], related_to: str) -> str:
    if is_alovya_task_id(related_to):
        return related_to

    related_task = find_task_by_id(tasks, related_to)
    related_notion_task_id = materialised_notion_task_id_from_task(related_task)
    if related_notion_task_id is None:
        raise RuntimeError(
            f"Task {related_to} must materialise its Notion task before another task can relate to it."
        )
    return related_notion_task_id


def _create_planned_notion_task(
    relationship: str,
    related_notion_task_id: str,
    title: str,
    task_path: Path,
) -> str:
    output_path = task_path / "notion-create-output.json"
    content_path = _write_notion_content_file(
        task_path=task_path,
        log_name="create",
        content={
            "title": "Ralph task materialised",
            "blocks": [
                {"type": "paragraph", "text": f"Created from Ralph plan: {title}"},
            ],
        },
    )
    command = _build_notion_task_creation_command(
        relationship=relationship,
        related_notion_task_id=related_notion_task_id,
        title=title,
        content_path=content_path,
        output_path=output_path,
    )
    completed_process = _run_notion_tracker_command(command)
    _write_text(task_path / "notion-create-stdout.txt", completed_process.stdout)
    return _extract_created_notion_task_id(output_path)


def _append_notion_task_log(
    notion_task_id: str,
    task_path: Path,
    log_name: str,
    content: dict[str, Any],
) -> None:
    content_path = _write_notion_content_file(task_path=task_path, log_name=log_name, content=content)
    output_path = task_path / f"notion-{log_name}-output.json"
    command = [
        _resolve_notion_tracker_command_path(),
        "--log",
        "--ticket-number",
        ticket_number_from_alovya_task_id(notion_task_id),
        "--content-path",
        str(content_path),
        "--output-path",
        str(output_path),
    ]
    completed_process = _run_notion_tracker_command(command)
    _write_text(task_path / f"notion-{log_name}-stdout.txt", completed_process.stdout)


def _record_materialised_notion_task_id(
    ledger: dict[str, Any],
    task_id: str,
    materialised_task_id: str,
) -> dict[str, Any]:
    updated_ledger = copy.deepcopy(ledger)
    for task in read_tasks_from_ledger(updated_ledger):
        if task["id"] == task_id:
            task["notion_task"]["materialized_task_id"] = materialised_task_id
            return updated_ledger
    raise ValueError(f"Unknown Ralph task id: {task_id}")


def _write_notion_content_file(task_path: Path, log_name: str, content: dict[str, Any]) -> Path:
    content_path = task_path / f"notion-{log_name}-content.json"
    content_path.write_text(json.dumps(content, indent=2, sort_keys=True), encoding="utf-8")
    return content_path


def _run_notion_tracker_command(command: list[str]) -> subprocess.CompletedProcess[str]:
    completed_process = subprocess.run(
        command,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )
    if completed_process.returncode != 0:
        raise RuntimeError(f"Notion task tracker command failed:\n{completed_process.stdout}")
    return completed_process


def _worker_launch_constraints() -> list[str]:
    return [
        "Worker cannot read Ralph controller state.",
        "Worker cannot receive Notion credentials or tracker state.",
        "Worker may run only the bash commands allowed by the active task contract.",
        "Worker must run verification before DONE.",
        "Worker must commit with git commit --no-verify before DONE.",
        "Controller owns Notion logging and validates worker-produced verification and commit artefacts.",
    ]


def _build_agent_transcript_reference_blocks(task_path: Path, agent_backend_name: str) -> list[dict[str, str]]:
    transcript_blocks = [
        {"type": "paragraph", "text": f"Transcript path: {task_path / 'agent-output.txt'}"},
    ]
    if agent_backend_name == "claude":
        transcript_blocks.append({
            "type": "paragraph",
            "text": f"Raw Claude stream path: {task_path / 'agent-output.raw.jsonl'}",
        })
    return transcript_blocks


def _resolve_notion_tracker_command_path() -> str:
    command_path = shutil.which("ntt")
    if command_path is not None:
        return command_path

    workspace_command_path = Path("/workspace/venv/bin/ntt")
    if workspace_command_path.is_file():
        return str(workspace_command_path)

    raise RuntimeError("Notion task tracker command not found: ntt")


def _read_text_if_file_exists(path: Path) -> str:
    if path.is_file():
        return path.read_text(encoding="utf-8")
    return ""


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


def _write_yaml_file(yaml_path: Path, value: dict[str, Any]) -> None:
    yaml_path.write_text(_dump_yaml(value))


def _dump_yaml(value: Any) -> str:
    return yaml.safe_dump(value, sort_keys=False)
