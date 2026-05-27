"""Create task database pages and execute the Notion writes caused by creation."""

from __future__ import annotations

import json
from typing import Any

from notion_task_tracker.apply_tracker_command import apply_command_to_tracker_state
from notion_task_tracker.notion_operations.client import NotionClient
from notion_task_tracker.notion_operations.prepare_task_page_timeline_log_write import prepare_command_result_from_current_task_page
from notion_task_tracker.notion_operations.write_executor import execute_command_result_writes
from notion_task_tracker.tasks import TaskDependencyGraph
from notion_task_tracker.tasks.create_task import (
    TaskCreation,
    derive_task_creation_from_command,
    add_created_task_to_tracker_state,
)
from notion_task_tracker.tasks.database import (
    TASK_DATABASE_PARENT_PROPERTY,
    TASK_DATABASE_PRIORITY_PROPERTY,
    TASK_DATABASE_STATUS_PROPERTY,
    TASK_DATABASE_TITLE_PROPERTY,
    task_database_data_source_id_from_tracker_state,
    task_id_from_fetched_task_database_page,
)
from notion_task_tracker.tasks.task import TASK_PAGE_TIMELINE_LOG_HEADING
from notion_task_tracker.tasks.timeline_log import build_timeline_entry_for_date


async def execute_create_task_database_page_command(
    command: dict[str, Any],
    tracker_state: dict[str, Any],
    notion_client: NotionClient,
) -> tuple[dict[str, Any], list[str]]:
    work_graph = TaskDependencyGraph.from_tracker_state(tracker_state)
    task_creation = derive_task_creation_from_command(command, work_graph)
    created_page_id, created_task_id, create_operation_keys = await _create_database_page_and_read_ticket_id(
        task_creation=task_creation,
        tracker_state=tracker_state,
        work_graph=work_graph,
        notion_client=notion_client,
    )

    updated_tracker_state = add_created_task_to_tracker_state(
        tracker_state=tracker_state,
        task_creation=task_creation,
        created_task_id=created_task_id,
        created_page_id=created_page_id,
    )
    timeline_tracker_state, timeline_operation_keys = await _write_task_creation_timeline_entry(
        task_creation=task_creation,
        tracker_state=updated_tracker_state,
        created_task_id=created_task_id,
        notion_client=notion_client,
    )
    landing_tracker_state, landing_operation_keys = await _refresh_derived_task_landing_pages(
        timeline_tracker_state,
        notion_client,
    )
    return landing_tracker_state, create_operation_keys + timeline_operation_keys + landing_operation_keys


def should_create_task_database_page_for_command(command: dict[str, Any], tracker_state: dict[str, Any]) -> bool:
    if command.get("command") not in {
        "create_top_level_task",
        "create_child_task",
        "create_sibling_task",
    }:
        return False

    if "task_database" not in tracker_state:
        raise ValueError("Task creation requires task_database in tracker state")

    return True


async def _create_database_page_and_read_ticket_id(
    task_creation: TaskCreation,
    tracker_state: dict[str, Any],
    work_graph: TaskDependencyGraph,
    notion_client: NotionClient,
) -> tuple[str, str, list[str]]:
    create_operation_key = f"create_database_task:{task_creation.command_name}"
    created_page = await notion_client.create_task_database_page(
        data_source_id=task_database_data_source_id_from_tracker_state(tracker_state),
        properties=_build_new_task_database_row_properties(
            task_title=task_creation.task_title,
            configured_priority=task_creation.configured_priority.value,
            status=task_creation.status.value,
            parent_task_id=task_creation.parent_task_id,
            work_graph=work_graph,
        ),
        content=_render_new_task_page_initial_content(
            initial_timeline_entry=task_creation.initial_child_timeline_entry,
            parent_task_id=task_creation.parent_task_id,
            work_graph=work_graph,
        ),
        operation_key=create_operation_key,
    )
    fetched_page_content = await notion_client.fetch_task_page_content(created_page.notion_page_id)
    created_task_id = task_id_from_fetched_task_database_page(fetched_page_content)
    update_title_operation_key = f"update_properties:task:{created_task_id}"
    completed_update_operation_key = await notion_client.update_task_database_page_title(
        page_id=created_page.notion_page_id,
        title_property=TASK_DATABASE_TITLE_PROPERTY,
        title=task_creation.task_title,
        operation_key=update_title_operation_key,
    )
    return (
        created_page.notion_page_id,
        created_task_id,
        [*created_page.operation_keys, completed_update_operation_key],
    )


