"""Complete a task and emit the Notion writes that show completion."""

from __future__ import annotations

from typing import Any

from notion_task_tracker.tasks.actions.build_timeline_entry_from_command import timeline_entry_from_command
from notion_task_tracker.tasks import TaskDependencyGraph


def complete_task_from_command(work_graph: TaskDependencyGraph, command: dict[str, Any]):
    return work_graph.complete_task(
        task_id=command["task_id"],
        timeline_entry=timeline_entry_from_command(command["timeline_entry"]),
    )
