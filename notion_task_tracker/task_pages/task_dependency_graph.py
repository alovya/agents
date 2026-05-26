"""Task graph metadata and task-page write planning."""

from __future__ import annotations

from collections.abc import Callable
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from notion_task_tracker.common import (
    COMPLETED_LANDING_PAGE_LOCAL_KEY,
    COMPLETED_LANDING_PAGE_TITLE,
    LANDING_PAGE_LOCAL_KEY,
    LANDING_PAGE_TITLE,
    NotionPageRegistry,
    NotionMcpCallPlanningError,
    NotionWriteIntent,
    PagePointer,
    external_link_from_snapshot,
    external_link_to_snapshot,
    fixed_page_pointer_from_snapshot,
    heading_block,
    page_pointer_to_snapshot,
    paragraph_block,
    validate_fixed_page_pointer,
    write_json_snapshot,
)


from notion_task_tracker.task_pages.task_metadata import (
    LANDING_HEADING_BY_PRIORITY,
    Priority,
    TASK_DATABASE_PRIORITY_PROPERTY,
    TASK_DATABASE_STATUS_PROPERTY,
    TASK_DATABASE_TITLE_PROPERTY,
    TASK_PAGE_TIMELINE_LOG_HEADING,
    UPDATE_TIMELINE_LOG_OPERATION_NAME,
    TaskPageMetadata,
    TaskStatus,
    TimelineEntry,
    _PRIORITY_RANK_BY_VALUE,
)
from notion_task_tracker.task_pages.rendering import (
    _format_landing_task_text,
    _landing_color_for_task,
    _render_task_page_title,
    _render_timeline_entry_content_blocks,
    _render_timeline_blocks,
)


