"""Notion MCP transport client."""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import timedelta
from pathlib import Path
from typing import Any

from notion_task_tracker.notion_mcp_calls import NotionMcpToolCall

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

    async def send_call(self, tool_call: NotionMcpToolCall) -> dict[str, Any]:
        tool_result = await self._call_notion_tool(tool_call.tool_name, tool_call.arguments)
        return {
            "tool_name": tool_call.tool_name,
            "result": _snapshot_notion_mcp_tool_result(tool_result),
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
        # TODO: Delete this with the MCP fallback once REST is reliable enough to be the only transport.
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


def _snapshot_notion_mcp_tool_result(tool_result: Any) -> dict[str, Any]:
    return {
        "is_error": bool(getattr(tool_result, "isError", False) or getattr(tool_result, "is_error", False)),
        "text": _text_from_notion_mcp_tool_result(tool_result),
    }
