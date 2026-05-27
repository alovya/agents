"""Fetch task pages before deriving timeline log writes."""

from __future__ import annotations

from typing import Any

from notion_task_tracker.apply_tracker_command import TrackerCommandResult, apply_command_to_tracker_state
from notion_task_tracker.notion_operations.client import NotionClient
from notion_task_tracker.notion_operations.write_intent import NotionWriteIntent
from notion_task_tracker.tasks.task import UPDATE_TIMELINE_LOG_OPERATION_NAME
from notion_task_tracker.tasks.timeline_log import render_initialised_task_timeline_markdown
from notion_task_tracker.tasks.derive_task_timeline_log import (
    find_task_id_whose_timeline_is_written_by_command,
    derive_task_timeline_log_from_fetched_page_content,
)
from notion_task_tracker.tasks import TaskDependencyGraph
from notion_task_tracker.notion_operations.reconcile_task_database import plan_repairs_for_task_graph_changes


def plan_context_repair_result(
    before_tracker_state: dict[str, Any],
    command_ready_result: TrackerCommandResult,
) -> TrackerCommandResult:
    return plan_repairs_for_task_graph_changes(
        refreshed_result=command_ready_result,
        task_graph_changes=TaskDependencyGraph.changes_between_tracker_states(
            before_tracker_state,
            command_ready_result.tracker_state,
        ),
    )


def merge_context_repairs_into_command_result(
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


async def prepare_command_result_from_current_task_page(
    command: dict[str, Any],
    tracker_state: dict[str, Any],
    notion_client: NotionClient,
) -> TrackerCommandResult:
    task_id = find_task_id_whose_timeline_is_written_by_command(command)
    if task_id is None:
        return apply_command_to_tracker_state(command, tracker_state)

    notion_page_id = tracker_state["tasks"][task_id].get("notion_page_id")
    if notion_page_id is None:
        return apply_command_to_tracker_state(command, tracker_state)

    fetched_page_content = await notion_client.fetch_task_page_content(notion_page_id)
    derived_timeline_log = derive_task_timeline_log_from_fetched_page_content(
        task_id=task_id,
        entry_date=command["timeline_entry"]["entry_date"],
        tracker_state=tracker_state,
        fetched_page_content=fetched_page_content,
    )
    command_result = apply_command_to_tracker_state(command, derived_timeline_log.tracker_state)
    if derived_timeline_log.has_usable_timeline_log:
        return command_result

    return _replace_timeline_write_with_initialised_page_write(
        command_result=command_result,
        task_id=task_id,
        entry_date=command["timeline_entry"]["entry_date"],
        fetched_page_content=derived_timeline_log.fetched_page_content,
    )


def _replace_timeline_write_with_initialised_page_write(
    command_result: TrackerCommandResult,
    task_id: str,
    entry_date: str,
    fetched_page_content: str,
) -> TrackerCommandResult:
    replacement_write_intent = _build_initialised_task_timeline_write_intent(
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


def _build_initialised_task_timeline_write_intent(
    task_id: str,
    entry_date: str,
    fetched_page_content: str,
    command_result: TrackerCommandResult,
) -> NotionWriteIntent:
    timeline_write_intent = _find_task_timeline_write_intent(command_result, task_id, entry_date)
    return NotionWriteIntent(
        operation_key=timeline_write_intent.operation_key,
        operation_name="replace_page_markdown",
        target_page_key=timeline_write_intent.target_page_key,
        arguments={
            "markdown": render_initialised_task_timeline_markdown(
                entry_date=entry_date,
                timeline_section_markdown=timeline_write_intent.arguments["timeline_section_markdown"],
                fetched_page_content=fetched_page_content,
            ),
        },
    )


def _find_task_timeline_write_intent(
    command_result: TrackerCommandResult,
    task_id: str,
    entry_date: str,
) -> NotionWriteIntent:
    operation_key = f"{UPDATE_TIMELINE_LOG_OPERATION_NAME}:task:{task_id}:{entry_date}"
    for write_intent in command_result.write_intents:
        if write_intent.operation_key == operation_key:
            return write_intent

    raise ValueError(f"Command result did not include timeline update {operation_key!r}")