@dataclass
class TaskDependencyGraph:
    """Task graph and task landing-page registry."""

    landing_page: PagePointer = field(
        default_factory=lambda: PagePointer(
            local_page_key=LANDING_PAGE_LOCAL_KEY,
            title=LANDING_PAGE_TITLE,
        )
    )
    completed_landing_page: PagePointer = field(
        default_factory=lambda: PagePointer(
            local_page_key=COMPLETED_LANDING_PAGE_LOCAL_KEY,
            title=COMPLETED_LANDING_PAGE_TITLE,
        )
    )
    tasks: dict[str, TaskPageMetadata] = field(default_factory=dict)

    @classmethod
    def from_snapshot_path(cls, snapshot_path: str | Path) -> TaskDependencyGraph:
        source_path = Path(snapshot_path)
        snapshot = json.loads(source_path.read_text(encoding="utf-8"))
        return cls.from_snapshot(snapshot)

    @classmethod
    def from_snapshot(cls, snapshot: dict[str, Any]) -> TaskDependencyGraph:
        work_graph = cls(
            landing_page=fixed_page_pointer_from_snapshot(
                snapshot=snapshot["landing_page"],
                local_page_key=LANDING_PAGE_LOCAL_KEY,
                title=LANDING_PAGE_TITLE,
            ),
            completed_landing_page=fixed_page_pointer_from_snapshot(
                snapshot=snapshot.get("completed_landing_page") or {},
                local_page_key=COMPLETED_LANDING_PAGE_LOCAL_KEY,
                title=COMPLETED_LANDING_PAGE_TITLE,
            ),
        )
        for task_snapshot in snapshot.get("tasks", {}).values():
            work_graph.tasks[task_snapshot["task_id"]] = _task_from_snapshot(task_snapshot)
        work_graph._normalize_task_timelines()
        work_graph.validate()
        work_graph.recalculate_display_priorities()
        return work_graph

    def write_snapshot(self, snapshot_path: str | Path) -> None:
        write_json_snapshot(self.to_snapshot(), snapshot_path)

    def to_snapshot(self) -> dict[str, Any]:
        return {
            "landing_page": page_pointer_to_snapshot(self.landing_page),
            "completed_landing_page": page_pointer_to_snapshot(self.completed_landing_page),
            "tasks": {
                task_id: _task_to_snapshot(task)
                for task_id, task in sorted(self.tasks.items(), key=lambda item: _task_id_sort_key(item[0]))
            },
        }

    def page_registry(self) -> NotionPageRegistry:
        return NotionPageRegistry.from_page_pointers(self._pages_that_should_exist())

    def add_task(self, task: TaskPageMetadata) -> None:
        if task.task_id in self.tasks:
            raise NotionMcpCallPlanningError(f"Task {task.task_id} already exists")
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
            task.child_task_ids.sort(key=_task_id_sort_key)

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
        task.timeline_entries = _merged_timeline_entries_by_date(task.timeline_entries)
        existing_entry = _timeline_entry_for_date(task.timeline_entries, timeline_entry.entry_date)
        existing_entry_before_append = _copy_timeline_entry(existing_entry) if existing_entry is not None else None
        appended_entry = _copy_timeline_entry(timeline_entry)
        timeline_entry_to_render = _upsert_timeline_entry(task, timeline_entry)
        self.validate()
        self.recalculate_display_priorities()
        return self._plan_task_timeline_log_update(
            task,
            existing_entry_before_append,
            appended_entry,
            timeline_entry_to_render,
        )

    def complete_task(
        self,
        task_id: str,
        timeline_entry: TimelineEntry,
    ) -> list[NotionWriteIntent]:
        task = self.tasks[task_id]
        task.timeline_entries = _merged_timeline_entries_by_date(task.timeline_entries)
        existing_entry = _timeline_entry_for_date(task.timeline_entries, timeline_entry.entry_date)
        existing_entry_before_append = _copy_timeline_entry(existing_entry) if existing_entry is not None else None
        appended_entry = _copy_timeline_entry(timeline_entry)
        task.status = TaskStatus.COMPLETE
        timeline_entry_to_render = _upsert_timeline_entry(task, timeline_entry)
        self.validate()
        self.recalculate_display_priorities()
        return [
            *self._plan_task_completion_update(task_id),
            self._plan_task_timeline_log_update(
                task,
                existing_entry_before_append,
                appended_entry,
                timeline_entry_to_render,
            ),
        ]

    def task_ids_grouped_for_landing_page(self) -> dict[Priority, list[str]]:
        self.recalculate_display_priorities()
        return {
            priority: [
                task_id
                for task_id in self._landing_root_task_ids_matching(_task_should_start_ongoing_landing_tree)
                if self.tasks[task_id].displayed_priority == priority
            ]
            for priority in Priority
        }

    def completed_task_ids_for_landing_page(self) -> list[str]:
        return self._top_level_task_ids_matching(lambda task: task.status == TaskStatus.COMPLETE)

    def cancelled_task_ids_for_landing_page(self) -> list[str]:
        return self._top_level_task_ids_matching(lambda task: task.status == TaskStatus.CANCELLED)

    def validate(self) -> None:
        self._validate_fixed_page_keys_and_titles()
        self._validate_task_keys_match_task_values()
        self._validate_parent_child_links()
        self._validate_task_hierarchy_has_no_cycles()

    def recalculate_display_priorities(self) -> None:
        for task in self.tasks.values():
            task.displayed_priority = task.configured_priority
        for task_id in sorted(self.tasks, key=_task_id_sort_key, reverse=True):
            self.tasks[task_id].displayed_priority = self._calculate_priority_visible_on_task(self.tasks[task_id])

    def _plan_missing_page_creation(self) -> list[NotionWriteIntent]:
        write_intents = []
        for page in [self.landing_page, self.completed_landing_page]:
            if page.notion_page_id is None:
                write_intents.append(
                    NotionWriteIntent(
                        operation_key=f"create:{page.local_page_key}",
                        operation_name="create_page",
                        target_page_key=None,
                        arguments={
                            "local_page_key": page.local_page_key,
                            "title": page.title,
                            "parent_page_key": page.parent_page_key,
                            "blocks": self._page_creation_blocks(page.local_page_key),
                        },
                    )
                )
        return write_intents

    def _plan_fixed_page_title_refreshes(self) -> list[NotionWriteIntent]:
        return [
            NotionWriteIntent(
                operation_key=f"update_properties:{page.local_page_key}",
                operation_name="update_page_properties",
                target_page_key=page.local_page_key,
                arguments={"properties": {"title": page.title}},
            )
            for page in [self.landing_page, self.completed_landing_page]
            if page.notion_page_id is not None
        ]

    def _plan_existing_task_property_refreshes(self) -> list[NotionWriteIntent]:
        return [
            self._plan_task_page_property_refresh(task)
            for task in sorted(self.tasks.values(), key=lambda task: _task_id_sort_key(task.task_id))
            if task.notion_page_id is not None
        ]

    def _plan_task_page_property_refresh(self, task: TaskPageMetadata) -> NotionWriteIntent:
        return NotionWriteIntent(
            operation_key=f"update_properties:{task.local_page_key}",
            operation_name="update_page_properties",
            target_page_key=task.local_page_key,
            arguments={
                "properties": {
                    TASK_DATABASE_TITLE_PROPERTY: _render_task_page_title(task),
                    TASK_DATABASE_PRIORITY_PROPERTY: task.configured_priority.value,
                    TASK_DATABASE_STATUS_PROPERTY: task.status.value,
                }
            },
        )

    def _plan_task_timeline_log_update(
        self,
        task: TaskPageMetadata,
        existing_timeline_entry: TimelineEntry | None,
        appended_timeline_entry: TimelineEntry,
        timeline_entry: TimelineEntry,
    ) -> NotionWriteIntent:
        arguments = {
            "task_id": task.task_id,
            "timeline_log_heading": TASK_PAGE_TIMELINE_LOG_HEADING,
            "timeline_entry": _timeline_entry_to_snapshot(timeline_entry),
            "blocks": _render_timeline_blocks([timeline_entry]),
        }
        if existing_timeline_entry is not None:
            arguments["existing_timeline_heading"] = existing_timeline_entry.heading
            arguments["existing_blocks"] = _render_timeline_blocks([existing_timeline_entry])
            arguments["append_blocks"] = _render_timeline_line_blocks(appended_timeline_entry)

        return NotionWriteIntent(
            operation_key=f"{UPDATE_TIMELINE_LOG_OPERATION_NAME}:{task.local_page_key}:{timeline_entry.entry_date}",
            operation_name=UPDATE_TIMELINE_LOG_OPERATION_NAME,
            target_page_key=task.local_page_key,
            arguments=arguments,
        )

    def _plan_task_completion_update(self, task_id: str) -> list[NotionWriteIntent]:
        task = self.tasks[task_id]
        return [
            self._plan_task_page_property_refresh(task),
            self._plan_landing_page_refresh(),
            *self._plan_completed_landing_page_refresh(),
        ]

    def _plan_landing_page_refresh(self) -> NotionWriteIntent:
        return NotionWriteIntent(
            operation_key="replace:landing_page",
            operation_name="replace_page_children",
            target_page_key=self.landing_page.local_page_key,
            arguments={"blocks": self._render_landing_page_blocks()},
        )

    def _plan_completed_landing_page_refresh(self) -> list[NotionWriteIntent]:
        if self.completed_landing_page.notion_page_id is None:
            return []

        return [
            NotionWriteIntent(
                operation_key="replace:completed_landing_page",
                operation_name="replace_page_children",
                target_page_key=self.completed_landing_page.local_page_key,
                arguments={"blocks": self._render_completed_landing_page_blocks()},
            )
        ]

    def _pages_that_should_exist(self) -> list[PagePointer]:
        pages = [self.landing_page, self.completed_landing_page]
        for task in self.tasks.values():
            pages.append(
                PagePointer(
                    local_page_key=task.local_page_key,
                    title=_render_task_page_title(task),
                    notion_page_id=task.notion_page_id,
                    parent_page_key=None,
                )
            )
        return pages

    def _render_landing_page_blocks(self) -> list[dict[str, Any]]:
        blocks = []
        self._append_priority_landing_sections(blocks)
        return blocks

    def _render_completed_landing_page_blocks(self) -> list[dict[str, Any]]:
        blocks = []
        self._append_status_landing_section(TaskStatus.COMPLETE, "Completed", blocks)
        self._append_status_landing_section(TaskStatus.CANCELLED, "Cancelled", blocks)
        return blocks or [paragraph_block(text="No completed tasks yet.")]

    def _append_priority_landing_sections(self, blocks: list[dict[str, Any]]) -> None:
        for priority, task_ids in self.task_ids_grouped_for_landing_page().items():
            if task_ids:
                blocks.append(heading_block(level=2, text=LANDING_HEADING_BY_PRIORITY[priority]))
                for task_id in task_ids:
                    blocks.extend(
                        self._render_task_tree_blocks(
                            task_id,
                            depth=0,
                            task_should_be_visible=_task_should_appear_inside_ongoing_landing_tree,
                        )
                    )

    def _append_status_landing_section(
        self,
        status: TaskStatus,
        section_title: str,
        blocks: list[dict[str, Any]],
    ) -> None:
        task_should_be_visible = lambda task: task.status == status
        task_ids = self._top_level_task_ids_matching(task_should_be_visible)
        if task_ids:
            blocks.append(heading_block(level=2, text=section_title))
            for task_id in task_ids:
                blocks.extend(
                    self._render_task_tree_blocks(
                        task_id,
                        depth=0,
                        task_should_be_visible=task_should_be_visible,
                    )
                )

    def _render_task_tree_blocks(
        self,
        task_id: str,
        depth: int,
        task_should_be_visible: Callable[[TaskPageMetadata], bool],
    ) -> list[dict[str, Any]]:
        task = self.tasks[task_id]
        displayed_priority = task.displayed_priority or task.configured_priority
        blocks = [
            {
                "type": "bulleted_list_item",
                "depth": depth,
                "text": _format_landing_task_text(task, displayed_priority),
                "page_key": task.local_page_key,
                "color": _landing_color_for_task(task, displayed_priority),
            }
        ]
        for child_task_id in sorted(task.child_task_ids, key=_task_id_sort_key):
            child_task = self.tasks[child_task_id]
            if task_should_be_visible(child_task):
                blocks.extend(
                    self._render_task_tree_blocks(
                        child_task_id,
                        depth=depth + 1,
                        task_should_be_visible=task_should_be_visible,
                    )
                )
        return blocks

    def _page_creation_blocks(self, local_page_key: str) -> list[dict[str, Any]]:
        if local_page_key == self.landing_page.local_page_key:
            return self._render_landing_page_blocks()
        if local_page_key == self.completed_landing_page.local_page_key:
            return self._render_completed_landing_page_blocks()
        raise NotionMcpCallPlanningError(f"Task graph cannot create dynamic page {local_page_key!r}")

    def _validate_fixed_page_keys_and_titles(self) -> None:
        validate_fixed_page_pointer(
            page=self.landing_page,
            expected_local_page_key=LANDING_PAGE_LOCAL_KEY,
            expected_title=LANDING_PAGE_TITLE,
        )
        validate_fixed_page_pointer(
            page=self.completed_landing_page,
            expected_local_page_key=COMPLETED_LANDING_PAGE_LOCAL_KEY,
            expected_title=COMPLETED_LANDING_PAGE_TITLE,
        )

    def _validate_task_keys_match_task_values(self) -> None:
        for task_id, task in self.tasks.items():
            if task_id != task.task_id:
                raise NotionMcpCallPlanningError(f"Task key {task_id!r} does not match task id {task.task_id!r}")

    def _validate_parent_child_links(self) -> None:
        for task_id, task in self.tasks.items():
            if task.parent_task_id is not None:
                self._validate_task_exists(task.parent_task_id)
                parent_task = self.tasks[task.parent_task_id]
                if task_id not in parent_task.child_task_ids:
                    raise NotionMcpCallPlanningError(
                        f"Task {task_id} should be listed as child of {task.parent_task_id}"
                    )
            for child_task_id in task.child_task_ids:
                self._validate_task_exists(child_task_id)
                child_task = self.tasks[child_task_id]
                if child_task.parent_task_id != task_id:
                    raise NotionMcpCallPlanningError(
                        f"Task {child_task_id} should have parent {task_id}"
                    )

    def _validate_task_exists(self, task_id: str) -> None:
        if task_id not in self.tasks:
            raise NotionMcpCallPlanningError(f"Task {task_id} does not exist")

    def _validate_task_hierarchy_has_no_cycles(self) -> None:
        for task_id in self.tasks:
            visited_task_ids = set()
            current_task_id = task_id
            while current_task_id is not None:
                if current_task_id in visited_task_ids:
                    raise NotionMcpCallPlanningError("Task hierarchy has a cycle")
                visited_task_ids.add(current_task_id)
                current_task_id = self.tasks[current_task_id].parent_task_id

    def _landing_root_task_ids_matching(
        self,
        task_should_be_visible: Callable[[TaskPageMetadata], bool],
    ) -> list[str]:
        return [
            task.task_id
            for task in sorted(self.tasks.values(), key=lambda task: _task_id_sort_key(task.task_id))
            if task_should_be_visible(task)
            and self._parent_is_not_visible_on_same_landing(task, task_should_be_visible)
        ]

    def _parent_is_not_visible_on_same_landing(
        self,
        task: TaskPageMetadata,
        task_should_be_visible: Callable[[TaskPageMetadata], bool],
    ) -> bool:
        return task.parent_task_id is None or not task_should_be_visible(self.tasks[task.parent_task_id])

    def _top_level_task_ids_matching(
        self,
        task_should_be_visible: Callable[[TaskPageMetadata], bool],
    ) -> list[str]:
        return [
            task.task_id
            for task in sorted(self.tasks.values(), key=lambda task: _task_id_sort_key(task.task_id))
            if task.parent_task_id is None and task_should_be_visible(task)
        ]

    def _calculate_priority_visible_on_task(self, task: TaskPageMetadata) -> Priority:
        priorities_visible_in_subtree = [task.configured_priority]
        for child_task_id in task.child_task_ids:
            child_task = self.tasks[child_task_id]
            if child_task.should_contribute_priority_to_ancestors():
                priorities_visible_in_subtree.append(child_task.displayed_priority or child_task.configured_priority)
        return _highest_priority(priorities_visible_in_subtree)

    def _normalize_task_timelines(self) -> None:
        for task in self.tasks.values():
            task.timeline_entries = _merged_timeline_entries_by_date(task.timeline_entries)


