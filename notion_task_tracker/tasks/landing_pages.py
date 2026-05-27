"""Task landing-page groupings derived from the dependency graph."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from notion_task_tracker.tasks.task import Priority, Task, TaskStatus, task_id_sort_key
from notion_task_tracker.tracked_pages import TrackedPage


@dataclass
class OngoingTasksLandingPage:
    page: TrackedPage

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
    page: TrackedPage

    def completed_top_level_task_ids(self, tasks: dict[str, Task]) -> list[str]:
        return _top_level_task_ids_matching(tasks, lambda task: task.status == TaskStatus.COMPLETE)

    def cancelled_top_level_task_ids(self, tasks: dict[str, Task]) -> list[str]:
        return _top_level_task_ids_matching(tasks, lambda task: task.status == TaskStatus.CANCELLED)


def visible_ongoing_landing_task_ids(tasks: dict[str, Task]) -> list[str]:
    return _landing_root_task_ids_matching(tasks, _task_should_start_ongoing_landing_tree)


def task_should_appear_inside_ongoing_landing_tree(task: Task) -> bool:
    return True


def landing_root_task_ids_matching(
    tasks: dict[str, Task],
    task_should_be_visible: Callable[[Task], bool],
) -> list[str]:
    return _landing_root_task_ids_matching(tasks, task_should_be_visible)


def top_level_task_ids_matching(
    tasks: dict[str, Task],
    task_should_be_visible: Callable[[Task], bool],
) -> list[str]:
    return _top_level_task_ids_matching(tasks, task_should_be_visible)


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
