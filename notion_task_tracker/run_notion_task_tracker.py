"""Run the Notion task tracker CLI and tracker commands."""

from __future__ import annotations

import argparse
import asyncio
import json
import time
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from notion_task_tracker.build_tracker_command import build_tracker_command_from_cli_action
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
    refresh_tracker_state_for_task_ids,
    refresh_tracker_state_for_task_command,
    refresh_tracker_state_from_notion_task_database,
)
from notion_task_tracker.notion_operations.write_executor import execute_command_result_writes
from notion_task_tracker.tasks import TaskDependencyGraph
from notion_task_tracker.tasks.timeline_log import parse_timeline_entries_from_fetched_task_page_content


DEFAULT_CODEX_HOME_PATH = Path.home() / ".codex"
DEFAULT_CREDENTIALS_PATH = DEFAULT_CODEX_HOME_PATH / ".credentials.json"
DEFAULT_TRACKER_STATE_PATH = DEFAULT_CODEX_HOME_PATH / "memories" / "notion_tasks_graph.json"
DEFAULT_OUTPUT_PATH = Path("/tmp/notion_task_refreshed_result.json")


def main(argv: Sequence[str] | None = None) -> None:
    parser = _build_argument_parser()
    args = parse_args(argv, parser)

    try:
        _run_requested_cli_action(args)
    except PermissionError as error:
        parser.exit(1, f"{error}\n")
    except ValueError as error:
        parser.exit(2, f"{error}\n")


def parse_args(
    argv: Sequence[str] | None = None,
    parser: argparse.ArgumentParser | None = None,
) -> argparse.Namespace:
    parser = parser or _build_argument_parser()
    return parser.parse_args(argv)


def _build_argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    action_group = parser.add_mutually_exclusive_group()
    action_group.add_argument("--reconcile-from-notion", action="store_true")
    action_group.add_argument("--read", action="store_true")
    action_group.add_argument("--work", action="store_true")
    action_group.add_argument("--log", action="store_true")
    action_group.add_argument("--complete", action="store_true")
    action_group.add_argument("--cancel", action="store_true")
    action_group.add_argument("--parent", action="store_true")
    action_group.add_argument("--child", action="store_true")
    action_group.add_argument("--sibling", action="store_true")
    action_group.add_argument("--misc", action="store_true")
    action_group.add_argument("--synth", action="store_true")
    parser.add_argument("--tracker-state-path")
    parser.add_argument("--output-path")
    parser.add_argument("--credentials-path")
    parser.add_argument("--notion-transport", choices=["rest", "mcp"], default="rest")
    parser.add_argument("--ticket-number", action="append", type=int, default=[])
    parser.add_argument("--parent-ticket-number", type=int)
    parser.add_argument("--sibling-ticket-number", type=int)
    parser.add_argument("--title")
    parser.add_argument("--priority", choices=["P0", "P1", "P2", "P3"], default="P1")
    parser.add_argument("--content-path")
    parser.add_argument("--synthesis-key")
    parser.add_argument("--entry-date")
    return parser


def _run_requested_cli_action(args: argparse.Namespace) -> None:
    command = build_tracker_command_from_cli_action(args)
    execution_summary = execute_tracker_command(
        command=command,
        tracker_state_path=args.tracker_state_path or DEFAULT_TRACKER_STATE_PATH,
        output_path=args.output_path or DEFAULT_OUTPUT_PATH,
        credentials_path=args.credentials_path or DEFAULT_CREDENTIALS_PATH,
        notion_client=args.notion_transport,
    )
    print(json.dumps(execution_summary.to_json_summary(), indent=2, sort_keys=True))


