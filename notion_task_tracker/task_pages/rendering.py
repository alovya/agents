"""Render task graph metadata into Notion blocks."""

from __future__ import annotations

from typing import Any

from notion_task_tracker.common import heading_block, paragraph_block, toggle_block
from notion_task_tracker.task_pages.task_metadata import (
    COMPLETED_TASK_PRIORITY_LABEL,
    LANDING_COLOR_BY_PRIORITY,
    LANDING_COLOR_BY_STATUS,
    Priority,
    TaskPageMetadata,
    TaskStatus,
    TimelineEntry,
)


def _render_task_page_title(task: TaskPageMetadata) -> str:
    task_title = _format_task_title(task)
    if task.status == TaskStatus.COMPLETE:
        return _render_visible_strikethrough_text(task_title)

    return task_title


def _render_timeline_blocks(timeline_entries: list[TimelineEntry]) -> list[dict[str, Any]]:
    if not timeline_entries:
        return [paragraph_block(text="No timeline entries yet.")]

    blocks = []

    for timeline_entry in sorted(timeline_entries, key=lambda entry: entry.entry_date, reverse=True):
        blocks.append(heading_block(level=3, text=timeline_entry.heading))
        blocks.extend(_render_timeline_entry_content_blocks(timeline_entry))

    return blocks


def _format_landing_task_text(task: TaskPageMetadata, displayed_priority: Priority) -> str:
    priority_label = _priority_label_for_task(task, displayed_priority)
    return f"[{priority_label}] {_format_task_title(task)}: {task.status.value}"


def _landing_color_for_task(task: TaskPageMetadata, displayed_priority: Priority) -> str:
    return LANDING_COLOR_BY_STATUS.get(
        task.status,
        LANDING_COLOR_BY_PRIORITY[displayed_priority],
    )


def _priority_label_for_task(task: TaskPageMetadata, displayed_priority: Priority) -> str:
    if task.status == TaskStatus.COMPLETE:
        return COMPLETED_TASK_PRIORITY_LABEL

    return displayed_priority.value


def _format_task_title(task: TaskPageMetadata) -> str:
    return task.title


def _render_visible_strikethrough_text(text: str) -> str:
    return "".join(f"{character}\u0336" for character in text)


def _render_timeline_entry_content_blocks(timeline_entry: TimelineEntry) -> list[dict[str, Any]]:
    line_blocks = [_timeline_line_block(line) for line in timeline_entry.lines]
    if timeline_entry.subheading:
        return [toggle_block(text=timeline_entry.subheading, children=line_blocks)]

    return line_blocks


def _timeline_line_block(line: str) -> dict[str, Any]:
    return {
        "type": "bulleted_list_item",
        "depth": 0,
        "text": line,
    }
