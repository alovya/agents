"""Shared task data shapes and constants."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from notion_task_tracker.common import ExternalLink


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
    blocks: list[dict[str, Any]] = field(default_factory=list)
    subheading: str | None = None


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
