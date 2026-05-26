"""Task dependency graph metadata."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from notion_task_tracker.notion_pages import (
    COMPLETED_LANDING_PAGE_LOCAL_KEY,
    COMPLETED_LANDING_PAGE_TITLE,
    LANDING_PAGE_LOCAL_KEY,
    LANDING_PAGE_TITLE,
    NotionPageRegistry,
    NotionPlanningError,
    NotionWriteIntent,
    PagePointer,
    external_link_from_snapshot,
    external_link_to_snapshot,
    fixed_page_pointer_from_snapshot,
    page_pointer_to_snapshot,
    validate_fixed_page_pointer,
    write_json_snapshot,
)


from notion_task_tracker.tasks.pages.landing_pages import CompletedTasksLandingPage, OngoingTasksLandingPage
from notion_task_tracker.tasks.task import (
    Priority,
    Task,
    TaskStatus,
    TimelineEntry,
    _PRIORITY_RANK_BY_VALUE,
    task_id_sort_key,
)


@dataclass
class TaskDependencyGraph:
    """Task graph and task landing-page registry."""

    ongoing_tasks_landing_page: OngoingTasksLandingPage = field(
        default_factory=lambda: OngoingTasksLandingPage(
            page=PagePointer(
                local_page_key=LANDING_PAGE_LOCAL_KEY,
                title=LANDING_PAGE_TITLE,
            )
        )
    )
    completed_tasks_landing_page: CompletedTasksLandingPage = field(
        default_factory=lambda: CompletedTasksLandingPage(
            page=PagePointer(
                local_page_key=COMPLETED_LANDING_PAGE_LOCAL_KEY,
                title=COMPLETED_LANDING_PAGE_TITLE,
            )
        )
    )
    tasks: dict[str, Task] = field(default_factory=dict)

    @classmethod
    def from_snapshot_path(cls, snapshot_path: str | Path) -> TaskDependencyGraph:
        source_path = Path(snapshot_path)
        snapshot = json.loads(source_path.read_text(encoding="utf-8"))
        return cls.from_snapshot(snapshot)

    @classmethod
    def from_snapshot(cls, snapshot: dict[str, Any]) -> TaskDependencyGraph:
        work_graph = cls(
            ongoing_tasks_landing_page=OngoingTasksLandingPage(
                page=fixed_page_pointer_from_snapshot(
                    snapshot=snapshot["landing_page"],
                    local_page_key=LANDING_PAGE_LOCAL_KEY,
                    title=LANDING_PAGE_TITLE,
                )
            ),
            completed_tasks_landing_page=CompletedTasksLandingPage(
                page=fixed_page_pointer_from_snapshot(
                    snapshot=snapshot.get("completed_landing_page") or {},
                    local_page_key=COMPLETED_LANDING_PAGE_LOCAL_KEY,
                    title=COMPLETED_LANDING_PAGE_TITLE,
                )
            ),
        )
        for task_snapshot in snapshot.get("tasks", {}).values():
            work_graph.tasks[task_snapshot["task_id"]] = _task_from_snapshot(task_snapshot)
        work_graph._normalise_task_timelines()
        work_graph.validate()
        work_graph.recalculate_display_priorities()
        return work_graph

    def write_snapshot(self, snapshot_path: str | Path) -> None:
        write_json_snapshot(self.to_snapshot(), snapshot_path)

    def to_snapshot(self) -> dict[str, Any]:
        return {
            "landing_page": page_pointer_to_snapshot(self.ongoing_tasks_landing_page.page),
            "completed_landing_page": page_pointer_to_snapshot(self.completed_tasks_landing_page.page),
            "tasks": {
                task_id: _task_to_snapshot(task)
                for task_id, task in sorted(self.tasks.items(), key=lambda item: task_id_sort_key(item[0]))
            },
        }

    def page_registry(self) -> NotionPageRegistry:
        return NotionPageRegistry.from_page_pointers(self._pages_that_should_exist())

    def add_task(self, task: Task) -> None:
        if task.task_id in self.tasks:
            raise NotionPlanningError(f"Task {task.task_id} already exists")
        self.tasks[task.task_id] = task

    def link_parent_to_child(self, parent_task_id: str, child_task_id: str) -> None:
        parent_task = self.tasks[parent_task_id]
        child_task = self.tasks[child_task_id]
        if child_task_id not in parent_task.child_task_ids:
            parent_task.child_task_ids.append(child_task_id)
        child_task.parent_task_id = parent_task_id

    def set_task_parent(self, task_id: str, parent_task_id: str | None) -> None:
        for task in self.tasks.values():
            if task_id in task.child_task_ids:
                task.child_task_ids.remove(task_id)

        self.tasks[task_id].parent_task_id = None
        if parent_task_id is not None:
            self.link_parent_to_child(parent_task_id=parent_task_id, child_task_id=task_id)

        for task in self.tasks.values():
            task.child_task_ids.sort(key=task_id_sort_key)

    def build_notion_write_plan(self) -> list[NotionWriteIntent]:
        self.validate()
        self.recalculate_display_priorities()
        return [
            *self._plan_missing_page_creation(),
            *self._plan_fixed_page_title_refreshes(),
            *self._plan_existing_task_property_refreshes(),
            self._plan_landing_page_refresh(),
            *self._plan_completed_landing_page_refresh(),
        ]

    def append_task_timeline_log(
        self,
        task_id: str,
        timeline_entry: TimelineEntry,
    ) -> NotionWriteIntent:
        task = self.tasks[task_id]
        write_intent = task.append_timeline_log(timeline_entry)
        self.validate()
        self.recalculate_display_priorities()
        return write_intent

    def complete_task(
        self,
        task_id: str,
        timeline_entry: TimelineEntry,
    ) -> list[NotionWriteIntent]:
        task = self.tasks[task_id]
        task_property_intent, timeline_log_intent = task.complete_with_timeline_log(timeline_entry)
        self.validate()
        self.recalculate_display_priorities()
        return [
            task_property_intent,
            self._plan_landing_page_refresh(),
            *self._plan_completed_landing_page_refresh(),
            timeline_log_intent,
        ]

    def task_ids_grouped_for_landing_page(self) -> dict[Priority, list[str]]:
        self.recalculate_display_priorities()
        return self.ongoing_tasks_landing_page.task_ids_grouped_by_priority(self.tasks)

    def completed_task_ids_for_landing_page(self) -> list[str]:
        return self.completed_tasks_landing_page.completed_top_level_task_ids(self.tasks)

    def cancelled_task_ids_for_landing_page(self) -> list[str]:
        return self.completed_tasks_landing_page.cancelled_top_level_task_ids(self.tasks)

    def validate(self) -> None:
        self._validate_fixed_page_keys_and_titles()
        self._validate_task_keys_match_task_values()
        self._validate_parent_child_links()
        self._validate_task_hierarchy_has_no_cycles()

    def recalculate_display_priorities(self) -> None:
        for task in self.tasks.values():
            task.displayed_priority = task.configured_priority
        for task_id in sorted(self.tasks, key=task_id_sort_key, reverse=True):
            self.tasks[task_id].displayed_priority = self._calculate_priority_visible_on_task(self.tasks[task_id])

    def _plan_missing_page_creation(self) -> list[NotionWriteIntent]:
        write_intents = []
        ongoing_page_creation = self.ongoing_tasks_landing_page.creation_intent(
            self.ongoing_tasks_landing_page.render_blocks(self.tasks)
        )
        completed_page_creation = self.completed_tasks_landing_page.creation_intent(
            self.completed_tasks_landing_page.render_blocks(self.tasks)
        )
        for page_creation in [ongoing_page_creation, completed_page_creation]:
            if page_creation is not None:
                write_intents.append(page_creation)
        return write_intents

    def _plan_fixed_page_title_refreshes(self) -> list[NotionWriteIntent]:
        return [
            title_refresh
            for title_refresh in [
                self.ongoing_tasks_landing_page.title_refresh_intent(),
                self.completed_tasks_landing_page.title_refresh_intent(),
            ]
            if title_refresh is not None
        ]

    def _plan_existing_task_property_refreshes(self) -> list[NotionWriteIntent]:
        return [
            task.database_property_refresh_intent()
            for task in sorted(self.tasks.values(), key=lambda task: task_id_sort_key(task.task_id))
            if task.notion_page_id is not None
        ]

    def _plan_landing_page_refresh(self) -> NotionWriteIntent:
        return self.ongoing_tasks_landing_page.refresh_intent(self.tasks)

    def _plan_completed_landing_page_refresh(self) -> list[NotionWriteIntent]:
        return self.completed_tasks_landing_page.refresh_intents(self.tasks)

    def _pages_that_should_exist(self) -> list[PagePointer]:
        pages = [
            self.ongoing_tasks_landing_page.page,
            self.completed_tasks_landing_page.page,
        ]
        for task in self.tasks.values():
            pages.append(
                PagePointer(
                    local_page_key=task.local_page_key,
                    title=task.page_title(),
                    notion_page_id=task.notion_page_id,
                    parent_page_key=None,
                )
            )
        return pages

    def _validate_fixed_page_keys_and_titles(self) -> None:
        validate_fixed_page_pointer(
            page=self.ongoing_tasks_landing_page.page,
            expected_local_page_key=LANDING_PAGE_LOCAL_KEY,
            expected_title=LANDING_PAGE_TITLE,
        )
        validate_fixed_page_pointer(
            page=self.completed_tasks_landing_page.page,
            expected_local_page_key=COMPLETED_LANDING_PAGE_LOCAL_KEY,
            expected_title=COMPLETED_LANDING_PAGE_TITLE,
        )

    def _validate_task_keys_match_task_values(self) -> None:
        for task_id, task in self.tasks.items():
            if task_id != task.task_id:
                raise NotionPlanningError(f"Task key {task_id!r} does not match task id {task.task_id!r}")

    def _validate_parent_child_links(self) -> None:
        for task_id, task in self.tasks.items():
            if task.parent_task_id is not None:
                self._validate_task_exists(task.parent_task_id)
                parent_task = self.tasks[task.parent_task_id]
                if task_id not in parent_task.child_task_ids:
                    raise NotionPlanningError(
                        f"Task {task_id} should be listed as child of {task.parent_task_id}"
                    )
            for child_task_id in task.child_task_ids:
                self._validate_task_exists(child_task_id)
                child_task = self.tasks[child_task_id]
                if child_task.parent_task_id != task_id:
                    raise NotionPlanningError(
                        f"Task {child_task_id} should have parent {task_id}"
                    )

    def _validate_task_exists(self, task_id: str) -> None:
        if task_id not in self.tasks:
            raise NotionPlanningError(f"Task {task_id} does not exist")

    def _validate_task_hierarchy_has_no_cycles(self) -> None:
        for task_id in self.tasks:
            visited_task_ids = set()
            current_task_id = task_id
            while current_task_id is not None:
                if current_task_id in visited_task_ids:
                    raise NotionPlanningError("Task hierarchy has a cycle")
                visited_task_ids.add(current_task_id)
                current_task_id = self.tasks[current_task_id].parent_task_id

    def _calculate_priority_visible_on_task(self, task: Task) -> Priority:
        priorities_visible_in_subtree = [task.configured_priority]
        for child_task_id in task.child_task_ids:
            child_task = self.tasks[child_task_id]
            if child_task.should_contribute_priority_to_ancestors():
                priorities_visible_in_subtree.append(child_task.displayed_priority or child_task.configured_priority)
        return _highest_priority(priorities_visible_in_subtree)

    def _normalise_task_timelines(self) -> None:
        for task in self.tasks.values():
            task.normalise_timeline_entries()


def _highest_priority(priorities: list[Priority]) -> Priority:
    return min(priorities, key=lambda priority: _PRIORITY_RANK_BY_VALUE[priority])


def _task_to_snapshot(task: Task) -> dict[str, Any]:
    return {
        "task_id": task.task_id,
        "title": task.title,
        "configured_priority": task.configured_priority.value,
        "displayed_priority": task.displayed_priority.value if task.displayed_priority else None,
        "status": task.status.value,
        "status_update": task.status_update,
        "parent_task_id": task.parent_task_id,
        "child_task_ids": list(task.child_task_ids),
        "timeline_entries": [
            timeline_entry.to_snapshot()
            for timeline_entry in task.timeline_entries
        ],
        "links": [
            external_link_to_snapshot(link)
            for link in task.links
        ],
        "notion_page_id": task.notion_page_id,
    }


def _task_from_snapshot(snapshot: dict[str, Any]) -> Task:
    displayed_priority = snapshot.get("displayed_priority")

    return Task(
        task_id=snapshot["task_id"],
        title=snapshot["title"],
        configured_priority=Priority(snapshot["configured_priority"]),
        displayed_priority=Priority(displayed_priority) if displayed_priority else None,
        status=TaskStatus(snapshot["status"]),
        status_update=snapshot.get("status_update", ""),
        parent_task_id=snapshot.get("parent_task_id"),
        child_task_ids=list(snapshot.get("child_task_ids", [])),
        timeline_entries=[
            TimelineEntry.from_snapshot(timeline_snapshot)
            for timeline_snapshot in snapshot.get("timeline_entries", [])
        ],
        links=[
            external_link_from_snapshot(link_snapshot)
            for link_snapshot in snapshot.get("links", [])
        ],
        notion_page_id=snapshot.get("notion_page_id"),
    )
