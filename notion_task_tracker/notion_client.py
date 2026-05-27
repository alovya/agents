"""Workflow-level Notion client interface."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

from notion_task_tracker.apply_tracker_command import TrackerCommandResult


@dataclass(frozen=True)
class CreatedTaskDatabasePage:
    notion_page_id: str
    operation_keys: list[str]


@dataclass(frozen=True)
class NotionWriteExecutionResult:
    completed_operation_keys: list[str] = field(default_factory=list)
    captured_page_ids: dict[str, str] = field(default_factory=dict)
    blocked_operation_count: int = 0


class NotionClient(Protocol):
    async def fetch_task_page_content(self, page_id: str) -> str:
        raise NotImplementedError

    async def query_task_database_rows(self, tracker_state: dict[str, Any]) -> list[dict[str, Any]]:
        raise NotImplementedError

    async def create_task_database_page(
        self,
        data_source_id: str,
        properties: dict[str, Any],
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

    async def execute_command_result(self, command_result: TrackerCommandResult) -> NotionWriteExecutionResult:
        raise NotImplementedError


def notion_client_from_credentials_path(credentials_path: Path, notion_client: str = "rest") -> NotionClient:
    if notion_client == "rest":
        from notion_task_tracker.notion_rest_client import NotionRestClient

        return NotionRestClient.from_credentials_path(credentials_path)

    if notion_client == "mcp":
        from notion_task_tracker.notion_mcp_client import NotionMcpClient

        return NotionMcpClient.from_credentials_path(credentials_path)

    raise ValueError(f"Unsupported Notion client {notion_client!r}")


__all__ = [
    "CreatedTaskDatabasePage",
    "NotionClient",
    "NotionWriteExecutionResult",
    "notion_client_from_credentials_path",
]