async def _write_task_creation_timeline_entry(
    task_creation: TaskCreation,
    tracker_state: dict[str, Any],
    created_task_id: str,
    notion_client: NotionClient,
) -> tuple[dict[str, Any], list[str]]:
    timeline_command = _build_created_task_timeline_command(
        task_creation=task_creation,
        created_task_url=_build_task_notion_url_from_tracker_state(tracker_state, created_task_id),
    )
    if timeline_command is None:
        return tracker_state, []

    timeline_owner_task_id = task_creation.parent_task_id or created_task_id
    timeline_result = await prepare_command_result_from_current_task_page(
        command={
            "command": "append_task_timeline_log",
            "task_id": timeline_owner_task_id,
            "timeline_entry": timeline_command,
        },
        tracker_state=tracker_state,
        notion_client=notion_client,
    )
    return await execute_command_result_writes(timeline_result, notion_client)


async def _refresh_derived_task_landing_pages(
    tracker_state: dict[str, Any],
    notion_client: NotionClient,
) -> tuple[dict[str, Any], list[str]]:
    landing_refresh_result = apply_command_to_tracker_state(
        command={
            "command": "refresh_task_pages",
            "operation_keys": ["replace:ongoing_landing_page", "replace:completed_landing_page"],
        },
        tracker_state=tracker_state,
    )
    return await execute_command_result_writes(landing_refresh_result, notion_client)


def _render_new_task_page_initial_content(
    initial_timeline_entry: dict[str, Any] | None,
    parent_task_id: str | None,
    work_graph: TaskDependencyGraph,
) -> str:
    if initial_timeline_entry is None or parent_task_id is None:
        return f"## {TASK_PAGE_TIMELINE_LOG_HEADING}"

    parent_page_url = _build_task_notion_url(work_graph, parent_task_id)
    return "\n".join(
        [
            f"## {TASK_PAGE_TIMELINE_LOG_HEADING}",
            f"### {build_timeline_entry_for_date(initial_timeline_entry['entry_date'])['heading']}",
            f'- Spawned from parent task: <mention-page url="{parent_page_url}"/>.',
        ]
    )


def _build_created_task_timeline_command(
    task_creation: TaskCreation,
    created_task_url: str,
) -> dict[str, Any] | None:
    if task_creation.parent_timeline_entry is None:
        return None

    if task_creation.command_name not in {"create_child_task", "create_sibling_task"}:
        return task_creation.parent_timeline_entry

    updated_timeline_command = json.loads(json.dumps(task_creation.parent_timeline_entry))
    updated_timeline_command["lines"] = [
        f'Spawned child task: <mention-page url="{created_task_url}"/>.'
    ]
    return updated_timeline_command


def _build_new_task_database_row_properties(
    task_title: str,
    configured_priority: str,
    status: str,
    parent_task_id: str | None,
    work_graph: TaskDependencyGraph,
) -> dict[str, Any]:
    properties = {
        TASK_DATABASE_TITLE_PROPERTY: task_title,
        TASK_DATABASE_PRIORITY_PROPERTY: configured_priority,
        TASK_DATABASE_STATUS_PROPERTY: status,
    }
    if parent_task_id is not None:
        properties[TASK_DATABASE_PARENT_PROPERTY] = json.dumps([
            _build_task_notion_url(work_graph, parent_task_id)
        ])
    return properties


def _build_task_notion_url(work_graph: TaskDependencyGraph, task_id: str) -> str:
    notion_page_id = work_graph.tasks[task_id].notion_page_id
    if notion_page_id is None:
        raise ValueError(f"Task {task_id} has no Notion page id")

    return f"https://www.notion.so/{notion_page_id.replace('-', '')}"


def _build_task_notion_url_from_tracker_state(tracker_state: dict[str, Any], task_id: str) -> str:
    notion_page_id = tracker_state["tasks"][task_id].get("notion_page_id")
    if notion_page_id is None:
        raise ValueError(f"Task {task_id} has no Notion page id")

    return f"https://www.notion.so/{notion_page_id.replace('-', '')}"
