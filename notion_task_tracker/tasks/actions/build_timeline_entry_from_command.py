"""Build task timeline entries from command JSON."""

from __future__ import annotations

from typing import Any

from notion_task_tracker.tasks import TimelineEntry
from notion_task_tracker.tasks.task import MENTION_DATE_START_PATTERN


def timeline_entry_from_command(command: dict[str, Any]) -> TimelineEntry:
    entry_date = command["entry_date"]
    return TimelineEntry(
        entry_date=entry_date,
        heading=_date_only_timeline_heading(command.get("heading", ""), entry_date),
        lines=list(command.get("lines", [])),
        blocks=list(command.get("blocks", [])),
        subheading=command.get("subheading"),
    )


def _date_only_timeline_heading(raw_heading: str, entry_date: str) -> str:
    date_match = MENTION_DATE_START_PATTERN.search(raw_heading)
    if date_match is not None:
        return f'<mention-date start="{date_match.group(1)}"/>'

    return f'<mention-date start="{entry_date}"/>'
