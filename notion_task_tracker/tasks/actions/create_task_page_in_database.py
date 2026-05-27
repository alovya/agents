"""Create parent, child, or sibling task pages through the task database."""

from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Any

from notion_task_tracker.apply_tracker_command import apply_command_to_tracker_state
from notion_task_tracker.notion_client import NotionClient
from notion_task_tracker.notion_write_executor import execute_command_result_writes
from notion_task_tracker.tasks.actions.write_task_log import command_result_from_current_notion_state
from notion_task_tracker.tasks import TaskDependencyGraph, Task, TimelineEntry
from notion_task_tracker.tasks.database import (
    TASK_DATABASE_PARENT_PROPERTY,
    TASK_DATABASE_PRIORITY_PROPERTY,
    TASK_DATABASE_STATUS_PROPERTY,
    TASK_DATABASE_TITLE_PROPERTY,
    task_database_data_source_id_from_tracker_state,
    task_id_from_fetched_task_database_page,
)
from notion_task_tracker.tasks.task import (
    TASK_PAGE_TIMELINE_LOG_HEADING,
    Priority,
    TaskStatus,
)
from notion_task_tracker.tasks.pages.timeline_log import timeline_entry_for_date


async def execute_task_creation_command(
    command: dict[str, Any],
    tracker_state: dict[str, Any],
    notion_client: NotionClient,
) -> tuple[dict[str, Any], list[str]]:
    work_graph = TaskDependencyGraph.from_tracker_state(tracker_state)
    task_creation = _task_creation_from_command(command, work_graph)
    created_page_id, created_task_id, create_operation_keys = await _create_database_page_and_read_ticket_id(
        task_creation=task_creation,
        tracker_state=tracker_state,
        work_graph=work_graph,
        notion_client=notion_client,
    )

    _add_created_task_to_dependency_graph(
        work_graph=work_graph,
        task_creation=task_creation,
        created_task_id=created_task_id,
        created_page_id=created_page_id,
    )
    updated_tracker_state = work_graph.replace_task_graph_in_tracker_state(tracker_state)
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


def command_creates_task_page_in_database(command: dict[str, Any], tracker_state: dict[str, Any]) -> bool:
    if command.get("command") not in {
        "create_top_level_task",
        "create_child_task",
        "create_sibling_task",
    }:
        return False

    if "task_database" not in tracker_state:
        raise ValueError("Task creation requires task_database in tracker state")

    return True


@dataclass(frozen=True)
class _TaskCreation:
    command_name: str
    task_title: str
    configured_priority: Priority
    status: TaskStatus
    parent_task_id: str | None
    initial_child_timeline_entry: dict[str, Any] | None
    parent_timeline_entry: dict[str, Any] | None


def _task_creation_from_command(command: dict[str, Any], work_graph: TaskDependencyGraph) -> _TaskCreation:
    command_name = command["command"]
    if command_name == "create_top_level_task":
        return _parent_task_creation_from_command(command)

    if command_name == "create_child_task":
        return _child_task_creation_from_command(command)

    if command_name == "create_sibling_task":
        return _sibling_task_creation_from_command(command, work_graph)

    raise ValueError(f"Unsupported database task creation command {command_name!r}")


def _parent_task_creation_from_command(command: dict[str, Any]) -> _TaskCreation:
    task_command = command["task"]
    return _TaskCreation(
        command_name=command["command"],
        task_title=task_command["title"],
        configured_priority=Priority(task_command["configured_priority"]),
        status=TaskStatus(task_command["status"]),
        parent_task_id=None,
        initial_child_timeline_entry=None,
        parent_timeline_entry=command.get("timeline_entry"),
    )


