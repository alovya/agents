"""Shared task data shapes and constants."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from notion_task_tracker.external_links import ExternalLink
from notion_task_tracker.notion_markdown import bullet, heading, join_markdown_blocks, toggle
from notion_task_tracker.notion_writes import NotionWriteIntent


COMPLETED_TASK_PRIORITY_LABEL = "N/A"
TASK_DATABASE_TITLE_PROPERTY = "Ticket page"
TASK_DATABASE_PRIORITY_PROPERTY = "Priority"
TASK_DATABASE_STATUS_PROPERTY = "Status"

TASK_PAGE_TIMELINE_LOG_HEADING = "Timeline log"

UPDATE_TIMELINE_LOG_OPERATION_NAME = "update_timeline_log"

TASK_ID_PATTERN = re.compile(r"^(ALOVYA-\d+):\s*(.+)$")
MENTION_DATE_START_PATTERN = re.compile(r'<mention-date\s+[^>]*start="([^"]+)"[^>]*/>')
PROPERTIES_BLOCK_PATTERN = re.compile(r"<properties>\s*(.*?)\s*</properties>", re.DOTALL)


class TaskStatus(str, Enum):
    """Status values for task pages."""

    ACTIVE = "Active"
    BLOCKED = "Blocked"
    PARKED = "Parked"
    COMPLETE = "Complete"
    CANCELLED = "Cancelled"


class Priority(str, Enum):
    """Priority assigned directly to a task before graph rollup."""

    P0 = "P0"
    P1 = "P1"
    P2 = "P2"
    P3 = "P3"


_PRIORITY_RANK_BY_VALUE = {
    Priority.P0: 0,
    Priority.P1: 1,
    Priority.P2: 2,
    Priority.P3: 3,
}

_STATUS_VALUES_THAT_PROPAGATE_PRIORITY = {
    TaskStatus.ACTIVE,
    TaskStatus.BLOCKED,
}

LANDING_HEADING_BY_PRIORITY = {
    Priority.P0: "P0 (high impact and urgent)",
    Priority.P1: "P1 (high impact)",
    Priority.P2: "P2 (lower impact but urgent)",
    Priority.P3: "P3 (lower impact and not urgent)",
}

LANDING_COLOR_BY_PRIORITY = {
    Priority.P0: "red",
    Priority.P1: "orange",
    Priority.P2: "yellow",
    Priority.P3: "gray",
}

LANDING_COLOR_BY_STATUS = {
    TaskStatus.COMPLETE: "green",
    TaskStatus.CANCELLED: "gray",
}


@dataclass
class TimelineEntry:
    """One date-grouped timeline section owned by a single task."""

    entry_date: str
    heading: str
    lines: list[str] = field(default_factory=list)
    subheading: str | None = None

    def to_content_markdown(self) -> str:
        lines_markdown = join_markdown_blocks([bullet(line) for line in self.lines])
        if self.subheading:
            return toggle(self.subheading, lines_markdown)

        return lines_markdown

    def to_timeline_section_markdown(self) -> str:
        return join_markdown_blocks([
            heading(3, self.heading),
            self.to_content_markdown(),
        ])

    def to_tracker_state(self) -> dict[str, Any]:
        return {
            "entry_date": self.entry_date,
            "heading": self.heading,
            "lines": [],
        }

    @classmethod
    def from_tracker_state(cls, tracker_state: dict[str, Any]) -> "TimelineEntry":
        return cls(
            entry_date=tracker_state["entry_date"],
            heading=tracker_state["heading"],
            lines=[],
        )

    @classmethod
    def from_command(cls, command: dict[str, Any]) -> "TimelineEntry":
        entry_date = command["entry_date"]
        return cls(
            entry_date=entry_date,
            heading=_date_only_timeline_heading(command.get("heading", ""), entry_date),
            lines=list(command.get("lines", [])),
            subheading=command.get("subheading"),
        )


@dataclass
class Task:
    """Metadata for one task."""

    task_id: str
    title: str
    configured_priority: Priority
    status: TaskStatus
    status_update: str = ""
    parent_task_id: str | None = None
    child_task_ids: list[str] = field(default_factory=list)
    timeline_entries: list[TimelineEntry] = field(default_factory=list)
    links: list[ExternalLink] = field(default_factory=list)
    notion_page_id: str | None = None
    displayed_priority: Priority | None = None

    @property
    def local_page_key(self) -> str:
        return f"task:{self.task_id}"

    def should_contribute_priority_to_ancestors(self) -> bool:
        return self.status in _STATUS_VALUES_THAT_PROPAGATE_PRIORITY

    def page_title(self) -> str:
        if self.status == TaskStatus.COMPLETE:
            return _render_visible_strikethrough_text(self.title)

        return self.title

    def database_property_refresh_intent(self) -> NotionWriteIntent:
        return NotionWriteIntent(
            operation_key=f"update_properties:{self.local_page_key}",
            operation_name="update_page_properties",
            target_page_key=self.local_page_key,
            arguments={
                "properties": {
                    TASK_DATABASE_TITLE_PROPERTY: self.page_title(),
                    TASK_DATABASE_PRIORITY_PROPERTY: self.configured_priority.value,
                    TASK_DATABASE_STATUS_PROPERTY: self.status.value,
                }
            },
        )

    def append_timeline_log(self, timeline_entry: TimelineEntry) -> NotionWriteIntent:
        self.timeline_entries = _merged_timeline_entries_by_date(self.timeline_entries)
        existing_entry = _timeline_entry_for_date(self.timeline_entries, timeline_entry.entry_date)
        existing_entry_before_append = _copy_timeline_entry(existing_entry) if existing_entry is not None else None
        appended_entry = _copy_timeline_entry(timeline_entry)
        timeline_entry_to_render = _upsert_timeline_entry(self, timeline_entry)
        return self._timeline_log_update_intent(
            existing_timeline_entry=existing_entry_before_append,
            appended_timeline_entry=appended_entry,
            timeline_entry=timeline_entry_to_render,
        )

    def complete_with_timeline_log(self, timeline_entry: TimelineEntry) -> tuple[NotionWriteIntent, NotionWriteIntent]:
        self.status = TaskStatus.COMPLETE
        timeline_log_update_intent = self.append_timeline_log(timeline_entry)
        return self.database_property_refresh_intent(), timeline_log_update_intent

    def normalise_timeline_entries(self) -> None:
        self.timeline_entries = _merged_timeline_entries_by_date(self.timeline_entries)

    def _timeline_log_update_intent(
        self,
        existing_timeline_entry: TimelineEntry | None,
        appended_timeline_entry: TimelineEntry,
        timeline_entry: TimelineEntry,
    ) -> NotionWriteIntent:
        arguments = {
            "task_id": self.task_id,
            "timeline_log_heading": TASK_PAGE_TIMELINE_LOG_HEADING,
            "timeline_entry": timeline_entry.to_tracker_state(),
            "timeline_section_markdown": timeline_entry.to_timeline_section_markdown(),
        }
        if existing_timeline_entry is not None:
            arguments["existing_timeline_heading"] = existing_timeline_entry.heading
            arguments["old_timeline_section_markdown"] = existing_timeline_entry.to_timeline_section_markdown()
            arguments["new_timeline_section_markdown"] = timeline_entry.to_timeline_section_markdown()
            arguments["appended_markdown"] = appended_timeline_entry.to_content_markdown()

        return NotionWriteIntent(
            operation_key=f"{UPDATE_TIMELINE_LOG_OPERATION_NAME}:{self.local_page_key}:{timeline_entry.entry_date}",
            operation_name=UPDATE_TIMELINE_LOG_OPERATION_NAME,
            target_page_key=self.local_page_key,
            arguments=arguments,
        )


def task_id_sort_key(task_id: str) -> tuple[str, int, str]:
    task_prefix, separator, task_number_text = task_id.rpartition("-")

    if separator and task_number_text.isdigit():
        return task_prefix, int(task_number_text), ""

    return task_id, -1, task_id


def _upsert_timeline_entry(
    task: Task,
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


def _date_only_timeline_heading(raw_heading: str, entry_date: str) -> str:
    date_match = MENTION_DATE_START_PATTERN.search(raw_heading)
    if date_match is not None:
        return f'<mention-date start="{date_match.group(1)}"/>'

    return f'<mention-date start="{entry_date}"/>'


def _render_visible_strikethrough_text(text: str) -> str:
    return "".join(f"{character}\u0336" for character in text)
