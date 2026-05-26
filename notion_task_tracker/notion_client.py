"""Fetch Notion task pages and reconcile the local task dependency graph."""

from __future__ import annotations

import asyncio
import json
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from notion_task_tracker.commands import CommandResult, apply_command_to_tracker_state
from notion_task_tracker.notion_mcp_calls import NotionMcpCallPlan, NotionMcpToolCall
from notion_task_tracker.notion_mcp_client import NotionMcpClient
from notion_task_tracker.notion_rest_client import NotionRestClient
from notion_task_tracker.task_pages import TaskDependencyGraph, TimelineEntry
from notion_task_tracker.task_pages.task_database import (
    TASK_DATABASE_PARENT_PROPERTY,
    TASK_DATABASE_PRIORITY_PROPERTY,
    TASK_DATABASE_STATUS_PROPERTY,
    TASK_DATABASE_TITLE_PROPERTY,
    task_database_row_from_fetched_task_database_page,
    task_database_data_source_id_from_tracker_state,
    task_database_data_source_url_from_tracker_state,
    task_database_query_for_tracker_state,
    task_database_view_url_from_tracker_state,
    task_dependency_graph_from_database_query_results,
    task_id_from_fetched_task_database_page,
)
from notion_task_tracker.task_pages.task_metadata import (
    MENTION_DATE_START_PATTERN,
    PROPERTIES_BLOCK_PATTERN,
    TASK_PAGE_TIMELINE_LOG_HEADING,
    Priority,
    TaskPageMetadata,
    TaskStatus,
)


DEFAULT_CODEX_HOME_PATH = Path.home() / ".codex"
DEFAULT_CREDENTIALS_PATH = DEFAULT_CODEX_HOME_PATH / ".credentials.json"
DEFAULT_TRACKER_STATE_PATH = DEFAULT_CODEX_HOME_PATH / "memories" / "notion_tasks_graph.json"
DEFAULT_OUTPUT_PATH = Path("/tmp/notion_task_reconcile_result.json")


def reconcile_task_dependency_graph_from_notion(
    credentials_path: str | Path = DEFAULT_CREDENTIALS_PATH,
    tracker_state_path: str | Path = DEFAULT_TRACKER_STATE_PATH,
    output_path: str | Path = DEFAULT_OUTPUT_PATH,
    backup_path: str | Path | None = None,
    notion_transport: str = "rest",
) -> NotionTaskReconcileSummary:
    return asyncio.run(_reconcile_task_dependency_graph_from_notion(
        credentials_path=credentials_path,
        tracker_state_path=tracker_state_path,
        output_path=output_path,
        backup_path=backup_path,
        notion_transport=notion_transport,
    ))


def execute_command_file(
    command_path: str | Path,
    tracker_state_path: str | Path = DEFAULT_TRACKER_STATE_PATH,
    output_path: str | Path = DEFAULT_OUTPUT_PATH,
    credentials_path: str | Path = DEFAULT_CREDENTIALS_PATH,
    backup_path: str | Path | None = None,
    notion_transport: str = "rest",
) -> "NotionCommandExecutionSummary":
    return asyncio.run(_execute_command_file(
        command_path=command_path,
        tracker_state_path=tracker_state_path,
        output_path=output_path,
        credentials_path=credentials_path,
        backup_path=backup_path,
        notion_transport=notion_transport,
    ))


async def _execute_command_file(
    command_path: str | Path,
    tracker_state_path: str | Path,
    output_path: str | Path,
    credentials_path: str | Path,
    backup_path: str | Path | None,
    notion_transport: str,
) -> "NotionCommandExecutionSummary":
    source_command_path = Path(command_path)
    source_tracker_state_path = Path(tracker_state_path)
    destination_output_path = Path(output_path)
    destination_backup_path = Path(backup_path) if backup_path else _timestamped_backup_path()

    command = _read_json(source_command_path)
    tracker_state = _read_json(source_tracker_state_path)
    _write_json(destination_backup_path, tracker_state)

    notion_client = _notion_client_from_credentials_path(Path(credentials_path), notion_transport)
    preflight_result = await _reconcile_tracker_state_for_command_targets(
        command=command,
        tracker_state=tracker_state,
        notion_client=notion_client,
    )
    repair_result = _maybe_repair_reconciled_task_pages(
        reconcile_result=preflight_result,
        task_graph_changes=_task_graph_changes(tracker_state, preflight_result.tracker_state),
    )
    command_ready_tracker_state, completed_operation_keys = await _execute_command_result_writes(
        repair_result,
        notion_client,
    )

    if _should_create_task_through_database(command, command_ready_tracker_state):
        command_tracker_state, command_operation_keys = await _execute_database_task_creation_command(
            command=command,
            tracker_state=command_ready_tracker_state,
            notion_client=notion_client,
        )
        command_warnings = []
    else:
        command_ready_tracker_state, timeline_setup_operation_keys = await _tracker_state_ready_for_timeline_command(
            command=command,
            tracker_state=command_ready_tracker_state,
            notion_client=notion_client,
        )
        command_result = apply_command_to_tracker_state(command, command_ready_tracker_state)
        command_tracker_state, command_operation_keys = await _execute_command_result_writes(command_result, notion_client)
        command_operation_keys = timeline_setup_operation_keys + command_operation_keys
        command_warnings = command_result.warnings or []
    completed_operation_keys.extend(command_operation_keys)

    _write_json(source_tracker_state_path, command_tracker_state)
    execution_summary = NotionCommandExecutionSummary(
        backup_path=destination_backup_path,
        command_path=source_command_path,
        completed_operation_keys=completed_operation_keys,
        output_path=destination_output_path,
        tracker_state_path=source_tracker_state_path,
        warnings=list(preflight_result.warnings or []) + list(command_warnings),
    )
    _write_json(destination_output_path, execution_summary.to_json_summary())
    return execution_summary


