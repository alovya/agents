"""Top-level CLI workflow for tracker commands and full task refreshes."""

from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from notion_task_tracker.notion_operations.client import notion_client_from_credentials_path
from notion_task_tracker.notion_operations.create_task_database_page import (
    should_create_task_database_page_for_command,
    execute_create_task_database_page_command,
)
from notion_task_tracker.notion_operations.prepare_task_page_timeline_log_write import (
    prepare_command_result_from_current_task_page,
    merge_context_repairs_into_command_result,
    plan_context_repair_result,
)
from notion_task_tracker.notion_operations.reconcile_task_database import (
    plan_repairs_for_task_graph_changes,
    refresh_tracker_state_for_task_command,
    refresh_tracker_state_from_notion_task_database,
)
from notion_task_tracker.notion_operations.write_executor import execute_command_result_writes
from notion_task_tracker.tasks import TaskDependencyGraph


DEFAULT_CODEX_HOME_PATH = Path.home() / ".codex"
DEFAULT_CREDENTIALS_PATH = DEFAULT_CODEX_HOME_PATH / ".credentials.json"
DEFAULT_TRACKER_STATE_PATH = DEFAULT_CODEX_HOME_PATH / "memories" / "notion_tasks_graph.json"
DEFAULT_OUTPUT_PATH = Path("/tmp/notion_task_refreshed_result.json")


def execute_command_file(
    command_path: str | Path,
    tracker_state_path: str | Path = DEFAULT_TRACKER_STATE_PATH,
    output_path: str | Path = DEFAULT_OUTPUT_PATH,
    credentials_path: str | Path = DEFAULT_CREDENTIALS_PATH,
    backup_path: str | Path | None = None,
    notion_client: str = "rest",
) -> "NotionCommandExecutionSummary":
    return asyncio.run(_execute_command_file(
        command_path=command_path,
        tracker_state_path=tracker_state_path,
        output_path=output_path,
        credentials_path=credentials_path,
        backup_path=backup_path,
        notion_client=notion_client,
    ))


def refresh_task_tracker_from_notion(
    credentials_path: str | Path = DEFAULT_CREDENTIALS_PATH,
    tracker_state_path: str | Path = DEFAULT_TRACKER_STATE_PATH,
    output_path: str | Path = DEFAULT_OUTPUT_PATH,
    backup_path: str | Path | None = None,
    notion_client: str = "rest",
) -> "TaskTrackerRefreshSummary":
    return asyncio.run(_refresh_task_tracker_from_notion(
        credentials_path=credentials_path,
        tracker_state_path=tracker_state_path,
        output_path=output_path,
        backup_path=backup_path,
        notion_client=notion_client,
    ))


async def _execute_command_file(
    command_path: str | Path,
    tracker_state_path: str | Path,
    output_path: str | Path,
    credentials_path: str | Path,
    backup_path: str | Path | None,
    notion_client: str,
) -> "NotionCommandExecutionSummary":
    source_command_path = Path(command_path)
    source_tracker_state_path = Path(tracker_state_path)
    destination_output_path = Path(output_path)
    destination_backup_path = Path(backup_path) if backup_path else _timestamped_backup_path()

    command = _read_json(source_command_path)
    tracker_state = _read_json(source_tracker_state_path)
    _write_json(destination_backup_path, tracker_state)

    client = notion_client_from_credentials_path(Path(credentials_path), notion_client)
    command_ready_result = await refresh_tracker_state_for_task_command(
        command=command,
        tracker_state=tracker_state,
        notion_client=client,
    )
    command_ready_tracker_state = command_ready_result.tracker_state

    if should_create_task_database_page_for_command(command, command_ready_tracker_state):
        command_tracker_state, command_operation_keys = await execute_create_task_database_page_command(
            command=command,
            tracker_state=command_ready_tracker_state,
            notion_client=client,
        )
        command_warnings = []
    else:
        context_repair_result = plan_context_repair_result(
            before_tracker_state=tracker_state,
            command_ready_result=command_ready_result,
        )
        command_result = await prepare_command_result_from_current_task_page(
            command=command,
            tracker_state=command_ready_tracker_state,
            notion_client=client,
        )
        command_result = merge_context_repairs_into_command_result(context_repair_result, command_result)
        command_tracker_state, command_operation_keys = await execute_command_result_writes(command_result, client)
        command_warnings = command_result.warnings or []

    _write_json(source_tracker_state_path, command_tracker_state)
    execution_summary = NotionCommandExecutionSummary(
        backup_path=destination_backup_path,
        command_path=source_command_path,
        completed_operation_keys=command_operation_keys,
        output_path=destination_output_path,
        tracker_state_path=source_tracker_state_path,
        warnings=list(command_ready_result.warnings or []) + list(command_warnings),
    )
    _write_json(destination_output_path, execution_summary.to_json_summary())
    return execution_summary


