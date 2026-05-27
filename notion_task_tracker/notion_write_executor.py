"""Execute planned Notion writes through the selected Notion client."""

from __future__ import annotations

from typing import Any

from notion_task_tracker.apply_tracker_command import TrackerCommandResult, apply_command_to_tracker_state
from notion_task_tracker.notion_client import NotionClient


async def execute_command_result_writes(
    command_result: TrackerCommandResult,
    notion_client: NotionClient,
) -> tuple[dict[str, Any], list[str]]:
    if not command_result.write_intents:
        return command_result.tracker_state, []

    write_result = await notion_client.execute_command_result(command_result)
    tracker_state_with_page_ids = _record_captured_page_ids(
        command_result.tracker_state,
        write_result.captured_page_ids,
    )
    if write_result.blocked_operation_count == 0:
        return tracker_state_with_page_ids, write_result.completed_operation_keys

    refresh_result = apply_command_to_tracker_state(
        _refresh_command_for_captured_page_ids(write_result.captured_page_ids),
        tracker_state_with_page_ids,
    )
    refresh_tracker_state, refresh_operation_keys = await execute_command_result_writes(
        refresh_result,
        notion_client,
    )
    return refresh_tracker_state, write_result.completed_operation_keys + refresh_operation_keys


def _record_captured_page_ids(
    tracker_state: dict[str, Any],
    captured_page_ids: dict[str, str],
) -> dict[str, Any]:
    updated_tracker_state = tracker_state
    for local_page_key, notion_page_id in captured_page_ids.items():
        updated_tracker_state = apply_command_to_tracker_state(
            {
                "command": "record_page_id",
                "local_page_key": local_page_key,
                "notion_page_id": notion_page_id,
            },
            updated_tracker_state,
        ).tracker_state
    return updated_tracker_state


def _refresh_command_for_captured_page_ids(captured_page_ids: dict[str, str]) -> dict[str, Any]:
    captured_page_key_prefixes = {
        local_page_key.split(":", 1)[0]
        for local_page_key in captured_page_ids
    }
    if captured_page_key_prefixes == {"completed_landing_page"}:
        return {
            "command": "refresh_task_pages",
            "operation_keys": ["replace:completed_landing_page"],
        }

    if captured_page_key_prefixes == {"miscellaneous"}:
        return {"command": "refresh_miscellaneous_pages"}

    if captured_page_key_prefixes == {"synthesis"}:
        return {"command": "refresh_synthesis_pages"}

    raise ValueError(f"Cannot refresh mixed captured page keys {sorted(captured_page_ids)}")