def execute_tracker_command(
    command: dict[str, Any],
    tracker_state_path: str | Path = DEFAULT_TRACKER_STATE_PATH,
    output_path: str | Path = DEFAULT_OUTPUT_PATH,
    credentials_path: str | Path = DEFAULT_CREDENTIALS_PATH,
    backup_path: str | Path | None = None,
    notion_client: str = "rest",
) -> "TrackerActionExecutionSummary":
    return asyncio.run(_run_tracker_command(
        command=command,
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
) -> "TrackerActionExecutionSummary":
    return asyncio.run(_run_reconcile_tracker_from_notion_command(
        credentials_path=credentials_path,
        tracker_state_path=tracker_state_path,
        output_path=output_path,
        backup_path=backup_path,
        notion_client=notion_client,
    ))


def read_task_pages(
    task_ids: list[str],
    tracker_state_path: str | Path = DEFAULT_TRACKER_STATE_PATH,
    output_path: str | Path = DEFAULT_OUTPUT_PATH,
    credentials_path: str | Path = DEFAULT_CREDENTIALS_PATH,
    notion_client: str = "rest",
) -> "TrackerActionExecutionSummary":
    return asyncio.run(_run_read_task_pages(
        action_name="read",
        task_ids=task_ids,
        tracker_state_path=tracker_state_path,
        output_path=output_path,
        credentials_path=credentials_path,
        notion_client=notion_client,
    ))


async def _run_tracker_command(
    command: dict[str, Any],
    tracker_state_path: str | Path,
    output_path: str | Path,
    credentials_path: str | Path,
    backup_path: str | Path | None,
    notion_client: str,
) -> "TrackerActionExecutionSummary":
    if command["command"] == "reconcile_from_notion":
        return await _run_reconcile_tracker_from_notion_command(
            credentials_path=credentials_path,
            tracker_state_path=tracker_state_path,
            output_path=output_path,
            backup_path=backup_path,
            notion_client=notion_client,
        )

    if command["command"] in {"read_tasks", "work_task"}:
        return await _run_read_task_pages_command(
            command=command,
            tracker_state_path=tracker_state_path,
            output_path=output_path,
            credentials_path=credentials_path,
            notion_client=notion_client,
        )

    return await _run_write_tracker_command(
        command=command,
        tracker_state_path=tracker_state_path,
        output_path=output_path,
        credentials_path=credentials_path,
        backup_path=backup_path,
        notion_client=notion_client,
    )


async def _run_reconcile_tracker_from_notion_command(
    credentials_path: str | Path,
    tracker_state_path: str | Path,
    output_path: str | Path,
    backup_path: str | Path | None,
    notion_client: str,
) -> "TrackerActionExecutionSummary":
    source_tracker_state_path = Path(tracker_state_path)
    destination_output_path = Path(output_path)
    destination_backup_path = Path(backup_path) if backup_path else _timestamped_backup_path()

    tracker_state = _read_json(source_tracker_state_path)
    _write_json(destination_backup_path, tracker_state)

    client = _notion_client_from_name_or_instance(credentials_path, notion_client)
    refreshed_result = await refresh_tracker_state_from_notion_task_database(tracker_state, client)
    return await repair_and_write_refreshed_tracker_state(
        source_tracker_state_path=source_tracker_state_path,
        destination_output_path=destination_output_path,
        destination_backup_path=destination_backup_path,
        before_tracker_state=tracker_state,
        refreshed_result=refreshed_result,
        notion_client=client,
    )


async def _run_read_task_pages_command(
    command: dict[str, Any],
    tracker_state_path: str | Path,
    output_path: str | Path,
    credentials_path: str | Path,
    notion_client: str,
) -> "TrackerActionExecutionSummary":
    return await _run_read_task_pages(
        action_name=_action_name_from_tracker_command(command),
        task_ids=list(command["task_ids"]),
        tracker_state_path=tracker_state_path,
        output_path=output_path,
        credentials_path=credentials_path,
        notion_client=notion_client,
    )


async def _run_write_tracker_command(
    command: dict[str, Any],
    tracker_state_path: str | Path,
    output_path: str | Path,
    credentials_path: str | Path,
    backup_path: str | Path | None,
    notion_client: str,
) -> "TrackerActionExecutionSummary":
    source_tracker_state_path = Path(tracker_state_path)
    destination_output_path = Path(output_path)
    destination_backup_path = Path(backup_path) if backup_path else _timestamped_backup_path()

    tracker_state = _read_json(source_tracker_state_path)
    _write_json(destination_backup_path, tracker_state)

    client = _notion_client_from_name_or_instance(credentials_path, notion_client)
    command_ready_result = await refresh_tracker_state_for_task_command(
        command=command,
        tracker_state=tracker_state,
        notion_client=client,
    )
    command_ready_tracker_state = command_ready_result.tracker_state

    command_tracker_state, command_operation_keys, command_warnings = await _run_notion_writes_for_write_command(
        command=command,
        before_tracker_state=tracker_state,
        command_ready_result=command_ready_result,
        command_ready_tracker_state=command_ready_tracker_state,
        notion_client=client,
    )

    _write_json(source_tracker_state_path, command_tracker_state)
    execution_summary = TrackerActionExecutionSummary(
        action_name=_action_name_from_tracker_command(command),
        backup_path=destination_backup_path,
        completed_operation_keys=command_operation_keys,
        output_path=destination_output_path,
        tracker_state_path=source_tracker_state_path,
        warnings=list(command_ready_result.warnings or []) + list(command_warnings),
    )
    _write_json(destination_output_path, execution_summary.to_json_summary())
    return execution_summary


async def _run_notion_writes_for_write_command(
    command: dict[str, Any],
    before_tracker_state: dict[str, Any],
    command_ready_result,
    command_ready_tracker_state: dict[str, Any],
    notion_client,
) -> tuple[dict[str, Any], list[str], list[dict[str, str]]]:
    if should_create_task_database_page_for_command(command, command_ready_tracker_state):
        command_tracker_state, command_operation_keys = await execute_create_task_database_page_command(
            command=command,
            tracker_state=command_ready_tracker_state,
            notion_client=notion_client,
        )
        return command_tracker_state, command_operation_keys, []

    context_repair_result = plan_context_repair_result(
        before_tracker_state=before_tracker_state,
        command_ready_result=command_ready_result,
    )
    command_result = await prepare_command_result_from_current_task_page(
        command=command,
        tracker_state=command_ready_tracker_state,
        notion_client=notion_client,
    )
    command_result = merge_context_repairs_into_command_result(context_repair_result, command_result)
    command_tracker_state, command_operation_keys = await execute_command_result_writes(command_result, notion_client)
    return command_tracker_state, command_operation_keys, command_result.warnings or []


async def _run_read_task_pages(
    action_name: str,
    task_ids: list[str],
    tracker_state_path: str | Path,
    output_path: str | Path,
    credentials_path: str | Path,
    notion_client: str,
) -> "TrackerActionExecutionSummary":
    source_tracker_state_path = Path(tracker_state_path)
    destination_output_path = Path(output_path)
    tracker_state = _read_json(source_tracker_state_path)

    client = _notion_client_from_name_or_instance(credentials_path, notion_client)
    refreshed_result = await refresh_tracker_state_for_task_ids(
        task_ids=task_ids,
        tracker_state=tracker_state,
        notion_client=client,
    )
    refreshed_tracker_state = refreshed_result.tracker_state
    page_content_by_task_id = await _fetch_task_page_content_by_task_id(
        task_ids=task_ids,
        tracker_state=refreshed_tracker_state,
        notion_client=client,
    )

    _write_json(source_tracker_state_path, refreshed_tracker_state)
    read_summary = TrackerActionExecutionSummary(
        action_name=action_name,
        output_path=destination_output_path,
        tracker_state_path=source_tracker_state_path,
        tasks=[
            _task_read_item_from_tracker_state(
                task_id=task_id,
                tracker_state=refreshed_tracker_state,
                fetched_page_content=page_content_by_task_id[task_id],
            )
            for task_id in task_ids
        ],
        warnings=refreshed_result.warnings or [],
    )
    _write_json(destination_output_path, read_summary.to_json_summary())
    return read_summary


async def _fetch_task_page_content_by_task_id(
    task_ids: list[str],
    tracker_state: dict[str, Any],
    notion_client,
) -> dict[str, str]:
    page_content_by_task_id = {}
    for task_id in task_ids:
        notion_page_id = tracker_state["tasks"][task_id].get("notion_page_id")
        if notion_page_id is None:
            raise ValueError(f"Task {task_id} has no Notion page id; run notion_task update")
        page_content_by_task_id[task_id] = await notion_client.fetch_task_page_content(notion_page_id)
    return page_content_by_task_id


def _task_read_item_from_tracker_state(
    task_id: str,
    tracker_state: dict[str, Any],
    fetched_page_content: str,
) -> dict[str, Any]:
    task = tracker_state["tasks"][task_id]
    timeline_entries = parse_timeline_entries_from_fetched_task_page_content(fetched_page_content)
    return {
        "task_id": task_id,
        "ticket_number": int(task_id.removeprefix("ALOVYA-")),
        "title": task["title"],
        "status": task["status"],
        "configured_priority": task["configured_priority"],
        "displayed_priority": task["displayed_priority"],
        "parent_task_id": task["parent_task_id"],
        "child_task_ids": list(task["child_task_ids"]),
        "notion_url": _task_notion_url(task),
        "recent_timeline_headings": [
            timeline_entry["heading"]
            for timeline_entry in timeline_entries[:5]
        ],
        "summary": _summarise_fetched_page_content(fetched_page_content),
    }


def _task_notion_url(task: dict[str, Any]) -> str | None:
    notion_page_id = task.get("notion_page_id")
    if notion_page_id is None:
        return None

    return f"https://www.notion.so/{notion_page_id.replace('-', '')}"


def _summarise_fetched_page_content(fetched_page_content: str) -> list[str]:
    summary_lines = []
    inside_content = False
    for raw_line in fetched_page_content.splitlines():
        line = raw_line.strip()
        if line == "<content>":
            inside_content = True
            continue
        if line == "</content>":
            break
        if not inside_content:
            continue
        if not line or line.startswith("<") or line.startswith("#"):
            continue
        if line.startswith("- "):
            line = line[2:]
        summary_lines.append(line)
        if len(summary_lines) == 5:
            break
    return summary_lines


async def repair_and_write_refreshed_tracker_state(
    source_tracker_state_path: Path,
    destination_output_path: Path,
    destination_backup_path: Path,
    before_tracker_state: dict[str, Any],
    refreshed_result,
    notion_client,
) -> "TrackerActionExecutionSummary":
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

    refresh_summary = TrackerActionExecutionSummary(
        action_name="reconcile_from_notion",
        backup_path=destination_backup_path,
        completed_operation_keys=completed_operation_keys,
        output_path=destination_output_path,
        tracker_state_path=source_tracker_state_path,
        task_graph_changes=task_changes,
        task_count=len(repaired_tracker_state["tasks"]),
        warnings=refreshed_result.warnings or [],
        repair_operation_count=len(repair_result.write_intents),
    )
    _write_json(destination_output_path, refresh_summary.to_json_summary())
    return refresh_summary


@dataclass(frozen=True)
class TrackerActionExecutionSummary:
    action_name: str
    output_path: Path
    tracker_state_path: Path
    warnings: list[dict[str, str]]
    backup_path: Path | None = None
    completed_operation_keys: list[str] | None = None
    tasks: list[dict[str, Any]] | None = None
    task_graph_changes: list[dict[str, Any]] | None = None
    task_count: int | None = None
    repair_operation_count: int | None = None

    def to_json_summary(self) -> dict[str, Any]:
        summary = {
            "action_name": self.action_name,
            "output_path": str(self.output_path),
            "tracker_state_path": str(self.tracker_state_path),
            "warnings": list(self.warnings),
        }
        if self.backup_path is not None:
            summary["backup_path"] = str(self.backup_path)
        if self.completed_operation_keys is not None:
            summary["completed_operations"] = list(self.completed_operation_keys)
        if self.tasks is not None:
            summary["tasks"] = self.tasks
        if self.task_graph_changes is not None:
            summary["task_graph_changes"] = self.task_graph_changes
        if self.task_count is not None:
            summary["task_count"] = self.task_count
        if self.repair_operation_count is not None:
            summary["repair_operation_count"] = self.repair_operation_count
        return summary


def _action_name_from_tracker_command(command: dict[str, Any]) -> str:
    return {
        "reconcile_from_notion": "reconcile_from_notion",
        "read_tasks": "read",
        "work_task": "work",
        "append_task_timeline_log": "log",
        "complete_task": "complete",
        "cancel_task": "cancel",
        "create_top_level_task": "parent",
        "create_child_task": "child",
        "create_sibling_task": "sibling",
        "append_miscellaneous_note": "misc",
        "create_synthesis_page": "synth",
    }[command["command"]]


def _timestamped_backup_path() -> Path:
    return Path("/tmp") / f"notion_tasks_graph_before_refresh_{int(time.time())}.json"


def _read_json(source_path: Path) -> dict[str, Any]:
    return json.loads(source_path.read_text(encoding="utf-8"))


def _write_json(destination_path: Path, tracker_state: dict[str, Any]) -> None:
    destination_path.write_text(
        json.dumps(tracker_state, indent=2, sort_keys=True),
        encoding="utf-8",
    )


def _notion_client_from_name_or_instance(credentials_path: str | Path, notion_client):
    if isinstance(notion_client, str):
        return notion_client_from_credentials_path(Path(credentials_path), notion_client)

    return notion_client


if __name__ == "__main__":
    main()