async def _reconcile_task_dependency_graph_from_notion(
    credentials_path: str | Path,
    tracker_state_path: str | Path,
    output_path: str | Path,
    backup_path: str | Path | None,
    notion_transport: str,
) -> NotionTaskReconcileSummary:
    source_tracker_state_path = Path(tracker_state_path)
    destination_output_path = Path(output_path)
    destination_backup_path = Path(backup_path) if backup_path else _timestamped_backup_path()

    tracker_state = _read_json(source_tracker_state_path)
    _write_json(destination_backup_path, tracker_state)

    notion_client = _notion_client_from_credentials_path(Path(credentials_path), notion_transport)
    reconcile_result = await _reconcile_tracker_state_from_notion_pages(tracker_state, notion_client)

    return await _repair_and_write_reconciled_tracker_state(
        source_tracker_state_path=source_tracker_state_path,
        destination_output_path=destination_output_path,
        destination_backup_path=destination_backup_path,
        before_tracker_state=tracker_state,
        reconcile_result=reconcile_result,
        notion_client=notion_client,
    )


async def _reconcile_tracker_state_for_command_targets(
    command: dict[str, Any],
    tracker_state: dict[str, Any],
    notion_client: "_NotionClient",
) -> CommandResult:
    task_ids_to_refresh = _task_ids_to_refresh_before_command(command, tracker_state)
    if not task_ids_to_refresh:
        return CommandResult(tracker_state=tracker_state, call_plan=NotionMcpCallPlan(), warnings=[])

    work_graph = TaskDependencyGraph.from_snapshot(tracker_state)
    refreshed_task_ids = set()
    pending_task_ids = list(dict.fromkeys(task_ids_to_refresh))

    while pending_task_ids:
        task_id = pending_task_ids.pop(0)
        if task_id in refreshed_task_ids:
            continue

        database_row = await _fetch_known_task_database_row(task_id, work_graph, notion_client)
        parent_task_id = _parent_task_id_for_fetched_database_row(database_row, work_graph)
        _refresh_task_from_fetched_database_row(task_id, database_row, parent_task_id, work_graph)
        refreshed_task_ids.add(task_id)

        if parent_task_id is not None and parent_task_id not in refreshed_task_ids:
            pending_task_ids.append(parent_task_id)

    work_graph.validate()
    work_graph.recalculate_display_priorities()
    return CommandResult(
        tracker_state=_replace_task_graph_in_tracker_state(tracker_state, work_graph),
        call_plan=NotionMcpCallPlan(),
        warnings=[],
    )


async def _repair_and_write_reconciled_tracker_state(
    source_tracker_state_path: Path,
    destination_output_path: Path,
    destination_backup_path: Path,
    before_tracker_state: dict[str, Any],
    reconcile_result: CommandResult,
    notion_client: "_NotionClient",
) -> NotionTaskReconcileSummary:
    task_graph_changes = _task_graph_changes(before_tracker_state, reconcile_result.tracker_state)
    repair_result = _maybe_repair_reconciled_task_pages(
        reconcile_result=reconcile_result,
        task_graph_changes=task_graph_changes,
    )
    repaired_tracker_state, completed_operation_keys = await _execute_command_result_writes(repair_result, notion_client)
    _write_json(source_tracker_state_path, repaired_tracker_state)

    reconcile_summary = NotionTaskReconcileSummary(
        backup_path=destination_backup_path,
        completed_operation_keys=completed_operation_keys,
        output_path=destination_output_path,
        tracker_state_path=source_tracker_state_path,
        task_count=len(repaired_tracker_state["tasks"]),
        task_graph_changes=task_graph_changes,
        warnings=reconcile_result.warnings or [],
        repair_call_count=len(repair_result.call_plan.calls),
        repair_blocker_count=len(repair_result.call_plan.blocked_operations),
    )
    _write_json(destination_output_path, reconcile_summary.to_json_summary())
    return reconcile_summary


async def _execute_database_task_creation_command(
    command: dict[str, Any],
    tracker_state: dict[str, Any],
    notion_client: "_NotionClient",
) -> tuple[dict[str, Any], list[str]]:
    work_graph = TaskDependencyGraph.from_snapshot(tracker_state)
    parent_task_id = _database_task_parent_id_for_creation_command(command, work_graph)
    task_command = _database_task_command_for_creation_command(command)
    initial_timeline_entry = _initial_timeline_entry_for_created_database_task(command, parent_task_id)
    created_page_id, created_task_id, create_operation_keys = await _create_task_database_row(
        command_name=command["command"],
        task_title=task_command["title"],
        configured_priority=Priority(task_command["configured_priority"]),
        status=TaskStatus(task_command["status"]),
        initial_timeline_entry=initial_timeline_entry,
        parent_task_id=parent_task_id,
        tracker_state=tracker_state,
        work_graph=work_graph,
        notion_client=notion_client,
    )

    work_graph.add_task(
        TaskPageMetadata(
            task_id=created_task_id,
            title=task_command["title"],
            configured_priority=Priority(task_command["configured_priority"]),
            status=TaskStatus(task_command["status"]),
            timeline_entries=_timeline_entries_for_created_database_task(initial_timeline_entry),
            notion_page_id=created_page_id,
        )
    )
    if parent_task_id is not None:
        work_graph.link_parent_to_child(parent_task_id=parent_task_id, child_task_id=created_task_id)
    work_graph.validate()
    work_graph.recalculate_display_priorities()

    updated_tracker_state = _replace_task_graph_in_tracker_state(tracker_state, work_graph)
    timeline_tracker_state, timeline_operation_keys = await _append_database_task_creation_timeline_entry(
        command=command,
        tracker_state=updated_tracker_state,
        created_task_id=created_task_id,
        parent_task_id=parent_task_id,
        notion_client=notion_client,
    )
    landing_tracker_state, landing_operation_keys = await _refresh_landing_page_from_database_task_graph(
        timeline_tracker_state,
        notion_client,
    )
    return landing_tracker_state, create_operation_keys + timeline_operation_keys + landing_operation_keys


