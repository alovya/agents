"""Create task database pages and update derived task views."""

from __future__ import annotations

import json
from typing import Any

from notion_task_tracker.commands import apply_command_to_tracker_state
from notion_task_tracker.notion_transport import NotionTransport
from notion_task_tracker.notion_write_executor import execute_command_result_writes
from notion_task_tracker.tasks.actions.write_log import command_result_from_current_notion_state
from notion_task_tracker.tasks.pages import TaskDependencyGraph, TaskPageMetadata, TimelineEntry
from notion_task_tracker.tasks.pages.task_database import (
    TASK_DATABASE_PARENT_PROPERTY,
    TASK_DATABASE_PRIORITY_PROPERTY,
    TASK_DATABASE_STATUS_PROPERTY,
    TASK_DATABASE_TITLE_PROPERTY,
    task_database_data_source_id_from_tracker_state,
    task_id_from_fetched_task_database_page,
)
from notion_task_tracker.tasks.pages.task_metadata import (
    TASK_PAGE_TIMELINE_LOG_HEADING,
    Priority,
    TaskStatus,
)
from notion_task_tracker.tasks.pages.task_page_content import timeline_entry_for_date
from notion_task_tracker.tasks.actions.update_task_dependencies import replace_task_graph_in_tracker_state


async def execute_database_task_creation_command(
    command: dict[str, Any],
    tracker_state: dict[str, Any],
    notion_transport: NotionTransport,
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
        notion_transport=notion_transport,
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

    updated_tracker_state = replace_task_graph_in_tracker_state(tracker_state, work_graph)
    timeline_tracker_state, timeline_operation_keys = await _append_database_task_creation_timeline_entry(
        command=command,
        tracker_state=updated_tracker_state,
        created_task_id=created_task_id,
        parent_task_id=parent_task_id,
        notion_transport=notion_transport,
    )
    landing_tracker_state, landing_operation_keys = await _refresh_landing_page_from_database_task_graph(
        timeline_tracker_state,
        notion_transport,
    )
    return landing_tracker_state, create_operation_keys + timeline_operation_keys + landing_operation_keys


def should_create_task_through_database(command: dict[str, Any], tracker_state: dict[str, Any]) -> bool:
    if command.get("command") not in {
        "create_top_level_task",
        "create_child_task",
        "create_sibling_task",
    }:
        return False

    if "task_database" not in tracker_state:
        raise ValueError("Task creation requires task_database in tracker state")

    return True


async def _create_task_database_row(
    command_name: str,
    task_title: str,
    configured_priority: Priority,
    status: TaskStatus,
    initial_timeline_entry: dict[str, Any] | None,
    parent_task_id: str | None,
    tracker_state: dict[str, Any],
    work_graph: TaskDependencyGraph,
    notion_transport: NotionTransport,
) -> tuple[str, str, list[str]]:
    create_operation_key = f"create_database_task:{command_name}"
    created_page = await notion_transport.create_task_database_page(
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
        content=_new_task_page_initial_content(
            initial_timeline_entry=initial_timeline_entry,
            parent_task_id=parent_task_id,
            work_graph=work_graph,
        ),
        operation_key=create_operation_key,
    )
    fetched_page_content = await notion_transport.fetch_task_page_content(created_page.notion_page_id)
    created_task_id = task_id_from_fetched_task_database_page(fetched_page_content)
    update_title_operation_key = f"update_properties:task:{created_task_id}"
    completed_update_operation_key = await notion_transport.update_task_database_page_title(
        page_id=created_page.notion_page_id,
        title_property=TASK_DATABASE_TITLE_PROPERTY,
        title=task_title,
        operation_key=update_title_operation_key,
    )
    return (
        created_page.notion_page_id,
        created_task_id,
        [*created_page.operation_keys, completed_update_operation_key],
    )


async def _append_database_task_creation_timeline_entry(
    command: dict[str, Any],
    tracker_state: dict[str, Any],
    created_task_id: str,
    parent_task_id: str | None,
    notion_transport: NotionTransport,
) -> tuple[dict[str, Any], list[str]]:
    timeline_command = _database_task_creation_timeline_command(
        command=command,
        created_task_id=created_task_id,
        tracker_state=tracker_state,
    )
    if timeline_command is None:
        return tracker_state, []

    timeline_owner_task_id = parent_task_id or created_task_id
    timeline_result = await command_result_from_current_notion_state(
        command={
            "command": "append_task_timeline_log",
            "task_id": timeline_owner_task_id,
            "timeline_entry": timeline_command,
        },
        tracker_state=tracker_state,
        notion_transport=notion_transport,
    )
    return await execute_command_result_writes(timeline_result, notion_transport)


async def _refresh_landing_page_from_database_task_graph(
    tracker_state: dict[str, Any],
    notion_transport: NotionTransport,
) -> tuple[dict[str, Any], list[str]]:
    landing_refresh_result = apply_command_to_tracker_state(
        command={
            "command": "refresh_task_pages",
            "operation_keys": ["replace:landing_page", "replace:completed_landing_page"],
        },
        tracker_state=tracker_state,
    )
    return await execute_command_result_writes(landing_refresh_result, notion_transport)


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

    timeline_entry = timeline_entry_for_date(initial_timeline_entry["entry_date"])
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
            f"### {timeline_entry_for_date(initial_timeline_entry['entry_date'])['heading']}",
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
            "text": timeline_entry_for_date(initial_timeline_entry["entry_date"])["heading"],
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
