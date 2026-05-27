"""Derive normal task command writes from current Notion state."""

from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Any

from notion_task_tracker.apply_tracker_command import TrackerCommandResult, apply_command_to_tracker_state
from notion_task_tracker.notion_io.writes import NotionWriteIntent
from notion_task_tracker.notion_io.client import NotionClient
from notion_task_tracker.tasks.task import UPDATE_TIMELINE_LOG_OPERATION_NAME
from notion_task_tracker.tasks.pages.timeline_log import (
    fetched_task_page_has_usable_timeline_log,
    initialised_task_timeline_markdown,
    timeline_entries_from_fetched_task_page_content,
    timeline_entry_for_date,
)
from notion_task_tracker.tasks.actions.refresh_task_tracker_state import (
    repair_result_for_task_graph_changes,
    refresh_tracker_state_for_command_targets,
)
from notion_task_tracker.tasks import TaskDependencyGraph


async def tracker_state_ready_for_command(
    command: dict[str, Any],
    tracker_state: dict[str, Any],
    notion_client: NotionClient,
) -> TrackerCommandResult:
    if _is_task_command(command):
        return await refresh_tracker_state_for_command_targets(
            command=command,
            tracker_state=tracker_state,
            notion_client=notion_client,
        )

    return TrackerCommandResult(tracker_state=tracker_state, warnings=[])


async def command_result_from_current_notion_state(
    command: dict[str, Any],
    tracker_state: dict[str, Any],
    notion_client: NotionClient,
) -> TrackerCommandResult:
    task_id = task_id_whose_timeline_is_written_by_command(command)
    if task_id is None:
        return apply_command_to_tracker_state(command, tracker_state)

    timeline_state = await timeline_state_for_task_command(
        task_id=task_id,
        entry_date=command["timeline_entry"]["entry_date"],
        tracker_state=tracker_state,
        notion_client=notion_client,
    )
    command_result = apply_command_to_tracker_state(command, timeline_state.tracker_state)
    if timeline_state.has_usable_timeline_log:
        return command_result

    return _command_result_with_initialised_task_timeline(
        command_result=command_result,
        task_id=task_id,
        entry_date=command["timeline_entry"]["entry_date"],
        fetched_page_content=timeline_state.fetched_page_content,
    )


def repair_result_for_command_context(
    before_tracker_state: dict[str, Any],
    command_ready_result: TrackerCommandResult,
) -> TrackerCommandResult:
    return repair_result_for_task_graph_changes(
        refreshed_result=command_ready_result,
        task_graph_changes=TaskDependencyGraph.changes_between_tracker_states(
            before_tracker_state,
            command_ready_result.tracker_state,
        ),
    )


def command_result_with_context_repairs(
    context_repair_result: TrackerCommandResult,
    command_result: TrackerCommandResult,
) -> TrackerCommandResult:
    write_intents_by_key = {
        write_intent.operation_key: write_intent
        for write_intent in context_repair_result.write_intents
    }
    for write_intent in command_result.write_intents:
        write_intents_by_key[write_intent.operation_key] = write_intent

    return TrackerCommandResult(
        tracker_state=command_result.tracker_state,
        write_intents=list(write_intents_by_key.values()),
        page_registry=command_result.page_registry or context_repair_result.page_registry,
        warnings=list(context_repair_result.warnings or []) + list(command_result.warnings or []),
    )


def task_id_whose_timeline_is_written_by_command(command: dict[str, Any]) -> str | None:
    if command["command"] in {"append_task_timeline_log", "complete_task"}:
        return command["task_id"]

    return None


async def tracker_state_with_fetched_task_timeline_dates(
    task_id: str,
    tracker_state: dict[str, Any],
    notion_client: NotionClient,
) -> dict[str, Any]:
    notion_page_id = tracker_state["tasks"][task_id].get("notion_page_id")
    if notion_page_id is None:
        return tracker_state

    fetched_page_content = await notion_client.fetch_task_page_content(notion_page_id)
    return tracker_state_with_known_task_timeline_dates(
        task_id=task_id,
        tracker_state=tracker_state,
        timeline_entries=timeline_entries_from_fetched_task_page_content(fetched_page_content),
    )