async def _create_task_database_row(
    command_name: str,
    task_title: str,
    configured_priority: Priority,
    status: TaskStatus,
    initial_timeline_entry: dict[str, Any] | None,
    parent_task_id: str | None,
    tracker_state: dict[str, Any],
    work_graph: TaskDependencyGraph,
    notion_client: "_NotionClient",
) -> tuple[str, str, list[str]]:
    create_operation_key = f"create_database_task:{command_name}"
    if hasattr(notion_client, "create_database_page"):
        created_page = await notion_client.create_database_page(
            data_source_id=task_database_data_source_id_from_tracker_state(tracker_state),
            properties=_new_task_database_row_properties(
                task_title=task_title,
                configured_priority=configured_priority,
                status=status,
                parent_task_id=parent_task_id,
                work_graph=work_graph,
            ),
            blocks=_new_task_page_initial_blocks(
                initial_timeline_entry=initial_timeline_entry,
                parent_task_id=parent_task_id,
                work_graph=work_graph,
            ),
        )
        created_page_id = created_page["id"]
        fetched_page_content = await notion_client.fetch_task_page_content(created_page_id)
        created_task_id = task_id_from_fetched_task_database_page(fetched_page_content)
        update_title_operation_key = f"update_properties:task:{created_task_id}"
        await notion_client.update_page_properties(
            page_id=created_page_id,
            properties={TASK_DATABASE_TITLE_PROPERTY: task_title},
        )
        return created_page_id, created_task_id, [create_operation_key, update_title_operation_key]

    create_result = await notion_client.send_call(
        NotionMcpToolCall(
            operation_key=create_operation_key,
            tool_name="notion-create-pages",
            arguments={
                "parent": {
                    "type": "data_source_id",
                    "data_source_id": task_database_data_source_id_from_tracker_state(tracker_state),
                },
                "pages": [
                    {
                        "properties": _new_task_database_row_properties(
                            task_title=task_title,
                            configured_priority=configured_priority,
                            status=status,
                            parent_task_id=parent_task_id,
                            work_graph=work_graph,
                        ),
                        "content": _new_task_page_initial_content(
                            initial_timeline_entry=initial_timeline_entry,
                            parent_task_id=parent_task_id,
                            work_graph=work_graph,
                        ),
                    }
                ],
            },
        )
    )
    created_page_id = _notion_page_id_from_tool_result(create_result)
    fetched_page_content = await notion_client.fetch_task_page_content(created_page_id)
    created_task_id = task_id_from_fetched_task_database_page(fetched_page_content)
    update_title_operation_key = f"update_properties:task:{created_task_id}"
    await notion_client.send_call(
        NotionMcpToolCall(
            operation_key=update_title_operation_key,
            tool_name="notion-update-page",
            arguments={
                "page_id": created_page_id,
                "command": "update_properties",
                "properties": {
                    TASK_DATABASE_TITLE_PROPERTY: task_title,
                },
            },
        )
    )
    return created_page_id, created_task_id, [create_operation_key, update_title_operation_key]


async def _append_database_task_creation_timeline_entry(
    command: dict[str, Any],
    tracker_state: dict[str, Any],
    created_task_id: str,
    parent_task_id: str | None,
    notion_client: "_NotionClient",
) -> tuple[dict[str, Any], list[str]]:
    timeline_command = _database_task_creation_timeline_command(
        command=command,
        created_task_id=created_task_id,
        tracker_state=tracker_state,
    )
    if timeline_command is None:
        return tracker_state, []

    timeline_owner_task_id = parent_task_id or created_task_id
    tracker_state, timeline_setup_operation_keys = await _tracker_state_ready_for_task_timeline_write(
        task_id=timeline_owner_task_id,
        entry_date=timeline_command["entry_date"],
        tracker_state=tracker_state,
        notion_client=notion_client,
    )
    timeline_result = apply_command_to_tracker_state(
        command={
            "command": "append_task_timeline_log",
            "task_id": timeline_owner_task_id,
            "timeline_entry": timeline_command,
        },
        tracker_state=tracker_state,
    )
    timeline_tracker_state, timeline_operation_keys = await _execute_command_result_writes(timeline_result, notion_client)
    return timeline_tracker_state, timeline_setup_operation_keys + timeline_operation_keys
async def _tracker_state_ready_for_timeline_command(
    command: dict[str, Any],
    tracker_state: dict[str, Any],
    notion_client: "_NotionClient",
) -> tuple[dict[str, Any], list[str]]:
    task_id = _task_id_whose_timeline_is_written_by_command(command)
    if task_id is None:
        return tracker_state, []

    return await _tracker_state_ready_for_task_timeline_write(
        task_id=task_id,
        entry_date=command["timeline_entry"]["entry_date"],
        tracker_state=tracker_state,
        notion_client=notion_client,
    )


async def _tracker_state_ready_for_task_timeline_write(
    task_id: str,
    entry_date: str,
    tracker_state: dict[str, Any],
    notion_client: "_NotionClient",
) -> tuple[dict[str, Any], list[str]]:
    notion_page_id = tracker_state["tasks"][task_id].get("notion_page_id")
    if notion_page_id is None:
        return tracker_state, []

    fetched_page_content = await notion_client.fetch_task_page_content(notion_page_id)
    timeline_entries = _timeline_entries_from_fetched_task_page_content(fetched_page_content)
    if _fetched_task_page_has_usable_timeline_log(fetched_page_content, timeline_entries):
        return _tracker_state_with_known_task_timeline_dates(
            task_id=task_id,
            tracker_state=tracker_state,
            timeline_entries=timeline_entries,
        ), []

    setup_operation_key = f"initialise_timeline_log:task:{task_id}:{entry_date}"
    await notion_client.send_call(
        NotionMcpToolCall(
            operation_key=setup_operation_key,
            tool_name="notion-update-page",
            arguments={
                "page_id": notion_page_id,
                "command": "replace_content",
                "new_str": _initialised_task_timeline_content(
                    entry_date=entry_date,
                    fetched_page_content=fetched_page_content,
                ),
            },
        )
    )
    return _tracker_state_with_known_task_timeline_dates(
        task_id=task_id,
        tracker_state=tracker_state,
        timeline_entries=[_timeline_entry_for_date(entry_date)],
    ), [setup_operation_key]