def _child_task_creation_from_command(command: dict[str, Any]) -> _TaskCreation:
    child_task_command = command["child_task"]
    parent_timeline_entry = command.get("parent_timeline_entry")
    return _TaskCreation(
        command_name=command["command"],
        task_title=child_task_command["title"],
        configured_priority=Priority(child_task_command["configured_priority"]),
        status=TaskStatus(child_task_command["status"]),
        parent_task_id=command["parent_task_id"],
        initial_child_timeline_entry=parent_timeline_entry,
        parent_timeline_entry=parent_timeline_entry,
    )


def _sibling_task_creation_from_command(command: dict[str, Any], work_graph: TaskDependencyGraph) -> _TaskCreation:
    sibling_task_command = command["sibling_task"]
    parent_task_id = work_graph.tasks[command["sibling_task_id"]].parent_task_id
    timeline_entry = command.get("timeline_entry")
    return _TaskCreation(
        command_name=command["command"],
        task_title=sibling_task_command["title"],
        configured_priority=Priority(sibling_task_command["configured_priority"]),
        status=TaskStatus(sibling_task_command["status"]),
        parent_task_id=parent_task_id,
        initial_child_timeline_entry=timeline_entry if parent_task_id is not None else None,
        parent_timeline_entry=timeline_entry,
    )


async def _create_database_page_and_read_ticket_id(
    task_creation: _TaskCreation,
    tracker_state: dict[str, Any],
    work_graph: TaskDependencyGraph,
    notion_client: NotionClient,
) -> tuple[str, str, list[str]]:
    create_operation_key = f"create_database_task:{task_creation.command_name}"
    created_page = await notion_client.create_task_database_page(
        data_source_id=task_database_data_source_id_from_tracker_state(tracker_state),
        properties=_new_task_database_row_properties(
            task_title=task_creation.task_title,
            configured_priority=task_creation.configured_priority,
            status=task_creation.status,
            parent_task_id=task_creation.parent_task_id,
            work_graph=work_graph,
        ),
        content=_new_task_page_initial_content(
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


def _add_created_task_to_dependency_graph(
    work_graph: TaskDependencyGraph,
    task_creation: _TaskCreation,
    created_task_id: str,
    created_page_id: str,
) -> None:
    work_graph.add_task(
        Task(
            task_id=created_task_id,
            title=task_creation.task_title,
            configured_priority=task_creation.configured_priority,
            status=task_creation.status,
            timeline_entries=_timeline_entries_for_created_task(task_creation.initial_child_timeline_entry),
            notion_page_id=created_page_id,
        )
    )
    if task_creation.parent_task_id is not None:
        work_graph.link_parent_to_child(parent_task_id=task_creation.parent_task_id, child_task_id=created_task_id)
    work_graph.validate()
    work_graph.recalculate_display_priorities()


async def _write_task_creation_timeline_entry(
    task_creation: _TaskCreation,
    tracker_state: dict[str, Any],
    created_task_id: str,
    notion_client: NotionClient,
) -> tuple[dict[str, Any], list[str]]:
    timeline_command = _timeline_entry_that_records_created_task(
        task_creation=task_creation,
        created_task_id=created_task_id,
        tracker_state=tracker_state,
    )
    if timeline_command is None:
        return tracker_state, []

    timeline_owner_task_id = task_creation.parent_task_id or created_task_id
    timeline_result = await command_result_from_current_notion_state(
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
            "operation_keys": ["replace:landing_page", "replace:completed_landing_page"],
        },
        tracker_state=tracker_state,
    )
    return await execute_command_result_writes(landing_refresh_result, notion_client)


def _timeline_entries_for_created_task(
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


def _timeline_entry_that_records_created_task(
    task_creation: _TaskCreation,
    created_task_id: str,
    tracker_state: dict[str, Any],
) -> dict[str, Any] | None:
    if task_creation.parent_timeline_entry is None:
        return None

    if task_creation.command_name not in {"create_child_task", "create_sibling_task"}:
        return task_creation.parent_timeline_entry

    return _timeline_entry_with_created_task_link(task_creation.parent_timeline_entry, created_task_id, tracker_state)


def _timeline_entry_with_created_task_link(
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
