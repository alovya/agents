"""MCP implementation of the workflow-level Notion transport."""

from __future__ import annotations

import json
import re
from typing import Any

from notion_task_tracker.commands import CommandResult
from notion_task_tracker.mcp.calls import NotionMcpCallPlan, NotionMcpCallPlanner, NotionMcpToolCall
from notion_task_tracker.mcp.client import NotionMcpClient
from notion_task_tracker.notion_transport import (
    CreatedTaskDatabasePage,
    NotionWriteExecutionResult,
    query_task_database_rows_with_client,
)


class NotionMcpTransport:
    def __init__(self, client: NotionMcpClient) -> None:
        self.client = client

    async def fetch_task_page_content(self, page_id: str) -> str:
        return await self.client.fetch_task_page_content(page_id)

    async def query_task_database_rows(self, tracker_state: dict[str, Any]) -> list[dict[str, Any]]:
        return await query_task_database_rows_with_client(self.client, tracker_state)

    async def create_task_database_page(
        self,
        data_source_id: str,
        properties: dict[str, Any],
        blocks: list[dict[str, Any]],
        content: str,
        operation_key: str,
    ) -> CreatedTaskDatabasePage:
        del blocks
        create_result = await self.client.send_call(
            NotionMcpToolCall(
                operation_key=operation_key,
                tool_name="notion-create-pages",
                arguments={
                    "parent": {
                        "type": "data_source_id",
                        "data_source_id": data_source_id,
                    },
                    "pages": [
                        {
                            "properties": properties,
                            "content": content,
                        }
                    ],
                },
            )
        )
        return CreatedTaskDatabasePage(
            notion_page_id=_notion_page_id_from_tool_result(create_result),
            operation_keys=[operation_key],
        )

    async def update_task_database_page_title(
        self,
        page_id: str,
        title_property: str,
        title: str,
        operation_key: str,
    ) -> str:
        await self.client.send_call(
            NotionMcpToolCall(
                operation_key=operation_key,
                tool_name="notion-update-page",
                arguments={
                    "page_id": page_id,
                    "command": "update_properties",
                    "properties": {
                        title_property: title,
                    },
                },
            )
        )
        return operation_key

    async def execute_command_result(self, command_result: CommandResult) -> NotionWriteExecutionResult:
        if command_result.page_registry is None:
            raise ValueError("MCP write execution requires a page registry")

        call_plan = NotionMcpCallPlanner(command_result.page_registry).compile_write_intents(command_result.write_intents)
        completed_operation_keys, captured_page_ids = await _execute_available_calls(self.client, call_plan)
        if call_plan.blocked_operations and not captured_page_ids:
            _raise_if_call_plan_has_blocked_operations(call_plan)
        return NotionWriteExecutionResult(
            completed_operation_keys=completed_operation_keys,
            captured_page_ids=captured_page_ids,
            blocked_operation_count=len(call_plan.blocked_operations),
        )


def _raise_if_call_plan_has_blocked_operations(call_plan: NotionMcpCallPlan) -> None:
    if not call_plan.blocked_operations:
        return

    raise ValueError(
        json.dumps(
            {
                "blocked_operations": [
                    blocked_operation.to_snapshot()
                    for blocked_operation in call_plan.blocked_operations
                ],
            },
            indent=2,
            sort_keys=True,
        )
    )


async def _execute_available_calls(
    client: NotionMcpClient,
    call_plan: NotionMcpCallPlan,
) -> tuple[list[str], dict[str, str]]:
    completed_operation_keys = []
    captured_page_ids = {}
    for tool_call in call_plan.calls:
        tool_result = await client.send_call(tool_call)
        completed_operation_keys.append(tool_call.operation_key)
        if tool_call.captures_page_key is not None:
            captured_page_ids[tool_call.captures_page_key] = _notion_page_id_from_tool_result(tool_result)
    return completed_operation_keys, captured_page_ids


def _notion_page_id_from_tool_result(tool_result: dict[str, Any]) -> str:
    tool_text = str(tool_result.get("result", {}).get("text", ""))
    page_id_match = re.search(
        r"(?P<page_id>[0-9a-fA-F]{32}|[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})",
        tool_text,
    )
    if page_id_match is None:
        raise ValueError(f"Could not find Notion page id in tool result {tool_result!r}")

    return page_id_match.group("page_id").replace("-", "")