@dataclass(frozen=True)
class TimelineStateForCommand:
    tracker_state: dict[str, Any]
    fetched_page_content: str
    has_usable_timeline_log: bool


async def timeline_state_for_task_command(
    task_id: str,
    entry_date: str,
    tracker_state: dict[str, Any],
    notion_client: NotionClient,
) -> TimelineStateForCommand:
    notion_page_id = tracker_state["tasks"][task_id].get("notion_page_id")
    if notion_page_id is None:
        return TimelineStateForCommand(
            tracker_state=tracker_state,
            fetched_page_content="",
            has_usable_timeline_log=True,
        )

    fetched_page_content = await notion_client.fetch_task_page_content(notion_page_id)
    timeline_entries = timeline_entries_from_fetched_task_page_content(fetched_page_content)
    has_usable_timeline_log = fetched_task_page_has_usable_timeline_log(
        fetched_page_content,
        timeline_entries,
    )
    if has_usable_timeline_log:
        return TimelineStateForCommand(
            tracker_state=tracker_state_with_known_task_timeline_dates(
                task_id=task_id,
                tracker_state=tracker_state,
                timeline_entries=timeline_entries,
            ),
            fetched_page_content=fetched_page_content,
            has_usable_timeline_log=True,
        )

    return TimelineStateForCommand(
        tracker_state=tracker_state_with_known_task_timeline_dates(
            task_id=task_id,
            tracker_state=tracker_state,
            timeline_entries=[timeline_entry_for_date(entry_date)],
        ),
        fetched_page_content=fetched_page_content,
        has_usable_timeline_log=False,
    )


def tracker_state_with_known_task_timeline_dates(
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


def _is_task_command(command: dict[str, Any]) -> bool:
    return command["command"] in {
        "append_task_timeline_log",
        "complete_task",
        "create_child_task",
        "create_sibling_task",
    }


def _command_result_with_initialised_task_timeline(
    command_result: TrackerCommandResult,
    task_id: str,
    entry_date: str,
    fetched_page_content: str,
) -> TrackerCommandResult:
    replacement_write_intent = _initialised_task_timeline_write_intent(
        task_id,
        entry_date,
        fetched_page_content,
        command_result,
    )
    return TrackerCommandResult(
        tracker_state=command_result.tracker_state,
        write_intents=[
            replacement_write_intent
            if write_intent.operation_key == replacement_write_intent.operation_key
            else write_intent
            for write_intent in command_result.write_intents
        ],
        page_registry=command_result.page_registry,
        warnings=command_result.warnings,
    )


def _initialised_task_timeline_write_intent(
    task_id: str,
    entry_date: str,
    fetched_page_content: str,
    command_result: TrackerCommandResult,
) -> NotionWriteIntent:
    timeline_write_intent = _task_timeline_write_intent(command_result, task_id, entry_date)
    return NotionWriteIntent(
        operation_key=timeline_write_intent.operation_key,
        operation_name="replace_page_markdown",
        target_page_key=timeline_write_intent.target_page_key,
        arguments={
            "markdown": initialised_task_timeline_markdown(
                entry_date=entry_date,
                timeline_section_markdown=timeline_write_intent.arguments["timeline_section_markdown"],
                fetched_page_content=fetched_page_content,
            ),
        },
    )


def _task_timeline_write_intent(
    command_result: TrackerCommandResult,
    task_id: str,
    entry_date: str,
) -> NotionWriteIntent:
    operation_key = f"{UPDATE_TIMELINE_LOG_OPERATION_NAME}:task:{task_id}:{entry_date}"
    for write_intent in command_result.write_intents:
        if write_intent.operation_key == operation_key:
            return write_intent

    raise ValueError(f"Command result did not include timeline update {operation_key!r}")