def _task_should_start_ongoing_landing_tree(task: TaskPageMetadata) -> bool:
    return task.status not in {TaskStatus.COMPLETE, TaskStatus.CANCELLED}


def _task_should_appear_inside_ongoing_landing_tree(task: TaskPageMetadata) -> bool:
    return True


def _upsert_timeline_entry(
    task: TaskPageMetadata,
    timeline_entry: TimelineEntry,
) -> TimelineEntry:
    task.timeline_entries = _merged_timeline_entries_by_date(task.timeline_entries)
    existing_entry = _timeline_entry_for_date(task.timeline_entries, timeline_entry.entry_date)

    if existing_entry is None:
        task.timeline_entries.append(timeline_entry)
        return timeline_entry

    existing_entry.lines.extend(timeline_entry.lines)
    return existing_entry


def _copy_timeline_entry(timeline_entry: TimelineEntry) -> TimelineEntry:
    return TimelineEntry(
        entry_date=timeline_entry.entry_date,
        heading=timeline_entry.heading,
        lines=list(timeline_entry.lines),
        subheading=timeline_entry.subheading,
    )


def _render_timeline_line_blocks(timeline_entry: TimelineEntry) -> list[dict[str, Any]]:
    return _render_timeline_entry_content_blocks(timeline_entry)


