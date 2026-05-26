"""REST implementation of the workflow-level Notion transport."""

from __future__ import annotations

from typing import Any

from notion_task_tracker.commands import CommandResult
from notion_task_tracker.rest.client import NotionRestClient
from notion_task_tracker.notion_transport import (
    CreatedTaskDatabasePage,
    NotionWriteExecutionResult,
    query_task_database_rows_with_client,
)
from notion_task_tracker.tasks.database import TASK_DATABASE_TITLE_PROPERTY


class NotionRestTransport:
    def __init__(self, client: NotionRestClient) -> None:
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
        del content
        created_page = await self.client.create_database_page(
            data_source_id=data_source_id,
            properties=properties,
            blocks=blocks,
        )
        return CreatedTaskDatabasePage(
            notion_page_id=created_page["id"],
            operation_keys=[operation_key],
        )

    async def update_task_database_page_title(
        self,
        page_id: str,
        title_property: str,
        title: str,
        operation_key: str,
    ) -> str:
        await self.client.update_page_properties(
            page_id=page_id,
            properties={title_property or TASK_DATABASE_TITLE_PROPERTY: title},
        )
        return operation_key

    async def execute_command_result(self, command_result: CommandResult) -> NotionWriteExecutionResult:
        if command_result.page_registry is None:
            raise ValueError("REST write execution requires a page registry")

        completed_operation_keys = []
        captured_page_ids = {}
        for write_intent in command_result.write_intents:
            write_result = await self.client.execute_write_intent(write_intent, command_result.page_registry)
            completed_operation_keys.append(write_result["operation_key"])
            if write_result.get("captured_page_key") is not None:
                captured_page_ids[write_result["captured_page_key"]] = write_result["captured_page_id"]

        return NotionWriteExecutionResult(
            completed_operation_keys=completed_operation_keys,
            captured_page_ids=captured_page_ids,
        )
