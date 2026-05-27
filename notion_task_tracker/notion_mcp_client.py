"""Notion MCP client."""

from __future__ import annotations

import asyncio
import json
import re
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import timedelta
from pathlib import Path
from typing import Any

from notion_task_tracker.apply_tracker_command import TrackerCommandResult
from notion_task_tracker.json_file import write_json_file
from notion_task_tracker.notion_writes import NotionPlanningError, NotionWriteIntent
from notion_task_tracker.page_registry import (
    NotionPageRegistry,
)
from notion_task_tracker.notion_client import CreatedTaskDatabasePage, NotionWriteExecutionResult
from notion_task_tracker.tasks.database import (
    task_database_data_source_url_from_tracker_state,
    task_database_query_for_tracker_state,
    task_database_view_url_from_tracker_state,
)

DEFAULT_NOTION_MCP_REQUEST_TIMEOUT_SECONDS = 30


class NotionMcpClient:
    def __init__(
        self,
        access_token: str,
        server_url: str,
        request_timeout_seconds: int = DEFAULT_NOTION_MCP_REQUEST_TIMEOUT_SECONDS,
    ) -> None:
        self.access_token = access_token
        self.server_url = server_url
        self.request_timeout_seconds = request_timeout_seconds
        self._available_tool_names: set[str] | None = None

    @classmethod
    def from_credentials_path(cls, credentials_path: Path) -> "NotionMcpClient":
        credentials = _notion_mcp_credentials_from_path(credentials_path)
        return cls(
            access_token=credentials["access_token"],
            server_url=credentials["server_url"],
        )

    async def fetch_task_page_content(self, page_id: str) -> str:
        return _fetched_page_text_from_notion_mcp_tool_result(
            await self._call_notion_tool("notion-fetch", {"id": page_id})
        )

    async def query_data_source(self, data_source_url: str, query: str) -> list[dict[str, Any]]:
        tool_text = await self._call_notion_tool_for_text(
            "notion-query-data-sources",
            {
                "data": {
                    "mode": "sql",
                    "data_source_urls": [data_source_url],
                    "query": query,
                }
            },
        )
        return _notion_query_results_from_tool_text(tool_text)

    async def query_database_view(self, view_url: str) -> list[dict[str, Any]]:
        tool_text = await self._call_notion_tool_for_text(
            "notion-query-data-sources",
            {
                "data": {
                    "mode": "view",
                    "view_url": view_url,
                    "page_size": 100,
                }
            },
        )
        return _notion_query_results_from_tool_text(tool_text)

    async def query_task_database_rows(self, tracker_state: dict[str, Any]) -> list[dict[str, Any]]:
        view_url = task_database_view_url_from_tracker_state(tracker_state)
        if view_url is not None:
            return await self.query_database_view(view_url)

        return await self.query_data_source(
            data_source_url=task_database_data_source_url_from_tracker_state(tracker_state),
            query=task_database_query_for_tracker_state(tracker_state),
        )

    async def create_task_database_page(
        self,
        data_source_id: str,
        properties: dict[str, Any],
        content: str,
        operation_key: str,
    ) -> CreatedTaskDatabasePage:
        create_result = await self.send_call(
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
        await self.send_call(
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

    async def execute_command_result(self, command_result: TrackerCommandResult) -> NotionWriteExecutionResult:
        if command_result.page_registry is None:
            raise ValueError("MCP write execution requires a page registry")

        call_plan = NotionMcpCallPlanner(command_result.page_registry).compile_write_intents(command_result.write_intents)
        completed_operation_keys, captured_page_ids = await _execute_available_calls(self, call_plan)
        if call_plan.blocked_operations and not captured_page_ids:
            _raise_if_call_plan_has_blocked_operations(call_plan)
        return NotionWriteExecutionResult(
            completed_operation_keys=completed_operation_keys,
            captured_page_ids=captured_page_ids,
            blocked_operation_count=len(call_plan.blocked_operations),
        )

    async def send_call(self, tool_call: NotionMcpToolCall) -> dict[str, Any]:
        tool_result = await self._call_notion_tool(tool_call.tool_name, tool_call.arguments)
        return {
            "tool_name": tool_call.tool_name,
            "result": _jsonable_notion_mcp_tool_result(tool_result),
        }

    async def _call_notion_tool_for_text(self, tool_name: str, tool_arguments: dict[str, Any]) -> str:
        return _text_from_notion_mcp_tool_result(await self._call_notion_tool(tool_name, tool_arguments))

    async def _call_notion_tool(self, tool_name: str, tool_arguments: dict[str, Any]) -> Any:
        async with self._client_session() as session:
            await self._raise_if_tool_is_not_available(session, tool_name)
            tool_result = await asyncio.wait_for(
                session.call_tool(
                    tool_name,
                    tool_arguments,
                    read_timeout_seconds=timedelta(seconds=self.request_timeout_seconds),
                ),
                timeout=self.request_timeout_seconds,
            )
            _raise_if_notion_mcp_tool_call_failed(tool_name, tool_arguments, tool_result)
            return tool_result

    async def _raise_if_tool_is_not_available(self, session: Any, tool_name: str) -> None:
        # TODO: Delete this with the MCP fallback once REST is reliable enough to be the only Notion client.
        if self._available_tool_names is None:
            self._available_tool_names = await _available_tool_names_from_session(
                session=session,
                request_timeout_seconds=self.request_timeout_seconds,
            )

        if tool_name in self._available_tool_names:
            return

        raise ValueError(
            json.dumps(
                {
                    "tool_name": tool_name,
                    "available_tool_names": sorted(self._available_tool_names),
                    "error": "Notion MCP tool is not advertised by the live server.",
                },
                indent=2,
                sort_keys=True,
            )
        )

    @asynccontextmanager
    async def _client_session(self) -> AsyncIterator[Any]:
        from mcp import ClientSession
        from mcp.client.streamable_http import streamablehttp_client

        headers = {"Authorization": f"Bearer {self.access_token}"}
        try:
            async with streamablehttp_client(self.server_url, headers=headers) as (
                read_stream,
                write_stream,
                _get_session_id,
            ):
                async with ClientSession(
                    read_stream,
                    write_stream,
                    read_timeout_seconds=timedelta(seconds=self.request_timeout_seconds),
                ) as session:
                    try:
                        await asyncio.wait_for(session.initialize(), timeout=self.request_timeout_seconds)
                    except TimeoutError as error:
                        raise TimeoutError(
                            f"Timed out initialising Notion MCP session for {self.server_url!r}. "
                            "This usually means sandboxed DNS/network access failed before the Notion tool call ran."
                        ) from error
                    yield session
        except BaseExceptionGroup as error:
            _raise_clear_notion_mcp_connection_error(error)
        except Exception as error:
            _raise_clear_notion_mcp_connection_error(error)


def _notion_mcp_credentials_from_path(credentials_path: Path) -> dict[str, Any]:
    credentials = json.loads(credentials_path.read_text(encoding="utf-8"))
    return next(
        value
        for key, value in credentials.items()
        if key.startswith("Notion|")
    )


def _raise_if_call_plan_has_blocked_operations(call_plan: NotionMcpCallPlan) -> None:
    if not call_plan.blocked_operations:
        return

    raise ValueError(
        json.dumps(
            {
                "blocked_operations": [
                    blocked_operation.to_json()
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


def _raise_if_notion_mcp_tool_call_failed(tool_name: str, tool_arguments: dict[str, Any], tool_result: Any) -> None:
    if not getattr(tool_result, "isError", False) and not getattr(tool_result, "is_error", False):
        return

    raise ValueError(
        json.dumps(
            {
                "tool_name": tool_name,
                "tool_arguments": tool_arguments,
                "error": _text_from_notion_mcp_tool_result(tool_result),
            },
            indent=2,
            sort_keys=True,
        )
    )


def _raise_clear_notion_mcp_connection_error(error: BaseException) -> None:
    status_code = _http_status_code_from_exception(error)
    if status_code == 401:
        raise PermissionError(
            "Notion MCP returned HTTP 401. Run codex mcp login Notion, then retry the tracker command."
        ) from error

    raise error


def _http_status_code_from_exception(error: BaseException) -> int | None:
    response = getattr(error, "response", None)
    status_code = getattr(response, "status_code", None)
    if isinstance(status_code, int):
        return status_code

    if isinstance(error, BaseExceptionGroup):
        for nested_error in error.exceptions:
            nested_status_code = _http_status_code_from_exception(nested_error)
            if nested_status_code is not None:
                return nested_status_code

    return None


async def _available_tool_names_from_session(session: Any, request_timeout_seconds: int) -> set[str]:
    tool_names = set()
    next_cursor = None

    while True:
        list_tools_result = await asyncio.wait_for(
            session.list_tools(cursor=next_cursor),
            timeout=request_timeout_seconds,
        )
        tool_names.update(_tool_names_from_list_tools_result(list_tools_result))
        next_cursor = getattr(list_tools_result, "nextCursor", None)
        if next_cursor is None:
            return tool_names


def _tool_names_from_list_tools_result(list_tools_result: Any) -> set[str]:
    return {
        str(tool.name)
        for tool in getattr(list_tools_result, "tools", [])
    }


def _text_from_notion_mcp_tool_result(tool_result: Any) -> str:
    content_items = getattr(tool_result, "content", [])
    return "\n".join(
        text
        for text in (_text_from_notion_mcp_content_item(content_item) for content_item in content_items)
        if text
    )


def _fetched_page_text_from_notion_mcp_tool_result(tool_result: Any) -> str:
    tool_text = _text_from_notion_mcp_tool_result(tool_result)
    try:
        fetched_result = json.loads(tool_text)
    except json.JSONDecodeError:
        return tool_text

    if isinstance(fetched_result, dict) and isinstance(fetched_result.get("text"), str):
        return fetched_result["text"]

    return tool_text


def _notion_query_results_from_tool_text(tool_text: str) -> list[dict[str, Any]]:
    query_result = json.loads(tool_text)
    results = query_result.get("results")
    if not isinstance(results, list):
        raise ValueError(f"Notion query result did not contain a results list: {tool_text}")

    return [
        dict(result)
        for result in results
    ]


def _text_from_notion_mcp_content_item(content_item: Any) -> str:
    if isinstance(content_item, dict):
        return str(content_item.get("text", ""))

    return str(getattr(content_item, "text", ""))


def _jsonable_notion_mcp_tool_result(tool_result: Any) -> dict[str, Any]:
    return {
        "is_error": bool(getattr(tool_result, "isError", False) or getattr(tool_result, "is_error", False)),
        "text": _text_from_notion_mcp_tool_result(tool_result),
    }


@dataclass(frozen=True)
class NotionMcpToolCall:
    """One exact Notion MCP tool call plus local bookkeeping metadata."""

    operation_key: str
    tool_name: str
    arguments: dict[str, Any]
    captures_page_key: str | None = None

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> "NotionMcpToolCall":
        return cls(
            operation_key=data["operation_key"],
            tool_name=data["tool_name"],
            arguments=dict(data["arguments"]),
            captures_page_key=data.get("captures_page_key"),
        )

    def to_json(self) -> dict[str, Any]:
        return {
            "operation_key": self.operation_key,
            "tool_name": self.tool_name,
            "arguments": self.arguments,
            "captures_page_key": self.captures_page_key,
        }


@dataclass(frozen=True)
class BlockedNotionMcpOperation:
    """Intent that needs page ids or richer intent arguments before planning."""

    operation_key: str
    reason: str

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> "BlockedNotionMcpOperation":
        return cls(
            operation_key=data["operation_key"],
            reason=data["reason"],
        )

    def to_json(self) -> dict[str, Any]:
        return {
            "operation_key": self.operation_key,
            "reason": self.reason,
        }


@dataclass
class NotionMcpCallPlan:
    """Ordered MCP tool calls and any deterministic blockers."""

    calls: list[NotionMcpToolCall] = field(default_factory=list)
    blocked_operations: list[BlockedNotionMcpOperation] = field(default_factory=list)

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> "NotionMcpCallPlan":
        return cls(
            calls=[
                NotionMcpToolCall.from_json(call_state)
                for call_state in data.get("calls", [])
            ],
            blocked_operations=[
                BlockedNotionMcpOperation.from_json(blocked_state)
                for blocked_state in data.get("blocked_operations", [])
            ],
        )

    def write_json(self, output_path: str | Path) -> None:
        write_json_file(self.to_json(), output_path)

    def to_json(self) -> dict[str, Any]:
        return {
            "calls": [
                call.to_json()
                for call in self.calls
            ],
            "blocked_operations": [
                blocked_operation.to_json()
                for blocked_operation in self.blocked_operations
            ],
        }


class NotionMcpCallPlanner:
    """Turns abstract write intents into exact Notion MCP tool calls."""

    def __init__(self, page_registry: NotionPageRegistry):
        self.page_registry = page_registry

    def compile_write_intents(self, write_intents: list[NotionWriteIntent]) -> NotionMcpCallPlan:
        call_plan = NotionMcpCallPlan()

        for write_intent in write_intents:
            intent_call_plan = self.compile_write_intent(write_intent)
            call_plan.calls.extend(intent_call_plan.calls)
            call_plan.blocked_operations.extend(intent_call_plan.blocked_operations)

        return call_plan

    def compile_write_intent(self, write_intent: NotionWriteIntent) -> NotionMcpCallPlan:
        try:
            return self._compile_supported_write_intent(write_intent)
        except KeyError as error:
            return self._blocked_plan(
                write_intent.operation_key,
                f"Intent is missing required argument {error.args[0]!r}",
            )
        except NotionPlanningError as error:
            return self._blocked_plan(write_intent.operation_key, str(error))

    def _compile_supported_write_intent(self, write_intent: NotionWriteIntent) -> NotionMcpCallPlan:
        if write_intent.operation_name == "create_page":
            return self._compile_create_page_intent(write_intent)

        if write_intent.operation_name == "replace_page_markdown":
            return self._compile_replace_page_markdown_intent(write_intent)

        if write_intent.operation_name == "update_page_properties":
            return self._compile_update_page_properties_intent(write_intent)

        if write_intent.operation_name == "update_timeline_log":
            return self._compile_timeline_log_update_intent(write_intent)

        if write_intent.operation_name == "append_miscellaneous_context":
            return self._compile_miscellaneous_context_append_intent(write_intent)

        if write_intent.operation_name == "create_synthesis_page":
            return self._compile_synthesis_page_creation_intent(write_intent)

        return self._blocked_plan(
            write_intent.operation_key,
            f"Unsupported write-intent operation {write_intent.operation_name!r}",
        )

    def _compile_create_page_intent(self, write_intent: NotionWriteIntent) -> NotionMcpCallPlan:
        arguments = write_intent.arguments
        return self._plan_create_page(
            operation_key=write_intent.operation_key,
            local_page_key=arguments["local_page_key"],
            title=arguments["title"],
            parent_page_key=arguments.get("parent_page_key"),
            content=arguments.get("markdown", ""),
        )

    def _compile_replace_page_markdown_intent(self, write_intent: NotionWriteIntent) -> NotionMcpCallPlan:
        target_page_key = self._required_target_page_key(write_intent)
        return self._plan_replace_page_content(
            operation_key=write_intent.operation_key,
            target_page_key=target_page_key,
            content=write_intent.arguments["markdown"],
        )

    def _compile_update_page_properties_intent(self, write_intent: NotionWriteIntent) -> NotionMcpCallPlan:
        try:
            page_id = self.page_registry.page_id(self._required_target_page_key(write_intent))
        except NotionPlanningError as error:
            return self._blocked_plan(write_intent.operation_key, str(error))

        return NotionMcpCallPlan(
            calls=[
                NotionMcpToolCall(
                    operation_key=write_intent.operation_key,
                    tool_name="notion-update-page",
                    arguments={
                        "page_id": page_id,
                        "command": "update_properties",
                        "properties": _notion_mcp_page_properties(write_intent.arguments["properties"]),
                    },
                )
            ]
        )

    def _compile_timeline_log_update_intent(self, write_intent: NotionWriteIntent) -> NotionMcpCallPlan:
        if "old_timeline_section_markdown" in write_intent.arguments:
            return self._plan_replace_timeline_section(
                operation_key=write_intent.operation_key,
                target_page_key=self._required_target_page_key(write_intent),
                old_markdown=write_intent.arguments["old_timeline_section_markdown"],
                new_markdown=write_intent.arguments["new_timeline_section_markdown"],
            )

        return self._plan_prepend_timeline_entry(
            operation_key=write_intent.operation_key,
            target_page_key=self._required_target_page_key(write_intent),
            timeline_log_heading=write_intent.arguments["timeline_log_heading"],
            timeline_section_markdown=write_intent.arguments["timeline_section_markdown"],
        )

    def _compile_miscellaneous_context_append_intent(self, write_intent: NotionWriteIntent) -> NotionMcpCallPlan:
        dated_page = write_intent.arguments["dated_page"]
        dated_page_key = dated_page["local_page_key"]

        if not self._page_has_id(dated_page_key):
            return self._plan_miscellaneous_page_creation_before_refresh(write_intent, dated_page)

        return self._plan_target_and_root_replacement(
            operation_key=write_intent.operation_key,
            target_page_key=dated_page_key,
            target_markdown=write_intent.arguments["dated_page_markdown"],
            root_page_key=write_intent.arguments["root_page_key"],
            root_markdown=write_intent.arguments.get("root_page_markdown"),
        )

    def _compile_synthesis_page_creation_intent(self, write_intent: NotionWriteIntent) -> NotionMcpCallPlan:
        synthesis_page = write_intent.arguments["page"]
        synthesis_page_key = synthesis_page["local_page_key"]

        if not self._page_has_id(synthesis_page_key):
            return self._plan_synthesis_page_creation_before_root_refresh(write_intent, synthesis_page)

        return self._plan_target_and_root_replacement(
            operation_key=write_intent.operation_key,
            target_page_key=synthesis_page_key,
            target_markdown=write_intent.arguments["markdown"],
            root_page_key=write_intent.arguments["root_page_key"],
            root_markdown=write_intent.arguments.get("root_page_markdown"),
        )

    def _plan_miscellaneous_page_creation_before_refresh(
        self,
        write_intent: NotionWriteIntent,
        dated_page: dict[str, Any],
    ) -> NotionMcpCallPlan:
        create_plan = self._plan_create_page(
            operation_key=f"create:{dated_page['local_page_key']}",
            local_page_key=dated_page["local_page_key"],
            title=dated_page["title"],
            parent_page_key=dated_page.get("parent_page_key"),
            content=write_intent.arguments["dated_page_markdown"],
        )
        create_plan.blocked_operations.append(
            BlockedNotionMcpOperation(
                operation_key=write_intent.operation_key,
                reason=(
                    f"Capture page id for {dated_page['local_page_key']!r}, "
                    "then rerun this intent to refresh the dated page and root page"
                ),
            )
        )
        return create_plan

    def _plan_synthesis_page_creation_before_root_refresh(
        self,
        write_intent: NotionWriteIntent,
        synthesis_page: dict[str, Any],
    ) -> NotionMcpCallPlan:
        create_plan = self._plan_create_page(
            operation_key=f"create:{synthesis_page['local_page_key']}",
            local_page_key=synthesis_page["local_page_key"],
            title=synthesis_page["title"],
            parent_page_key=synthesis_page.get("parent_page_key"),
            content=write_intent.arguments["markdown"],
        )
        create_plan.blocked_operations.append(
            BlockedNotionMcpOperation(
                operation_key=write_intent.operation_key,
                reason=(
                    f"Capture page id for {synthesis_page['local_page_key']!r}, "
                    "then rerun this intent to refresh the synthesis root page"
                ),
            )
        )
        return create_plan

    def _plan_target_and_root_replacement(
        self,
        operation_key: str,
        target_page_key: str,
        target_markdown: str,
        root_page_key: str,
        root_markdown: str | None,
    ) -> NotionMcpCallPlan:
        call_plan = self._plan_replace_page_content(
            operation_key=f"replace:{target_page_key}:{operation_key}",
            target_page_key=target_page_key,
            content=target_markdown,
        )

        if root_markdown is not None:
            root_plan = self._plan_replace_page_content(
                operation_key=f"replace:{root_page_key}:{operation_key}",
                target_page_key=root_page_key,
                content=root_markdown,
            )
            call_plan.calls.extend(root_plan.calls)
            call_plan.blocked_operations.extend(root_plan.blocked_operations)

        return call_plan

    def _plan_create_page(
        self,
        operation_key: str,
        local_page_key: str,
        title: str,
        parent_page_key: str | None,
        content: str,
    ) -> NotionMcpCallPlan:
        try:
            arguments = self._create_page_arguments(title, parent_page_key, content)
        except NotionPlanningError as error:
            return self._blocked_plan(operation_key, str(error))

        return NotionMcpCallPlan(
            calls=[
                NotionMcpToolCall(
                    operation_key=operation_key,
                    tool_name="notion-create-pages",
                    arguments=arguments,
                    captures_page_key=local_page_key,
                )
            ]
        )

    def _create_page_arguments(
        self,
        title: str,
        parent_page_key: str | None,
        content: str,
    ) -> dict[str, Any]:
        page = {
            "properties": {
                "title": title,
            },
            "content": content,
        }
        arguments = {"pages": [page]}

        if parent_page_key is not None:
            arguments["parent"] = {
                "page_id": self.page_registry.page_id(parent_page_key),
                "type": "page_id",
            }

        return arguments

    def _plan_replace_page_content(
        self,
        operation_key: str,
        target_page_key: str,
        content: str,
    ) -> NotionMcpCallPlan:
        try:
            page_id = self.page_registry.page_id(target_page_key)
        except NotionPlanningError as error:
            return self._blocked_plan(operation_key, str(error))

        return NotionMcpCallPlan(
            calls=[
                NotionMcpToolCall(
                    operation_key=operation_key,
                    tool_name="notion-update-page",
                    arguments={
                        "page_id": page_id,
                        "command": "replace_content",
                        "new_str": content,
                    },
                )
            ]
        )

    def _plan_prepend_timeline_entry(
        self,
        operation_key: str,
        target_page_key: str,
        timeline_log_heading: str,
        timeline_section_markdown: str,
    ) -> NotionMcpCallPlan:
        try:
            page_id = self.page_registry.page_id(target_page_key)
            heading_content = f"## {timeline_log_heading}"
        except NotionPlanningError as error:
            return self._blocked_plan(operation_key, str(error))

        return NotionMcpCallPlan(
            calls=[
                NotionMcpToolCall(
                    operation_key=operation_key,
                    tool_name="notion-update-page",
                    arguments={
                        "page_id": page_id,
                        "command": "update_content",
                        "content_updates": [
                            {
                                "old_str": heading_content,
                                "new_str": f"{heading_content}\n{timeline_section_markdown}",
                            }
                        ],
                    },
                )
            ]
        )

    def _plan_replace_timeline_section(
        self,
        operation_key: str,
        target_page_key: str,
        old_markdown: str,
        new_markdown: str,
    ) -> NotionMcpCallPlan:
        try:
            page_id = self.page_registry.page_id(target_page_key)
        except NotionPlanningError as error:
            return self._blocked_plan(operation_key, str(error))

        return NotionMcpCallPlan(
            calls=[
                NotionMcpToolCall(
                    operation_key=operation_key,
                    tool_name="notion-update-page",
                    arguments={
                        "page_id": page_id,
                        "command": "update_content",
                        "content_updates": [
                            {
                                "old_str": old_markdown,
                                "new_str": new_markdown,
                            }
                        ],
                    },
                )
            ]
        )

    def _page_has_id(self, local_page_key: str) -> bool:
        try:
            self.page_registry.page_id(local_page_key)
        except NotionPlanningError:
            return False

        return True

    def _required_target_page_key(self, write_intent: NotionWriteIntent) -> str:
        if write_intent.target_page_key is None:
            raise NotionPlanningError(f"Intent {write_intent.operation_key!r} has no target page key")

        return write_intent.target_page_key

    def _blocked_plan(self, operation_key: str, reason: str) -> NotionMcpCallPlan:
        return NotionMcpCallPlan(
            blocked_operations=[
                BlockedNotionMcpOperation(
                    operation_key=operation_key,
                    reason=reason,
                )
            ]
        )


def _notion_mcp_page_properties(properties: dict[str, Any]) -> dict[str, Any]:
    if "title" in properties:
        return {
            **properties,
            "title": properties["title"],
        }

    return dict(properties)
