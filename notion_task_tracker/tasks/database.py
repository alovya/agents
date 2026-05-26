"""Build task graph metadata from Notion task database rows."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any

from notion_task_tracker.common import (
    NotionPlanningError,
    PagePointer,
    canonical_notion_page_id,
    notion_page_id_from_url,
)
from notion_task_tracker.tasks.dependency_graph import TaskDependencyGraph
from notion_task_tracker.tasks.landing_pages import CompletedTasksLandingPage, OngoingTasksLandingPage
from notion_task_tracker.tasks.task import (
    PROPERTIES_BLOCK_PATTERN,
    TASK_DATABASE_PRIORITY_PROPERTY,
    TASK_DATABASE_STATUS_PROPERTY,
    TASK_DATABASE_TITLE_PROPERTY,
    Priority,
    Task,
    TaskStatus,
    task_id_sort_key,
)


TASK_DATABASE_DATA_SOURCE_ID = "36b03da5-d69a-8080-91d1-000b5d7c1c8d"
TASK_DATABASE_DATA_SOURCE_URL = f"collection://{TASK_DATABASE_DATA_SOURCE_ID}"
TASK_DATABASE_VIEW_URL = (
    "https://www.notion.so/wayve/36b03da5d69a80b4acacf711623b59e8?v=36b03da5d69a800c893f000cf2aefead"
)
TASK_DATABASE_TICKET_ID_PROPERTY = "Ticket ID"
TASK_DATABASE_PARENT_PROPERTY = "Parent"
_TASK_TITLE_PREFIX_PATTERN = re.compile(r"^ALOVYA-\d+:\s+")


def task_dependency_graph_from_database_query_results(
    query_results: list[dict[str, Any]],
    landing_page: PagePointer,
    completed_landing_page: PagePointer | None = None,
    previous_work_graph: TaskDependencyGraph | None = None,
) -> TaskDependencyGraph:
    previous_tasks_by_task_id = _previous_tasks_by_task_id(previous_work_graph)
    previous_tasks_by_page_id = _previous_tasks_by_page_id(previous_work_graph)
    database_rows = _database_rows_from_query_results(query_results)
    database_rows = _database_rows_that_belong_to_task_graph(database_rows)
    work_graph = TaskDependencyGraph(
        ongoing_tasks_landing_page=OngoingTasksLandingPage(page=landing_page),
        completed_tasks_landing_page=CompletedTasksLandingPage(
            page=completed_landing_page or _previous_completed_landing_page(previous_work_graph)
        ),
    )

    for database_row in database_rows:
        previous_task = previous_tasks_by_task_id.get(database_row.task_id)
        if previous_task is None:
            previous_task = previous_tasks_by_page_id.get(database_row.notion_page_id)
        work_graph.add_task(_task_from_database_row(database_row, previous_task))

    _link_database_parent_rows(work_graph, database_rows)
    _sort_child_task_ids(work_graph)
    work_graph.validate()
    work_graph.recalculate_display_priorities()
    return work_graph


@dataclass(frozen=True)
class TaskDatabaseRow:
    """One task row returned by the Notion task database."""

    task_id: str
    title: str
    configured_priority: Priority
    status: TaskStatus
    notion_page_id: str
    notion_page_url: str
    parent_notion_page_ids: list[str]
    ticket_number: int


def task_database_query_for_tracker_state(tracker_state: dict[str, Any]) -> str:
    return (
        f'SELECT * FROM "{TASK_DATABASE_DATA_SOURCE_URL}" '
        f'WHERE "{TASK_DATABASE_PRIORITY_PROPERTY}" IS NOT NULL '
        f'AND "{TASK_DATABASE_STATUS_PROPERTY}" IS NOT NULL'
    )


def task_database_data_source_url_from_tracker_state(tracker_state: dict[str, Any]) -> str:
    return tracker_state.get("task_database", {}).get("data_source_url", TASK_DATABASE_DATA_SOURCE_URL)


def task_database_view_url_from_tracker_state(tracker_state: dict[str, Any]) -> str | None:
    return tracker_state.get("task_database", {}).get("view_url")


def task_database_data_source_id_from_tracker_state(tracker_state: dict[str, Any]) -> str:
    return tracker_state.get("task_database", {}).get("data_source_id", TASK_DATABASE_DATA_SOURCE_ID)


def task_id_from_fetched_task_database_page(fetched_page_content: str) -> str:
    return f"ALOVYA-{_ticket_number_from_fetched_task_database_page(fetched_page_content)}"


def task_database_row_from_fetched_task_database_page(
    fetched_page_content: str,
    notion_page_id: str,
) -> TaskDatabaseRow:
    properties = _properties_from_fetched_task_database_page(fetched_page_content)
    properties.setdefault("url", f"https://www.notion.so/{canonical_notion_page_id(notion_page_id)}")
    return _database_row_from_query_result(properties)


def default_task_database_tracker_state() -> dict[str, Any]:
    return {
        "data_source_id": TASK_DATABASE_DATA_SOURCE_ID,
        "data_source_url": TASK_DATABASE_DATA_SOURCE_URL,
        "view_url": TASK_DATABASE_VIEW_URL,
        "title_property": TASK_DATABASE_TITLE_PROPERTY,
        "ticket_id_property": TASK_DATABASE_TICKET_ID_PROPERTY,
        "priority_property": TASK_DATABASE_PRIORITY_PROPERTY,
        "status_property": TASK_DATABASE_STATUS_PROPERTY,
        "parent_property": TASK_DATABASE_PARENT_PROPERTY,
    }


def _database_rows_from_query_results(query_results: list[dict[str, Any]]) -> list[TaskDatabaseRow]:
    database_rows_by_task_id = {}

    for query_result in query_results:
        if not _query_result_has_task_identity(query_result):
            continue
        database_row = _database_row_from_query_result(query_result)
        _record_database_row_by_task_id(database_rows_by_task_id, database_row)

    return list(database_rows_by_task_id.values())


def _database_rows_that_belong_to_task_graph(database_rows: list[TaskDatabaseRow]) -> list[TaskDatabaseRow]:
    retained_database_rows = list(database_rows)

    while True:
        task_page_ids = {
            database_row.notion_page_id
            for database_row in retained_database_rows
        }
        filtered_database_rows = [
            database_row
            for database_row in retained_database_rows
            if _database_row_has_no_parent_or_known_parent(database_row, task_page_ids)
        ]
        if len(filtered_database_rows) == len(retained_database_rows):
            return filtered_database_rows
        retained_database_rows = filtered_database_rows


def _database_row_has_no_parent_or_known_parent(
    database_row: TaskDatabaseRow,
    task_page_ids: set[str],
) -> bool:
    if len(database_row.parent_notion_page_ids) > 1:
        raise NotionPlanningError(f"Task {database_row.task_id} has more than one parent")

    return not database_row.parent_notion_page_ids or database_row.parent_notion_page_ids[0] in task_page_ids


def _ticket_number_from_fetched_task_database_page(fetched_page_content: str) -> int:
    return _required_ticket_number(_properties_from_fetched_task_database_page(fetched_page_content))


def _properties_from_fetched_task_database_page(fetched_page_content: str) -> dict[str, Any]:
    properties_match = PROPERTIES_BLOCK_PATTERN.search(fetched_page_content)
    if properties_match is None:
        raise NotionPlanningError("Fetched task database page has no properties block")

    return json.loads(properties_match.group(1))


def _database_row_from_query_result(query_result: dict[str, Any]) -> TaskDatabaseRow:
    ticket_number = _required_ticket_number(query_result)
    notion_page_url = _required_text_property(query_result, "url")
    notion_page_id = notion_page_id_from_url(notion_page_url)
    task_id = f"ALOVYA-{ticket_number}"
    title = _task_title_from_database_title(
        database_title=_required_text_property(query_result, TASK_DATABASE_TITLE_PROPERTY),
        task_id=task_id,
    )
    return TaskDatabaseRow(
        task_id=task_id,
        title=title,
        configured_priority=Priority(_required_text_property(query_result, TASK_DATABASE_PRIORITY_PROPERTY)),
        status=TaskStatus(_required_text_property(query_result, TASK_DATABASE_STATUS_PROPERTY)),
        notion_page_id=notion_page_id,
        notion_page_url=notion_page_url,
        parent_notion_page_ids=[
            notion_page_id_from_url(parent_page_url)
            for parent_page_url in _relation_page_urls(query_result.get(TASK_DATABASE_PARENT_PROPERTY))
        ],
        ticket_number=ticket_number,
    )


def _task_from_database_row(
    database_row: TaskDatabaseRow,
    previous_task: Task | None,
) -> Task:
    return Task(
        task_id=database_row.task_id,
        title=database_row.title,
        configured_priority=database_row.configured_priority,
        status=database_row.status,
        status_update=previous_task.status_update if previous_task else "",
        timeline_entries=list(previous_task.timeline_entries) if previous_task else [],
        links=list(previous_task.links) if previous_task else [],
        notion_page_id=database_row.notion_page_id,
    )


def _link_database_parent_rows(
    work_graph: TaskDependencyGraph,
    database_rows: list[TaskDatabaseRow],
) -> None:
    task_id_by_page_id = {
        database_row.notion_page_id: database_row.task_id
        for database_row in database_rows
    }

    for database_row in database_rows:
        if not database_row.parent_notion_page_ids:
            continue

        parent_page_id = database_row.parent_notion_page_ids[0]
        parent_task_id = task_id_by_page_id.get(parent_page_id)
        work_graph.link_parent_to_child(parent_task_id=parent_task_id, child_task_id=database_row.task_id)


def _sort_child_task_ids(work_graph: TaskDependencyGraph) -> None:
    for task in work_graph.tasks.values():
        task.child_task_ids.sort(key=task_id_sort_key)


def _query_result_has_task_identity(query_result: dict[str, Any]) -> bool:
    return bool(
        query_result.get(TASK_DATABASE_TITLE_PROPERTY)
        and query_result.get(TASK_DATABASE_TICKET_ID_PROPERTY)
        and query_result.get(TASK_DATABASE_PRIORITY_PROPERTY)
        and query_result.get(TASK_DATABASE_STATUS_PROPERTY)
    )


def _record_database_row_by_task_id(
    database_rows_by_task_id: dict[str, TaskDatabaseRow],
    database_row: TaskDatabaseRow,
) -> None:
    existing_database_row = database_rows_by_task_id.get(database_row.task_id)
    if existing_database_row is None:
        database_rows_by_task_id[database_row.task_id] = database_row
        return

    raise NotionPlanningError(f"Duplicate task id {database_row.task_id} in task database")


def _task_title_from_database_title(database_title: str, task_id: str) -> str:
    database_title = _plain_database_title(database_title)
    while True:
        task_title_match = _TASK_TITLE_PREFIX_PATTERN.match(database_title)
        if task_title_match is None:
            return database_title
        database_title = database_title.removeprefix(task_title_match.group(0))



def _plain_database_title(database_title: str) -> str:
    return database_title.replace("\u0336", "")


def _relation_page_urls(raw_relation: Any) -> list[str]:
    if raw_relation is None or raw_relation == "":
        return []
    if isinstance(raw_relation, list):
        return [str(page_url) for page_url in raw_relation]
    if isinstance(raw_relation, str):
        return [str(page_url) for page_url in json.loads(raw_relation)]

    raise NotionPlanningError(f"Unsupported relation value {raw_relation!r}")


def _required_ticket_number(query_result: dict[str, Any]) -> int:
    raw_ticket_number = query_result.get(TASK_DATABASE_TICKET_ID_PROPERTY)
    if raw_ticket_number in {None, ""}:
        raise NotionPlanningError("Task database row has no Ticket ID")

    return int(raw_ticket_number)


def _required_text_property(query_result: dict[str, Any], property_name: str) -> str:
    value = _optional_text_property(query_result, property_name)
    if value is None:
        raise NotionPlanningError(f"Task database row has no {property_name}")

    return value


def _optional_text_property(query_result: dict[str, Any], property_name: str) -> str | None:
    value = query_result.get(property_name)
    if value in {None, ""}:
        return None

    if property_name == "url":
        return f"https://www.notion.so/{notion_page_id_from_url(str(value))}"

    return str(value)


def _previous_tasks_by_task_id(previous_work_graph: TaskDependencyGraph | None) -> dict[str, Task]:
    if previous_work_graph is None:
        return {}

    return dict(previous_work_graph.tasks)


def _previous_completed_landing_page(previous_work_graph: TaskDependencyGraph | None) -> PagePointer:
    if previous_work_graph is None:
        return TaskDependencyGraph().completed_tasks_landing_page.page

    return previous_work_graph.completed_tasks_landing_page.page


def _previous_tasks_by_page_id(previous_work_graph: TaskDependencyGraph | None) -> dict[str, Task]:
    if previous_work_graph is None:
        return {}

    return {
        canonical_notion_page_id(task.notion_page_id): task
        for task in previous_work_graph.tasks.values()
        if task.notion_page_id is not None
    }

