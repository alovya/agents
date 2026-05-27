"""Refresh local task tracker state from task database rows."""

from __future__ import annotations

from typing import Any

from notion_task_tracker.apply_tracker_command import TrackerCommandResult, apply_command_to_tracker_state
from notion_task_tracker.notion_io.client import NotionClient
from notion_task_tracker.tasks import TaskDependencyGraph
from notion_task_tracker.tasks.database import (
    task_database_row_from_fetched_task_database_page,
    task_dependency_graph_from_database_query_results,
)


async def refresh_tracker_state_from_task_database(
    tracker_state: dict[str, Any],
    notion_client: NotionClient,
) -> TrackerCommandResult:
    if "task_database" in tracker_state:
        return await _refresh_tracker_state_from_task_database(tracker_state, notion_client)

    raise ValueError("Task reconciliation requires task_database in tracker state")


async def refresh_tracker_state_for_command_targets(
    command: dict[str, Any],
    tracker_state: dict[str, Any],
    notion_client: NotionClient,
) -> TrackerCommandResult:
    task_ids_to_refresh = task_ids_to_refresh_before_command(command, tracker_state)
    if not task_ids_to_refresh:
        return TrackerCommandResult(tracker_state=tracker_state, warnings=[])

    work_graph = TaskDependencyGraph.from_tracker_state(tracker_state)
    refreshed_task_ids = set()
    pending_task_ids = list(dict.fromkeys(task_ids_to_refresh))

    while pending_task_ids:
        task_id = pending_task_ids.pop(0)
        if task_id in refreshed_task_ids:
            continue

        database_row = await _fetch_known_task_database_row(task_id, work_graph, notion_client)
        parent_task_id = _parent_task_id_for_fetched_database_row(database_row, work_graph)
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


def repair_result_for_task_graph_changes(
    refreshed_result: TrackerCommandResult,
    task_graph_changes: list[dict[str, Any]],
) -> TrackerCommandResult:
    if not task_graph_changes and not refreshed_result.warnings:
        return refreshed_result

    repair_result = apply_command_to_tracker_state(
        command={
            "command": "refresh_task_pages",
            "operation_keys": TaskDependencyGraph.from_tracker_state(
                refreshed_result.tracker_state
            ).repair_operation_keys_for_changes(task_graph_changes),
        },
        tracker_state=refreshed_result.tracker_state,
    )
    return TrackerCommandResult(
        tracker_state=repair_result.tracker_state,
        write_intents=repair_result.write_intents,
        page_registry=repair_result.page_registry,
        warnings=refreshed_result.warnings,
    )


async def _refresh_tracker_state_from_task_database(
    tracker_state: dict[str, Any],
    notion_client: NotionClient,
) -> TrackerCommandResult:
    previous_work_graph = TaskDependencyGraph.from_tracker_state(tracker_state)
    database_rows = await notion_client.query_task_database_rows(tracker_state)
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
    notion_client: NotionClient,
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
    parent_task_id = work_graph.task_id_for_notion_page_id(parent_page_id)
    if parent_task_id is None:
        raise ValueError(
            f"Parent page {parent_page_id} for task {database_row.task_id} is not in local tracker state; "
            "run notion_task update"
        )

    return parent_task_id
