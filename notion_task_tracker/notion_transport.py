"""Workflow-level Notion transport interface."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

from notion_task_tracker.commands import CommandResult
from notion_task_tracker.mcp.client import NotionMcpClient
from notion_task_tracker.rest.client import NotionRestClient
from notion_task_tracker.tasks.database import (
    task_database_data_source_url_from_tracker_state,
    task_database_query_for_tracker_state,
    task_database_view_url_from_tracker_state,
)


@dataclass(frozen=True)
class CreatedTaskDatabasePage:
    notion_page_id: str
    operation_keys: list[str]


@dataclass(frozen=True)
class NotionWriteExecutionResult:
    completed_operation_keys: list[str] = field(default_factory=list)
    captured_page_ids: dict[str, str] = field(default_factory=dict)
    blocked_operation_count: int = 0


class NotionTransport(Protocol):
    async def fetch_task_page_content(self, page_id: str) -> str:
        raise NotImplementedError

    async def query_task_database_rows(self, tracker_state: dict[str, Any]) -> list[dict[str, Any]]:
        raise NotImplementedError

    async def create_task_database_page(
        self,
        data_source_id: str,
        properties: dict[str, Any],
        blocks: list[dict[str, Any]],
        content: str,
        operation_key: str,
    ) -> CreatedTaskDatabasePage:
        raise NotImplementedError

    async def update_task_database_page_title(
        self,
        page_id: str,
        title_property: str,
        title: str,
        operation_key: str,
    ) -> str:
        raise NotImplementedError

    async def execute_command_result(self, command_result: CommandResult) -> NotionWriteExecutionResult:
        raise NotImplementedError


def notion_transport_from_credentials_path(credentials_path: Path, notion_transport: str = "rest") -> NotionTransport:
    if notion_transport == "rest":
        from notion_task_tracker.rest.transport import NotionRestTransport

        return NotionRestTransport(NotionRestClient.from_credentials_path(credentials_path))

    if notion_transport == "mcp":
        from notion_task_tracker.mcp.transport import NotionMcpTransport

        return NotionMcpTransport(NotionMcpClient.from_credentials_path(credentials_path))

    raise ValueError(f"Unsupported Notion transport {notion_transport!r}")


async def query_task_database_rows_with_client(client, tracker_state: dict[str, Any]) -> list[dict[str, Any]]:
    view_url = task_database_view_url_from_tracker_state(tracker_state)
    if view_url is not None:
        return await client.query_database_view(view_url)

    return await client.query_data_source(
        data_source_url=task_database_data_source_url_from_tracker_state(tracker_state),
        query=task_database_query_for_tracker_state(tracker_state),
    )