def _merged_timeline_entries_by_date(timeline_entries: list[TimelineEntry]) -> list[TimelineEntry]:
    merged_entries_by_date = {}
    merged_entries = []

    for timeline_entry in timeline_entries:
        existing_entry = merged_entries_by_date.get(timeline_entry.entry_date)
        if existing_entry is None:
            merged_entries_by_date[timeline_entry.entry_date] = timeline_entry
            merged_entries.append(timeline_entry)
            continue

        existing_entry.lines.extend(timeline_entry.lines)

    return merged_entries


def _timeline_entry_for_date(
    timeline_entries: list[TimelineEntry],
    entry_date: str,
) -> TimelineEntry | None:
    for timeline_entry in timeline_entries:
        if timeline_entry.entry_date == entry_date:
            return timeline_entry

    return None


def _highest_priority(priorities: list[Priority]) -> Priority:
    return min(priorities, key=lambda priority: _PRIORITY_RANK_BY_VALUE[priority])


def _task_id_sort_key(task_id: str) -> tuple[str, int, str]:
    task_prefix, separator, task_number_text = task_id.rpartition("-")

    if separator and task_number_text.isdigit():
        return task_prefix, int(task_number_text), ""

    return task_id, -1, task_id


def _task_to_snapshot(task: TaskPageMetadata) -> dict[str, Any]:
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
            _timeline_entry_to_snapshot(timeline_entry)
            for timeline_entry in task.timeline_entries
        ],
        "links": [
            external_link_to_snapshot(link)
            for link in task.links
        ],
        "notion_page_id": task.notion_page_id,
    }