async def _tracker_state_with_fetched_task_timeline_dates(
    task_id: str,
    tracker_state: dict[str, Any],
    notion_client: "_NotionClient",
) -> dict[str, Any]:
    notion_page_id = tracker_state["tasks"][task_id].get("notion_page_id")
    if notion_page_id is None:
        return tracker_state

    fetched_page_content = await notion_client.fetch_task_page_content(notion_page_id)
    return _tracker_state_with_known_task_timeline_dates(
        task_id=task_id,
        tracker_state=tracker_state,
        timeline_entries=_timeline_entries_from_fetched_task_page_content(fetched_page_content),
    )


def _task_id_whose_timeline_is_written_by_command(command: dict[str, Any]) -> str | None:
    if command["command"] in {"append_task_timeline_log", "complete_task"}:
        return command["task_id"]

    return None


async def _refresh_landing_page_from_database_task_graph(
    tracker_state: dict[str, Any],
    notion_client: "_NotionClient",
) -> tuple[dict[str, Any], list[str]]:
    landing_refresh_result = apply_command_to_tracker_state(
        command={
            "command": "refresh_task_pages",
            "operation_keys": ["replace:landing_page", "replace:completed_landing_page"],
        },
        tracker_state=tracker_state,
    )
    return await _execute_command_result_writes(landing_refresh_result, notion_client)


async def _execute_command_result_writes(
    command_result: CommandResult,
    notion_client: "_NotionClient",
) -> tuple[dict[str, Any], list[str]]:
    if _should_execute_write_intents_with_rest(command_result, notion_client):
        completed_operation_keys, captured_page_ids = await _execute_write_intents_with_notion_rest_client(
            command_result,
            notion_client,
        )
    else:
        completed_operation_keys, captured_page_ids = await _execute_available_calls_with_notion_client(
            command_result.call_plan,
            notion_client,
        )
    tracker_state_with_page_ids = _record_captured_page_ids(command_result.tracker_state, captured_page_ids)
    if not command_result.call_plan.blocked_operations:
        return tracker_state_with_page_ids, completed_operation_keys

    refresh_result = apply_command_to_tracker_state(
        _refresh_command_for_captured_page_ids(captured_page_ids, tracker_state_with_page_ids),
        tracker_state_with_page_ids,
    )
    refresh_tracker_state, refresh_operation_keys = await _execute_command_result_writes(refresh_result, notion_client)
    return refresh_tracker_state, completed_operation_keys + refresh_operation_keys


def _should_execute_write_intents_with_rest(
    command_result: CommandResult,
    notion_client: "_NotionClient",
) -> bool:
    return bool(command_result.write_intents) and hasattr(notion_client, "execute_write_intent")


async def _execute_write_intents_with_notion_rest_client(
    command_result: CommandResult,
    notion_client: "_NotionClient",
) -> tuple[list[str], dict[str, str]]:
    if command_result.page_registry is None:
        raise ValueError("REST write execution requires a page registry")

    completed_operation_keys = []
    captured_page_ids = {}
    for write_intent in command_result.write_intents:
        write_result = await notion_client.execute_write_intent(write_intent, command_result.page_registry)
        completed_operation_keys.append(write_result["operation_key"])
        if write_result.get("captured_page_key") is not None:
            captured_page_ids[write_result["captured_page_key"]] = write_result["captured_page_id"]

    return completed_operation_keys, captured_page_ids


def _raise_if_call_plan_has_blocked_operations(call_plan: NotionMcpCallPlan) -> None:
    if not call_plan.blocked_operations:
        return

    raise ValueError(
        json.dumps(
            {
                "blocked_operations": [
                    blocked_operation.to_snapshot()
                    for blocked_operation in call_plan.blocked_operations
                ],
            },
            indent=2,
            sort_keys=True,
        )
    )


async def _execute_call_plan_with_notion_client(
    call_plan: NotionMcpCallPlan,
    notion_client: "_NotionClient",
) -> list[str]:
    _raise_if_call_plan_has_blocked_operations(call_plan)
    completed_operation_keys, _captured_page_ids = await _execute_available_calls_with_notion_client(
        call_plan,
        notion_client,
    )
    return completed_operation_keys


async def _execute_available_calls_with_notion_client(
    call_plan: NotionMcpCallPlan,
    notion_client: "_NotionClient",
) -> tuple[list[str], dict[str, str]]:
    completed_operation_keys = []
    captured_page_ids = {}
    for tool_call in call_plan.calls:
        tool_result = await notion_client.send_call(tool_call)
        completed_operation_keys.append(tool_call.operation_key)
        if tool_call.captures_page_key is not None:
            captured_page_ids[tool_call.captures_page_key] = _notion_page_id_from_tool_result(tool_result)
    return completed_operation_keys, captured_page_ids


def _record_captured_page_ids(
    tracker_state: dict[str, Any],
    captured_page_ids: dict[str, str],
) -> dict[str, Any]:
    updated_tracker_state = tracker_state
    for local_page_key, notion_page_id in captured_page_ids.items():
        updated_tracker_state = apply_command_to_tracker_state(
            {
                "command": "record_page_id",
                "local_page_key": local_page_key,
                "notion_page_id": notion_page_id,
            },
            updated_tracker_state,
        ).tracker_state
    return updated_tracker_state


