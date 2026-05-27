"""Task landing pages derived from the task dependency graph."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from notion_task_tracker.notion_markdown import bullet, heading, join_markdown_blocks, page_mention
from notion_task_tracker.notion_writes import NotionWriteIntent
from notion_task_tracker.page_registry import NotionPageRegistry, PagePointer
from notion_task_tracker.tasks.task import (
    COMPLETED_TASK_PRIORITY_LABEL,
    LANDING_COLOR_BY_PRIORITY,
    LANDING_COLOR_BY_STATUS,
    LANDING_HEADING_BY_PRIORITY,
    Priority,
    Task,
    TaskStatus,
    task_id_sort_key,
)


@dataclass
class OngoingTasksLandingPage:
    page: PagePointer

    def creation_intent(self, markdown: str) -> NotionWriteIntent | None:
        if self.page.notion_page_id is not None:
            return None

        return _page_creation_intent(self.page, markdown)

    def title_refresh_intent(self) -> NotionWriteIntent | None:
        if self.page.notion_page_id is None:
            return None

        return _page_title_refresh_intent(self.page)

    def refresh_intent(self, tasks: dict[str, Task], page_registry: NotionPageRegistry) -> NotionWriteIntent:
        return NotionWriteIntent(
            operation_key="replace:landing_page",
            operation_name="replace_page_markdown",
            target_page_key=self.page.local_page_key,
            arguments={"markdown": self.render_markdown(tasks, page_registry)},
        )

    def render_markdown(self, tasks: dict[str, Task], page_registry: NotionPageRegistry) -> str:
        markdown_blocks = []
        for priority, task_ids in self.task_ids_grouped_by_priority(tasks).items():
            if task_ids:
                markdown_blocks.append(heading(2, LANDING_HEADING_BY_PRIORITY[priority]))
                for task_id in task_ids:
                    markdown_blocks.append(
                        _render_task_tree_markdown(
                            tasks=tasks,
                            task_id=task_id,
                            depth=0,
                            task_should_be_visible=_task_should_appear_inside_ongoing_landing_tree,
                            page_registry=page_registry,
                        )
                    )
        return join_markdown_blocks(markdown_blocks)

    def task_ids_grouped_by_priority(self, tasks: dict[str, Task]) -> dict[Priority, list[str]]:
        return {
            priority: [
                task_id
                for task_id in _landing_root_task_ids_matching(tasks, _task_should_start_ongoing_landing_tree)
                if tasks[task_id].displayed_priority == priority
            ]
            for priority in Priority
        }


@dataclass
class CompletedTasksLandingPage:
    page: PagePointer

    def creation_intent(self, markdown: str) -> NotionWriteIntent | None:
        if self.page.notion_page_id is not None:
            return None

        return _page_creation_intent(self.page, markdown)

    def title_refresh_intent(self) -> NotionWriteIntent | None:
        if self.page.notion_page_id is None:
            return None

        return _page_title_refresh_intent(self.page)

    def refresh_intents(self, tasks: dict[str, Task], page_registry: NotionPageRegistry) -> list[NotionWriteIntent]:
        if self.page.notion_page_id is None:
            return []

        return [
            NotionWriteIntent(
                operation_key="replace:completed_landing_page",
                operation_name="replace_page_markdown",
                target_page_key=self.page.local_page_key,
                arguments={"markdown": self.render_markdown(tasks, page_registry)},
            )
        ]

    def render_markdown(self, tasks: dict[str, Task], page_registry: NotionPageRegistry) -> str:
        markdown_blocks = []
        self._append_status_section(TaskStatus.COMPLETE, "Completed", tasks, markdown_blocks, page_registry)
        self._append_status_section(TaskStatus.CANCELLED, "Cancelled", tasks, markdown_blocks, page_registry)
        return join_markdown_blocks(markdown_blocks) or "No completed tasks yet."

    def completed_top_level_task_ids(self, tasks: dict[str, Task]) -> list[str]:
        return _top_level_task_ids_matching(tasks, lambda task: task.status == TaskStatus.COMPLETE)

    def cancelled_top_level_task_ids(self, tasks: dict[str, Task]) -> list[str]:
        return _top_level_task_ids_matching(tasks, lambda task: task.status == TaskStatus.CANCELLED)

    def _append_status_section(
        self,
        status: TaskStatus,
        section_title: str,
        tasks: dict[str, Task],
        markdown_blocks: list[str],
        page_registry: NotionPageRegistry,
    ) -> None:
        task_should_be_visible = lambda task: task.status == status
        task_ids = _top_level_task_ids_matching(tasks, task_should_be_visible)
        if task_ids:
            markdown_blocks.append(heading(2, section_title))
            for task_id in task_ids:
                markdown_blocks.append(
                    _render_task_tree_markdown(
                        tasks=tasks,
                        task_id=task_id,
                        depth=0,
                        task_should_be_visible=task_should_be_visible,
                        page_registry=page_registry,
                    )
                )


def _page_creation_intent(page: PagePointer, markdown: str) -> NotionWriteIntent:
    return NotionWriteIntent(
        operation_key=f"create:{page.local_page_key}",
        operation_name="create_page",
        target_page_key=None,
        arguments={
            "local_page_key": page.local_page_key,
            "title": page.title,
            "parent_page_key": page.parent_page_key,
            "markdown": markdown,
        },
    )


def _page_title_refresh_intent(page: PagePointer) -> NotionWriteIntent:
    return NotionWriteIntent(
        operation_key=f"update_properties:{page.local_page_key}",
        operation_name="update_page_properties",
        target_page_key=page.local_page_key,
        arguments={"properties": {"title": page.title}},
    )


def _render_task_tree_markdown(
    tasks: dict[str, Task],
    task_id: str,
    depth: int,
    task_should_be_visible: Callable[[Task], bool],
    page_registry: NotionPageRegistry,
) -> str:
    task = tasks[task_id]
    displayed_priority = task.displayed_priority or task.configured_priority
    lines = [
        bullet(
            text=_format_landing_task_text(task, displayed_priority, page_registry),
            depth=depth,
            colour=_landing_color_for_task(task, displayed_priority),
        )
    ]
    for child_task_id in sorted(task.child_task_ids, key=task_id_sort_key):
        child_task = tasks[child_task_id]
        if task_should_be_visible(child_task):
            lines.append(
                _render_task_tree_markdown(
                    tasks=tasks,
                    task_id=child_task_id,
                    depth=depth + 1,
                    task_should_be_visible=task_should_be_visible,
                    page_registry=page_registry,
                )
            )
    return join_markdown_blocks(lines)


def _landing_root_task_ids_matching(
    tasks: dict[str, Task],
    task_should_be_visible: Callable[[Task], bool],
) -> list[str]:
    return [
        task.task_id
        for task in sorted(tasks.values(), key=lambda task: task_id_sort_key(task.task_id))
        if task_should_be_visible(task)
        and _parent_is_not_visible_on_same_landing(tasks, task, task_should_be_visible)
    ]


def _parent_is_not_visible_on_same_landing(
    tasks: dict[str, Task],
    task: Task,
    task_should_be_visible: Callable[[Task], bool],
) -> bool:
    return task.parent_task_id is None or not task_should_be_visible(tasks[task.parent_task_id])


def _top_level_task_ids_matching(
    tasks: dict[str, Task],
    task_should_be_visible: Callable[[Task], bool],
) -> list[str]:
    return [
        task.task_id
        for task in sorted(tasks.values(), key=lambda task: task_id_sort_key(task.task_id))
        if task.parent_task_id is None and task_should_be_visible(task)
    ]


def _task_should_start_ongoing_landing_tree(task: Task) -> bool:
    return task.status not in {TaskStatus.COMPLETE, TaskStatus.CANCELLED}


def _task_should_appear_inside_ongoing_landing_tree(task: Task) -> bool:
    return True


def _format_landing_task_text(
    task: Task,
    displayed_priority: Priority,
    page_registry: NotionPageRegistry,
) -> str:
    priority_label = _priority_label_for_task(task, displayed_priority)
    return f"[{priority_label}] {page_mention(task.local_page_key, page_registry)}: {task.status.value}"


def _landing_color_for_task(task: Task, displayed_priority: Priority) -> str:
    return LANDING_COLOR_BY_STATUS.get(
        task.status,
        LANDING_COLOR_BY_PRIORITY[displayed_priority],
    )


def _priority_label_for_task(task: Task, displayed_priority: Priority) -> str:
    if task.status == TaskStatus.COMPLETE:
        return COMPLETED_TASK_PRIORITY_LABEL

    return displayed_priority.value