async def _refresh_task_tracker_from_notion(
    credentials_path: str | Path,
    tracker_state_path: str | Path,
    output_path: str | Path,
    backup_path: str | Path | None,
    notion_client: str,
) -> "TaskTrackerRefreshSummary":
    source_tracker_state_path = Path(tracker_state_path)
    destination_output_path = Path(output_path)
    destination_backup_path = Path(backup_path) if backup_path else _timestamped_backup_path()

    tracker_state = _read_json(source_tracker_state_path)
    _write_json(destination_backup_path, tracker_state)

    client = notion_client_from_credentials_path(Path(credentials_path), notion_client)
    refreshed_result = await refresh_tracker_state_from_notion_task_database(tracker_state, client)
    return await repair_and_write_refreshed_tracker_state(
        source_tracker_state_path=source_tracker_state_path,
        destination_output_path=destination_output_path,
        destination_backup_path=destination_backup_path,
        before_tracker_state=tracker_state,
        refreshed_result=refreshed_result,
        notion_client=client,
    )


async def repair_and_write_refreshed_tracker_state(
    source_tracker_state_path: Path,
    destination_output_path: Path,
    destination_backup_path: Path,
    before_tracker_state: dict[str, Any],
    refreshed_result,
    notion_client,
) -> "TaskTrackerRefreshSummary":
    task_changes = TaskDependencyGraph.changes_between_tracker_states(
        before_tracker_state,
        refreshed_result.tracker_state,
    )
    repair_result = plan_repairs_for_task_graph_changes(
        refreshed_result=refreshed_result,
        task_graph_changes=task_changes,
    )
    repaired_tracker_state, completed_operation_keys = await execute_command_result_writes(repair_result, notion_client)
    _write_json(source_tracker_state_path, repaired_tracker_state)

    refresh_summary = TaskTrackerRefreshSummary(
        backup_path=destination_backup_path,
        completed_operation_keys=completed_operation_keys,
        output_path=destination_output_path,
        tracker_state_path=source_tracker_state_path,
        task_count=len(repaired_tracker_state["tasks"]),
        task_graph_changes=task_changes,
        warnings=refreshed_result.warnings or [],
        repair_operation_count=len(repair_result.write_intents),
    )
    _write_json(destination_output_path, refresh_summary.to_json_summary())
    return refresh_summary


@dataclass(frozen=True)
class TaskTrackerRefreshSummary:
    backup_path: Path
    completed_operation_keys: list[str]
    output_path: Path
    tracker_state_path: Path
    task_count: int
    task_graph_changes: list[dict[str, Any]]
    warnings: list[dict[str, str]]
    repair_operation_count: int

    def to_json_summary(self) -> dict[str, Any]:
        return {
            "backup_path": str(self.backup_path),
            "completed_operations": list(self.completed_operation_keys),
            "output_path": str(self.output_path),
            "tracker_state_path": str(self.tracker_state_path),
            "task_count": self.task_count,
            "task_graph_changes": self.task_graph_changes,
            "warnings": self.warnings,
            "repair_operation_count": self.repair_operation_count,
        }


@dataclass(frozen=True)
class NotionCommandExecutionSummary:
    backup_path: Path
    command_path: Path
    completed_operation_keys: list[str]
    output_path: Path
    tracker_state_path: Path
    warnings: list[dict[str, str]]

    def to_json_summary(self) -> dict[str, Any]:
        return {
            "backup_path": str(self.backup_path),
            "command_path": str(self.command_path),
            "completed_operations": list(self.completed_operation_keys),
            "output_path": str(self.output_path),
            "tracker_state_path": str(self.tracker_state_path),
            "warnings": list(self.warnings),
        }


def _timestamped_backup_path() -> Path:
    return Path("/tmp") / f"notion_tasks_graph_before_refresh_{int(time.time())}.json"


def _read_json(source_path: Path) -> dict[str, Any]:
    return json.loads(source_path.read_text(encoding="utf-8"))


def _write_json(destination_path: Path, tracker_state: dict[str, Any]) -> None:
    destination_path.write_text(
        json.dumps(tracker_state, indent=2, sort_keys=True),
        encoding="utf-8",
    )