def _refresh_command_for_captured_page_ids(
    captured_page_ids: dict[str, str],
    tracker_state: dict[str, Any],
) -> dict[str, Any]:
    captured_page_key_prefixes = {
        local_page_key.split(":", 1)[0]
        for local_page_key in captured_page_ids
    }
    if captured_page_key_prefixes == {"completed_landing_page"}:
        return {
            "command": "refresh_task_pages",
            "operation_keys": ["replace:completed_landing_page"],
        }

    if captured_page_key_prefixes == {"miscellaneous"}:
        return {"command": "refresh_miscellaneous_pages"}

    if captured_page_key_prefixes == {"synthesis"}:
        return {"command": "refresh_synthesis_pages"}

    raise ValueError(f"Cannot refresh mixed captured page keys {sorted(captured_page_ids)}")


def _should_create_task_through_database(command: dict[str, Any], tracker_state: dict[str, Any]) -> bool:
    if command.get("command") not in {
        "create_top_level_task",
        "create_child_task",
        "create_sibling_task",
    }:
        return False

    if "task_database" not in tracker_state:
        raise ValueError("Task creation requires task_database in tracker state")

    return True


def _database_task_parent_id_for_creation_command(
    command: dict[str, Any],
    work_graph: TaskDependencyGraph,
) -> str | None:
    command_name = command["command"]
    if command_name == "create_top_level_task":
        return None

    if command_name == "create_child_task":
        return command["parent_task_id"]

    if command_name == "create_sibling_task":
        return work_graph.tasks[command["sibling_task_id"]].parent_task_id

    raise ValueError(f"Unsupported database task creation command {command_name!r}")


def _database_task_command_for_creation_command(command: dict[str, Any]) -> dict[str, Any]:
    command_name = command["command"]
    if command_name == "create_top_level_task":
        return command["task"]

    if command_name == "create_child_task":
        return command["child_task"]

    if command_name == "create_sibling_task":
        return command["sibling_task"]

    raise ValueError(f"Unsupported database task creation command {command_name!r}")


def _initial_timeline_entry_for_created_database_task(
    command: dict[str, Any],
    parent_task_id: str | None,
) -> dict[str, Any] | None:
    if parent_task_id is None:
        return None

    return _raw_database_task_creation_timeline_command(command)


def _timeline_entries_for_created_database_task(
    initial_timeline_entry: dict[str, Any] | None,
) -> list[TimelineEntry]:
    if initial_timeline_entry is None:
        return []

    timeline_entry = _timeline_entry_for_date(initial_timeline_entry["entry_date"])
    return [
        TimelineEntry(
            entry_date=timeline_entry["entry_date"],
            heading=timeline_entry["heading"],
        )
    ]


def _database_task_creation_timeline_command(
    command: dict[str, Any],
    created_task_id: str,
    tracker_state: dict[str, Any],
) -> dict[str, Any] | None:
    timeline_command = _raw_database_task_creation_timeline_command(command)
    if timeline_command is None:
        return None

    if command["command"] not in {"create_child_task", "create_sibling_task"}:
        return timeline_command

    return _timeline_command_with_created_task_link(timeline_command, created_task_id, tracker_state)


def _raw_database_task_creation_timeline_command(command: dict[str, Any]) -> dict[str, Any] | None:
    command_name = command["command"]
    if command_name == "create_child_task":
        return command.get("parent_timeline_entry")

    return command.get("timeline_entry")


def _timeline_command_with_created_task_link(
    timeline_command: dict[str, Any],
    created_task_id: str,
    tracker_state: dict[str, Any],
) -> dict[str, Any]:
    updated_timeline_command = json.loads(json.dumps(timeline_command))
    child_page_url = _task_notion_url_from_tracker_state(tracker_state, created_task_id)
    updated_timeline_command["lines"] = [
        f'Spawned child task: <mention-page url="{child_page_url}"/>.'
    ]
    return updated_timeline_command


def _new_task_page_initial_content(
    initial_timeline_entry: dict[str, Any] | None,
    parent_task_id: str | None,
    work_graph: TaskDependencyGraph,
) -> str:
    if initial_timeline_entry is None or parent_task_id is None:
        return f"## {TASK_PAGE_TIMELINE_LOG_HEADING}"

    parent_page_url = _task_notion_url(work_graph, parent_task_id)
    return "\n".join(
        [
            f"## {TASK_PAGE_TIMELINE_LOG_HEADING}",
            f"### {_timeline_entry_for_date(initial_timeline_entry['entry_date'])['heading']}",
            f'- Spawned from parent task: <mention-page url="{parent_page_url}"/>.',
        ]
    )


def _new_task_page_initial_blocks(
    initial_timeline_entry: dict[str, Any] | None,
    parent_task_id: str | None,
    work_graph: TaskDependencyGraph,
) -> list[dict[str, Any]]:
    blocks = [{"type": "heading_2", "text": TASK_PAGE_TIMELINE_LOG_HEADING}]
    if initial_timeline_entry is None or parent_task_id is None:
        return blocks

    parent_page_url = _task_notion_url(work_graph, parent_task_id)
    blocks.extend([
        {
            "type": "heading_3",
            "text": _timeline_entry_for_date(initial_timeline_entry["entry_date"])["heading"],
        },
        {
            "type": "bulleted_list_item",
            "depth": 0,
            "text": f'Spawned from parent task: <mention-page url="{parent_page_url}"/>.',
        },
    ])
    return blocks


def _new_task_database_row_properties(
    task_title: str,
    configured_priority: Priority,
    status: TaskStatus,
    parent_task_id: str | None,
    work_graph: TaskDependencyGraph,
) -> dict[str, Any]:
    properties = {
        TASK_DATABASE_TITLE_PROPERTY: task_title,
        TASK_DATABASE_PRIORITY_PROPERTY: configured_priority.value,
        TASK_DATABASE_STATUS_PROPERTY: status.value,
    }
    if parent_task_id is not None:
        properties[TASK_DATABASE_PARENT_PROPERTY] = json.dumps([
            _task_notion_url(work_graph, parent_task_id)
        ])
    return properties


