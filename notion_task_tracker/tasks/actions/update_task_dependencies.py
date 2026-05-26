"""Reconcile task graph metadata from Notion task database state."""

from __future__ import annotations

import json
from typing import Any

from notion_task_tracker.commands import CommandResult, apply_command_to_tracker_state
from notion_task_tracker.notion_transport import NotionTransport
from notion_task_tracker.tasks import TaskDependencyGraph
from notion_task_tracker.tasks.database import (
    task_database_row_from_fetched_task_database_page,
    task_dependency_graph_from_database_query_results,
)


async def reconcile_tracker_state_from_notion_pages(
    tracker_state: dict[str, Any],
    notion_transport: NotionTransport,
) -> CommandResult:
    if "task_database" in tracker_state:
        return await _reconcile_tracker_state_from_task_database(tracker_state, notion_transport)

    raise ValueError("Task reconciliation requires task_database in tracker state")


async def reconcile_tracker_state_for_command_targets(
    command: dict[str, Any],
    tracker_state: dict[str, Any],
    notion_transport: NotionTransport,
) -> CommandResult:
    task_ids_to_refresh = task_ids_to_refresh_before_command(command, tracker_state)
    if not task_ids_to_refresh:
        return CommandResult(tracker_state=tracker_state, warnings=[])

    work_graph = TaskDependencyGraph.from_snapshot(tracker_state)
    refreshed_task_ids = set()
    pending_task_ids = list(dict.fromkeys(task_ids_to_refresh))

    while pending_task_ids:
        task_id = pending_task_ids.pop(0)
        if task_id in refreshed_task_ids:
            continue

        database_row = await _fetch_known_task_database_row(task_id, work_graph, notion_transport)
        parent_task_id = _parent_task_id_for_fetched_database_row(database_row, work_graph)
        _refresh_task_from_fetched_database_row(task_id, database_row, parent_task_id, work_graph)
        refreshed_task_ids.add(task_id)

        if parent_task_id is not None and parent_task_id not in refreshed_task_ids:
            pending_task_ids.append(parent_task_id)

    work_graph.validate()
    work_graph.recalculate_display_priorities()
    return CommandResult(
        tracker_state=replace_task_graph_in_tracker_state(tracker_state, work_graph),
        warnings=[],
    )


def maybe_repair_reconciled_task_pages(
    reconcile_result: CommandResult,
    task_graph_changes: list[dict[str, Any]],
) -> CommandResult:
    if not task_graph_changes and not reconcile_result.warnings:
        return reconcile_result

    repair_result = apply_command_to_tracker_state(
        command={
            "command": "refresh_task_pages",
            "operation_keys": repair_operation_keys_for_reconciled_task_pages(
                tracker_state=reconcile_result.tracker_state,
                task_graph_changes=task_graph_changes,
            ),
        },
        tracker_state=reconcile_result.tracker_state,
    )
    return CommandResult(
        tracker_state=repair_result.tracker_state,
        write_intents=repair_result.write_intents,
        page_registry=repair_result.page_registry,
        warnings=reconcile_result.warnings,
    )


def task_graph_changes(before_tracker_state: dict[str, Any], after_tracker_state: dict[str, Any]) -> list[dict[str, Any]]:
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


def repair_operation_keys_for_reconciled_task_pages(
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


def replace_task_graph_in_tracker_state(
    tracker_state: dict[str, Any],
    work_graph: TaskDependencyGraph,
) -> dict[str, Any]:
    updated_tracker_state = json.loads(json.dumps(tracker_state))
    task_graph_state = work_graph.to_snapshot()
    updated_tracker_state["landing_page"] = task_graph_state["landing_page"]
    updated_tracker_state["completed_landing_page"] = task_graph_state["completed_landing_page"]
    updated_tracker_state["tasks"] = task_graph_state["tasks"]
    return updated_tracker_state


async def _reconcile_tracker_state_from_task_database(
    tracker_state: dict[str, Any],
    notion_transport: NotionTransport,
) -> CommandResult:
    previous_work_graph = TaskDependencyGraph.from_snapshot(tracker_state)
    database_rows = await notion_transport.query_task_database_rows(tracker_state)
    work_graph = task_dependency_graph_from_database_query_results(
        query_results=database_rows,
        landing_page=previous_work_graph.landing_page,
        completed_landing_page=previous_work_graph.completed_landing_page,
        previous_work_graph=previous_work_graph,
    )
    return CommandResult(
        tracker_state=replace_task_graph_in_tracker_state(tracker_state, work_graph),
        warnings=[],
    )


def task_ids_to_refresh_before_command(command: dict[str, Any], tracker_state: dict[str, Any]) -> list[str]:
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
    notion_transport: NotionTransport,
):
    if task_id not in work_graph.tasks:
        raise ValueError(f"Task {task_id} is not in local tracker state; run notion_task update")

    notion_page_id = work_graph.tasks[task_id].notion_page_id
    if notion_page_id is None:
        raise ValueError(f"Task {task_id} has no Notion page id; run notion_task update")

    fetched_page_content = await notion_transport.fetch_task_page_content(notion_page_id)
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
