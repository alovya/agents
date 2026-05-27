"""Derive task timeline log facts from already fetched page content."""

from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Any

from notion_task_tracker.tasks.timeline_log import (
    check_fetched_task_page_has_usable_timeline_log,
    parse_timeline_entries_from_fetched_task_page_content,
    build_timeline_entry_for_date,
)


def find_task_id_whose_timeline_is_written_by_command(command: dict[str, Any]) -> str | None:
    if command["command"] in {"append_task_timeline_log", "complete_task"}:
        return command["task_id"]

    return None


def record_known_task_timeline_dates(
    task_id: str,
    tracker_state: dict[str, Any],
    timeline_entries: list[dict[str, str]],
) -> dict[str, Any]:
    if not timeline_entries:
        return tracker_state

    updated_tracker_state = json.loads(json.dumps(tracker_state))
    task_timeline_entries = updated_tracker_state["tasks"][task_id].setdefault("timeline_entries", [])
    known_entry_dates = {
        timeline_entry["entry_date"]
        for timeline_entry in task_timeline_entries
    }

    for timeline_entry in timeline_entries:
        if timeline_entry["entry_date"] in known_entry_dates:
            continue

        task_timeline_entries.append({
            "entry_date": timeline_entry["entry_date"],
            "heading": timeline_entry["heading"],
            "lines": [],
        })
        known_entry_dates.add(timeline_entry["entry_date"])

    return updated_tracker_state


@dataclass(frozen=True)
class DerivedTaskTimelineLog:
    tracker_state: dict[str, Any]
    fetched_page_content: str
    has_usable_timeline_log: bool


def derive_task_timeline_log_from_fetched_page_content(
    task_id: str,
    entry_date: str,
    tracker_state: dict[str, Any],
    fetched_page_content: str,
) -> DerivedTaskTimelineLog:
    timeline_entries = parse_timeline_entries_from_fetched_task_page_content(fetched_page_content)
    has_usable_timeline_log = check_fetched_task_page_has_usable_timeline_log(
        fetched_page_content,
        timeline_entries,
    )
    if has_usable_timeline_log:
        return DerivedTaskTimelineLog(
            tracker_state=record_known_task_timeline_dates(
                task_id=task_id,
                tracker_state=tracker_state,
                timeline_entries=timeline_entries,
            ),
            fetched_page_content=fetched_page_content,
            has_usable_timeline_log=True,
        )

    return DerivedTaskTimelineLog(
        tracker_state=record_known_task_timeline_dates(
            task_id=task_id,
            tracker_state=tracker_state,
            timeline_entries=[build_timeline_entry_for_date(entry_date)],
        ),
        fetched_page_content=fetched_page_content,
        has_usable_timeline_log=False,
    )