def _task_notion_url(work_graph: TaskDependencyGraph, task_id: str) -> str:
    notion_page_id = work_graph.tasks[task_id].notion_page_id
    if notion_page_id is None:
        raise ValueError(f"Task {task_id} has no Notion page id")

    return f"https://www.notion.so/{notion_page_id.replace('-', '')}"


def _task_notion_url_from_tracker_state(tracker_state: dict[str, Any], task_id: str) -> str:
    notion_page_id = tracker_state["tasks"][task_id].get("notion_page_id")
    if notion_page_id is None:
        raise ValueError(f"Task {task_id} has no Notion page id")

    return f"https://www.notion.so/{notion_page_id.replace('-', '')}"


def _notion_page_id_from_tool_result(tool_result: dict[str, Any]) -> str:
    tool_text = str(tool_result.get("result", {}).get("text", ""))
    page_id_match = re.search(
        r"(?P<page_id>[0-9a-fA-F]{32}|[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})",
        tool_text,
    )
    if page_id_match is None:
        raise ValueError(f"Could not find Notion page id in tool result {tool_result!r}")

    return page_id_match.group("page_id").replace("-", "")


@dataclass(frozen=True)
class NotionTaskReconcileSummary:
    backup_path: Path
    completed_operation_keys: list[str]
    output_path: Path
    tracker_state_path: Path
    task_count: int
    task_graph_changes: list[dict[str, Any]]
    warnings: list[dict[str, str]]
    repair_call_count: int
    repair_blocker_count: int

    def to_json_summary(self) -> dict[str, Any]:
        return {
            "backup_path": str(self.backup_path),
            "completed_operations": list(self.completed_operation_keys),
            "output_path": str(self.output_path),
            "tracker_state_path": str(self.tracker_state_path),
            "task_count": self.task_count,
            "task_graph_changes": self.task_graph_changes,
            "warnings": self.warnings,
            "repair_call_count": self.repair_call_count,
            "repair_blocker_count": self.repair_blocker_count,
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


async def _reconcile_tracker_state_from_notion_pages(
    tracker_state: dict[str, Any],
    notion_client: "_NotionClient",
) -> CommandResult:
    if "task_database" in tracker_state:
        return await _reconcile_tracker_state_from_task_database(tracker_state, notion_client)

    raise ValueError("Task reconciliation requires task_database in tracker state")


async def _reconcile_tracker_state_from_task_database(
    tracker_state: dict[str, Any],
    notion_client: "_NotionClient",
) -> CommandResult:
    previous_work_graph = TaskDependencyGraph.from_snapshot(tracker_state)
    database_rows = await _query_task_database_rows(tracker_state, notion_client)
    work_graph = task_dependency_graph_from_database_query_results(
        query_results=database_rows,
        landing_page=previous_work_graph.landing_page,
        completed_landing_page=previous_work_graph.completed_landing_page,
        previous_work_graph=previous_work_graph,
    )
    return CommandResult(
        tracker_state=_replace_task_graph_in_tracker_state(tracker_state, work_graph),
        call_plan=NotionMcpCallPlan(),
        warnings=[],
    )


async def _query_task_database_rows(
    tracker_state: dict[str, Any],
    notion_client: "_NotionClient",
) -> list[dict[str, Any]]:
    view_url = task_database_view_url_from_tracker_state(tracker_state)
    if view_url is not None:
        return await notion_client.query_database_view(view_url)

    return await notion_client.query_data_source(
        data_source_url=task_database_data_source_url_from_tracker_state(tracker_state),
        query=task_database_query_for_tracker_state(tracker_state),
    )


def _task_ids_to_refresh_before_command(command: dict[str, Any], tracker_state: dict[str, Any]) -> list[str]:
    command_name = command["command"]
    if command_name in {"append_task_timeline_log", "complete_task"}:
        return [command["task_id"]]

    if command_name == "create_child_task":
        return [command["parent_task_id"]]

    if command_name == "create_sibling_task":
        sibling_task_id = command["sibling_task_id"]
        sibling_task = tracker_state.get("tasks", {}).get(sibling_task_id, {})
        task_ids = [sibling_task_id]
        if sibling_task.get("parent_task_id") is not None:
            task_ids.append(sibling_task["parent_task_id"])
        return task_ids

    return []


async def _fetch_known_task_database_row(
    task_id: str,
    work_graph: TaskDependencyGraph,
    notion_client: "_NotionClient",
):
    if task_id not in work_graph.tasks:
        raise ValueError(f"Task {task_id} is not in local tracker state; run notion_task update")

    notion_page_id = work_graph.tasks[task_id].notion_page_id
    if notion_page_id is None:
        raise ValueError(f"Task {task_id} has no Notion page id; run notion_task update")

    fetched_page_content = await notion_client.fetch_task_page_content(notion_page_id)
    database_row = task_database_row_from_fetched_task_database_page(
        fetched_page_content=fetched_page_content,
        notion_page_id=notion_page_id,
    )
    if database_row.task_id != task_id:
        raise ValueError(f"Task page for {task_id} now reports {database_row.task_id}; run notion_task update")

    return database_row


def _parent_task_id_for_fetched_database_row(database_row, work_graph: TaskDependencyGraph) -> str | None:
    if len(database_row.parent_notion_page_ids) > 1:
        raise ValueError(f"Task {database_row.task_id} has more than one parent")

    if not database_row.parent_notion_page_ids:
        return None

    parent_page_id = database_row.parent_notion_page_ids[0]
    parent_task_id = _task_id_for_notion_page_id(parent_page_id, work_graph)
    if parent_task_id is None:
        raise ValueError(
            f"Parent page {parent_page_id} for task {database_row.task_id} is not in local tracker state; "
            "run notion_task update"
        )

    return parent_task_id


def _refresh_task_from_fetched_database_row(
    task_id: str,
    database_row,
    parent_task_id: str | None,
    work_graph: TaskDependencyGraph,
) -> None:
    task = work_graph.tasks[task_id]
    task.title = database_row.title
    task.configured_priority = database_row.configured_priority
    task.status = database_row.status
    task.notion_page_id = database_row.notion_page_id
    work_graph.set_task_parent(task_id, parent_task_id)


def _task_id_for_notion_page_id(
    notion_page_id: str,
    work_graph: TaskDependencyGraph,
) -> str | None:
    target_page_id = _compact_notion_page_id(notion_page_id)
    for task in work_graph.tasks.values():
        if task.notion_page_id is None:
            continue
        if _compact_notion_page_id(task.notion_page_id) == target_page_id:
            return task.task_id

    return None


def _compact_notion_page_id(notion_page_id: str) -> str:
    return notion_page_id.replace("-", "").lower()


def _maybe_repair_reconciled_task_pages(
    reconcile_result: CommandResult,
    task_graph_changes: list[dict[str, Any]],
) -> CommandResult:
    if not task_graph_changes and not reconcile_result.warnings:
        return reconcile_result

    repair_result = apply_command_to_tracker_state(
        command={
            "command": "refresh_task_pages",
            "operation_keys": _repair_operation_keys_for_reconciled_task_pages(
                tracker_state=reconcile_result.tracker_state,
                task_graph_changes=task_graph_changes,
            ),
        },
        tracker_state=reconcile_result.tracker_state,
    )
    return CommandResult(
        tracker_state=repair_result.tracker_state,
        call_plan=repair_result.call_plan,
        warnings=reconcile_result.warnings,
    )


def _repair_operation_keys_for_reconciled_task_pages(
    tracker_state: dict[str, Any],
    task_graph_changes: list[dict[str, Any]],
) -> list[str]:
    task_ids_to_repair = set()

    for task_graph_change in task_graph_changes:
        task_id = task_graph_change["task_id"]
        task_ids_to_repair.add(task_id)
        task_ids_to_repair.update(_ancestor_task_ids(tracker_state, task_id))

        changed_fields = set(task_graph_change.get("fields", {}))
        if "parent_task_id" in changed_fields:
            task_ids_to_repair.update(_parent_task_ids_from_change(task_graph_change))

    return [
        "replace:landing_page",
        "replace:completed_landing_page",
        *[
            operation_key
            for task_id in sorted(task_ids_to_repair, key=_task_id_sort_key)
            for operation_key in [f"update_properties:task:{task_id}"]
            if task_id in tracker_state["tasks"]
        ],
    ]


def _ancestor_task_ids(tracker_state: dict[str, Any], task_id: str) -> list[str]:
    ancestor_task_ids = []
    current_task = tracker_state["tasks"].get(task_id)

    while current_task and current_task.get("parent_task_id") is not None:
        parent_task_id = current_task["parent_task_id"]
        ancestor_task_ids.append(parent_task_id)
        current_task = tracker_state["tasks"].get(parent_task_id)

    return ancestor_task_ids


def _parent_task_ids_from_change(task_graph_change: dict[str, Any]) -> list[str]:
    parent_change = task_graph_change.get("fields", {}).get("parent_task_id", {})
    return [
        task_id
        for task_id in [parent_change.get("before"), parent_change.get("after")]
        if task_id is not None
    ]


def _call_plan_from_json(call: dict[str, Any]) -> NotionMcpCallPlan:
    if "call_plan" in call:
        return NotionMcpCallPlan.from_snapshot(call["call_plan"])

    return NotionMcpCallPlan.from_snapshot(call)


def _notion_client_from_credentials_path(credentials_path: Path, notion_transport: str = "rest") -> "_NotionClient":
    if notion_transport == "rest":
        return NotionRestClient.from_credentials_path(credentials_path)

    if notion_transport == "mcp":
        # TODO: Delete the MCP transport once REST has proved reliable for task creation, logging, completion, reconciliation, and landing-page rendering.
        return NotionMcpClient.from_credentials_path(credentials_path)

    raise ValueError(f"Unsupported Notion transport {notion_transport!r}")


class _NotionClient:
    async def fetch_task_page_content(self, page_id: str) -> str:
        raise NotImplementedError

    async def query_data_source(self, data_source_url: str, query: str) -> list[dict[str, Any]]:
        raise NotImplementedError

    async def query_database_view(self, view_url: str) -> list[dict[str, Any]]:
        raise NotImplementedError

    async def send_call(self, tool_call: NotionMcpToolCall) -> dict[str, Any]:
        raise NotImplementedError


def _replace_task_graph_in_tracker_state(
    tracker_state: dict[str, Any],
    work_graph: TaskDependencyGraph,
) -> dict[str, Any]:
    updated_tracker_state = json.loads(json.dumps(tracker_state))
    task_graph_state = work_graph.to_snapshot()
    updated_tracker_state["landing_page"] = task_graph_state["landing_page"]
    updated_tracker_state["completed_landing_page"] = task_graph_state["completed_landing_page"]
    updated_tracker_state["tasks"] = task_graph_state["tasks"]
    return updated_tracker_state


def _tracker_state_with_known_task_timeline_dates(
    task_id: str,
    tracker_state: dict[str, Any],
    timeline_entries: list[dict[str, str]],
) -> dict[str, Any]:
    if not timeline_entries:
        return tracker_state

    updated_tracker_state = json.loads(json.dumps(tracker_state))
    task_timeline_entries = updated_tracker_state["tasks"][task_id].setdefault("timeline_entries", [])
    known_entry_dates = {
        timeline_entry["entry_date"]
        for timeline_entry in task_timeline_entries
    }

    for timeline_entry in timeline_entries:
        if timeline_entry["entry_date"] in known_entry_dates:
            continue

        task_timeline_entries.append({
            "entry_date": timeline_entry["entry_date"],
            "heading": timeline_entry["heading"],
            "lines": [],
        })
        known_entry_dates.add(timeline_entry["entry_date"])

    return updated_tracker_state


def _timeline_entries_from_fetched_task_page_content(fetched_page_content: str) -> list[dict[str, str]]:
    timeline_content = _timeline_log_content_from_fetched_task_page_content(fetched_page_content)
    if timeline_content is None:
        return []

    timeline_entries = []
    seen_entry_dates = set()
    for heading in _markdown_headings_from_content(timeline_content):
        entry_date = _entry_date_from_timeline_heading(heading)
        if entry_date is None or entry_date in seen_entry_dates:
            continue

        timeline_entries.append({
            "entry_date": entry_date,
            "heading": heading,
        })
        seen_entry_dates.add(entry_date)

    return timeline_entries


def _fetched_task_page_has_usable_timeline_log(
    fetched_page_content: str,
    timeline_entries: list[dict[str, str]],
) -> bool:
    return _timeline_log_content_from_fetched_task_page_content(fetched_page_content) is not None and bool(timeline_entries)


def _initialised_task_timeline_content(entry_date: str, fetched_page_content: str) -> str:
    timeline_heading = f"## {TASK_PAGE_TIMELINE_LOG_HEADING}"
    date_heading = _timeline_entry_for_date(entry_date)["heading"]
    existing_body_content = _body_content_to_subsume_under_initial_timeline_date(fetched_page_content)
    if not existing_body_content:
        return "\n".join([timeline_heading, f"### {date_heading}"])

    return "\n".join([timeline_heading, f"### {date_heading}", "", existing_body_content])


def _timeline_entry_for_date(entry_date: str) -> dict[str, str]:
    return {
        "entry_date": entry_date,
        "heading": f'<mention-date start="{entry_date}"/>',
    }


def _body_content_to_subsume_under_initial_timeline_date(fetched_page_content: str) -> str:
    body_content = _body_content_from_fetched_task_page_content(fetched_page_content)
    existing_timeline_content = _timeline_log_content_from_body_content(body_content)
    if existing_timeline_content is None:
        return body_content.strip()

    return _content_below_first_markdown_heading(existing_timeline_content).strip()


def _body_content_from_fetched_task_page_content(fetched_page_content: str) -> str:
    content_match = re.search(r"<content>\s*(?P<content>.*?)\s*</content>", fetched_page_content, re.DOTALL)
    if content_match is not None:
        return content_match.group("content").strip()

    content_without_properties = PROPERTIES_BLOCK_PATTERN.sub("", fetched_page_content)
    content_without_page_tags = re.sub(r"(?m)^\s*</?page[^>]*>\s*$", "", content_without_properties)
    return content_without_page_tags.strip()


def _timeline_log_content_from_fetched_task_page_content(fetched_page_content: str) -> str | None:
    return _timeline_log_content_from_body_content(_body_content_from_fetched_task_page_content(fetched_page_content))


def _timeline_log_content_from_body_content(body_content: str) -> str | None:
    timeline_heading_match = re.search(
        rf"(?m)^##\s+{re.escape(TASK_PAGE_TIMELINE_LOG_HEADING)}\s*$",
        body_content,
    )
    if timeline_heading_match is None:
        return None

    return body_content[timeline_heading_match.start():]


def _content_below_first_markdown_heading(content: str) -> str:
    lines = content.splitlines()
    if not lines:
        return ""

    return "\n".join(lines[1:])


def _markdown_headings_from_content(content: str) -> list[str]:
    headings = []
    for line in content.splitlines():
        heading_match = re.match(r"\s*#{1,6}\s+(?P<heading>.+?)\s*$", line)
        if heading_match is None:
            continue

        headings.append(heading_match.group("heading"))
    return headings


def _entry_date_from_timeline_heading(heading: str) -> str | None:
    mention_date_match = MENTION_DATE_START_PATTERN.search(heading)
    if mention_date_match is not None:
        return mention_date_match.group(1)

    plain_date_match = re.fullmatch(r"\d{4}-\d{2}-\d{2}", heading)
    if plain_date_match is not None:
        return plain_date_match.group(0)

    return None


def _task_graph_changes(before_tracker_state: dict[str, Any], after_tracker_state: dict[str, Any]) -> list[dict[str, Any]]:
    changes = []
    before_tasks = before_tracker_state["tasks"]
    after_tasks = after_tracker_state["tasks"]

    for task_id in sorted(set(before_tasks) | set(after_tasks), key=_task_id_sort_key):
        before_task = before_tasks.get(task_id)
        after_task = after_tasks.get(task_id)

        if before_task is None:
            changes.append({"task_id": task_id, "change": "added"})
            continue

        if after_task is None:
            changes.append({"task_id": task_id, "change": "removed"})
            continue

        changed_fields = _changed_task_graph_fields(before_task, after_task)
        if changed_fields:
            changes.append({"task_id": task_id, "fields": changed_fields})

    return changes


def _changed_task_graph_fields(
    before_task: dict[str, Any],
    after_task: dict[str, Any],
) -> dict[str, dict[str, Any]]:
    changed_fields = {}
    for field_name in ["parent_task_id", "child_task_ids", "configured_priority", "status", "title"]:
        if before_task.get(field_name) != after_task.get(field_name):
            changed_fields[field_name] = {
                "before": before_task.get(field_name),
                "after": after_task.get(field_name),
            }
    return changed_fields


def _task_id_sort_key(task_id: str) -> tuple[str, int, str]:
    task_prefix, separator, task_number_text = task_id.rpartition("-")

    if separator and task_number_text.isdigit():
        return task_prefix, int(task_number_text), ""

    return task_id, -1, task_id


def _timestamped_backup_path() -> Path:
    return Path("/tmp") / f"notion_tasks_graph_before_reconcile_{int(time.time())}.json"


def _read_json(source_path: Path) -> dict[str, Any]:
    return json.loads(source_path.read_text(encoding="utf-8"))


def _write_json(destination_path: Path, tracker_state: dict[str, Any]) -> None:
    destination_path.write_text(
        json.dumps(tracker_state, indent=2, sort_keys=True),
        encoding="utf-8",
    )