def _timeline_entry_to_snapshot(timeline_entry: TimelineEntry) -> dict[str, Any]:
    return {
        "entry_date": timeline_entry.entry_date,
        "heading": timeline_entry.heading,
        "lines": [],
    }


def _task_from_snapshot(snapshot: dict[str, Any]) -> TaskPageMetadata:
    displayed_priority = snapshot.get("displayed_priority")

    return TaskPageMetadata(
        task_id=snapshot["task_id"],
        title=snapshot["title"],
        configured_priority=Priority(snapshot["configured_priority"]),
        displayed_priority=Priority(displayed_priority) if displayed_priority else None,
        status=TaskStatus(snapshot["status"]),
        status_update=snapshot.get("status_update", ""),
        parent_task_id=snapshot.get("parent_task_id"),
        child_task_ids=list(snapshot.get("child_task_ids", [])),
        timeline_entries=[
            _timeline_entry_from_snapshot(timeline_snapshot)
            for timeline_snapshot in snapshot.get("timeline_entries", [])
        ],
        links=[
            external_link_from_snapshot(link_snapshot)
            for link_snapshot in snapshot.get("links", [])
        ],
        notion_page_id=snapshot.get("notion_page_id"),
    )


def _timeline_entry_from_snapshot(snapshot: dict[str, Any]) -> TimelineEntry:
    return TimelineEntry(
        entry_date=snapshot["entry_date"],
        heading=snapshot["heading"],
        lines=[],
    )
