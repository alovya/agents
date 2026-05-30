"""Refresh task tracker state from already fetched task database data."""

from __future__ import annotations

from typing import Any

from notion_task_tracker.apply_tracker_command import TrackerCommandResult
from notion_task_tracker.tasks import TaskDependencyGraph
from notion_task_tracker.tasks.database import (
    TaskDatabaseRow,
    task_dependency_graph_from_database_query_results,
)


def refresh_tracker_state_from_database_rows(
    tracker_state: dict[str, Any],
    database_rows: list[dict[str, Any]],
) -> TrackerCommandResult:
    previous_work_graph = TaskDependencyGraph.from_tracker_state(tracker_state)
    work_graph = task_dependency_graph_from_database_query_results(
        query_results=database_rows,
        landing_page=previous_work_graph.ongoing_tasks_landing_page.page,
        completed_landing_page=previous_work_graph.completed_tasks_landing_page.page,
        previous_work_graph=previous_work_graph,
    )
    return TrackerCommandResult(
        tracker_state=work_graph.replace_task_graph_in_tracker_state(tracker_state),
        warnings=[],
    )


def refresh_command_tasks_in_tracker_state(
    command: dict[str, Any],
    tracker_state: dict[str, Any],
    database_rows_by_task_id: dict[str, TaskDatabaseRow],
) -> TrackerCommandResult:
    work_graph = TaskDependencyGraph.from_tracker_state(tracker_state)
    refreshed_task_ids = set()
    pending_task_ids = list(dict.fromkeys(find_task_ids_to_refresh_before_command(command, tracker_state)))
    return _refresh_task_ids_in_work_graph(
        work_graph=work_graph,
        tracker_state=tracker_state,
        database_rows_by_task_id=database_rows_by_task_id,
        refreshed_task_ids=refreshed_task_ids,
        pending_task_ids=pending_task_ids,
    )


def refresh_task_ids_in_tracker_state(
    task_ids: list[str],
    tracker_state: dict[str, Any],
    database_rows_by_task_id: dict[str, TaskDatabaseRow],
) -> TrackerCommandResult:
    return _refresh_task_ids_in_work_graph(
        work_graph=TaskDependencyGraph.from_tracker_state(tracker_state),
        tracker_state=tracker_state,
        database_rows_by_task_id=database_rows_by_task_id,
        refreshed_task_ids=set(),
        pending_task_ids=list(dict.fromkeys(task_ids)),
    )


def _refresh_task_ids_in_work_graph(
    work_graph: TaskDependencyGraph,
    tracker_state: dict[str, Any],
    database_rows_by_task_id: dict[str, TaskDatabaseRow],
    refreshed_task_ids: set[str],
    pending_task_ids: list[str],
) -> TrackerCommandResult:
    while pending_task_ids:
        task_id = pending_task_ids.pop(0)
        if task_id in refreshed_task_ids:
            continue

        database_row = _require_database_row_for_known_task(task_id, database_rows_by_task_id, work_graph)
        parent_task_id = _derive_parent_task_id_from_database_row(database_row, work_graph)
        work_graph.refresh_task_from_database_row(
            task_id=task_id,
            title=database_row.title,
            configured_priority=database_row.configured_priority,
            status=database_row.status,
            notion_page_id=database_row.notion_page_id,
            parent_task_id=parent_task_id,
        )
        refreshed_task_ids.add(task_id)

        if parent_task_id is not None and parent_task_id not in refreshed_task_ids:
            pending_task_ids.append(parent_task_id)

    work_graph.validate()
    work_graph.recalculate_display_priorities()
    return TrackerCommandResult(
        tracker_state=work_graph.replace_task_graph_in_tracker_state(tracker_state),
        warnings=[],
    )


def find_task_ids_to_refresh_before_command(command: dict[str, Any], tracker_state: dict[str, Any]) -> list[str]:
    command_name = command["command"]
    if command_name in {"append_task_timeline_log", "complete_task", "cancel_task"}:
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


def _require_database_row_for_known_task(
    task_id: str,
    database_rows_by_task_id: dict[str, TaskDatabaseRow],
    work_graph: TaskDependencyGraph,
) -> TaskDatabaseRow:
    if task_id not in work_graph.tasks:
        raise ValueError(f"Task {task_id} is not in local tracker state; run notion_task update")

    database_row = database_rows_by_task_id[task_id]
    if database_row.task_id != task_id:
        raise ValueError(f"Task page for {task_id} now reports {database_row.task_id}; run notion_task update")

    return database_row


def _derive_parent_task_id_from_database_row(database_row: TaskDatabaseRow, work_graph: TaskDependencyGraph) -> str | None:
    if len(database_row.parent_notion_page_ids) > 1:
        raise ValueError(f"Task {database_row.task_id} has more than one parent")

    if not database_row.parent_notion_page_ids:
        return None

    parent_page_id = database_row.parent_notion_page_ids[0]
    parent_task_id = work_graph.task_id_for_notion_page_id(parent_page_id)
    if parent_task_id is None:
        raise ValueError(
            f"Parent page {parent_page_id} for task {database_row.task_id} is not in local tracker state; "
            "run notion_task update"
        )

    return parent_task_id
