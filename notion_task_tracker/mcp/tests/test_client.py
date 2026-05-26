import asyncio
from dataclasses import dataclass

import pytest

from notion_task_tracker.mcp.calls import NotionMcpToolCall
from notion_task_tracker.mcp.client import (
    NotionMcpClient,
    _available_tool_names_from_session,
    _fetched_page_text_from_notion_mcp_tool_result,
    _http_status_code_from_exception,
    _notion_query_results_from_tool_text,
    _text_from_notion_mcp_tool_result,
    _tool_names_from_list_tools_result,
)


def test_text_from_notion_mcp_tool_result_joins_text_items():
    tool_result = _ToolResult(
        content=[
            {"text": "First line"},
            _TextContent(text="Second line"),
        ]
    )

    assert _text_from_notion_mcp_tool_result(tool_result) == "First line\nSecond line"


def test_fetched_page_text_from_notion_mcp_tool_result_unwraps_fetch_result_json():
    tool_result = _ToolResult(
        content=[
            {
                "text": (
                    '{"metadata":{"type":"page"},"text":"<page>\\n'
                    '<properties>\\n{\\"title\\":\\"ALOVYA-1: Root\\"}\\n'
                    '</properties>\\n</page>"}'
                )
            }
        ]
    )

    assert _fetched_page_text_from_notion_mcp_tool_result(tool_result) == "\n".join(
        [
            "<page>",
            "<properties>",
            '{"title":"ALOVYA-1: Root"}',
            "</properties>",
            "</page>",
        ]
    )


def test_notion_query_results_from_tool_text_reads_result_rows():
    query_results = _notion_query_results_from_tool_text(
        '{"results":[{"Ticket page":"Task","Ticket ID":"1"}],"has_more":false}'
    )

    assert query_results == [{"Ticket page": "Task", "Ticket ID": "1"}]


def test_tool_names_from_list_tools_result_reads_advertised_tools():
    list_tools_result = _ListToolsResult(
        tools=[
            _Tool(name="notion-fetch"),
            _Tool(name="notion-update-page"),
        ],
    )

    assert _tool_names_from_list_tools_result(list_tools_result) == {
        "notion-fetch",
        "notion-update-page",
    }


def test_available_tool_names_from_session_reads_paginated_tools():
    session = _ListToolsSession(
        results_by_cursor={
            None: _ListToolsResult(
                tools=[_Tool(name="notion-fetch")],
                nextCursor="next-page",
            ),
            "next-page": _ListToolsResult(
                tools=[_Tool(name="notion-update-page")],
                nextCursor=None,
            ),
        }
    )

    tool_names = asyncio.run(_available_tool_names_from_session(session, request_timeout_seconds=1))

    assert tool_names == {"notion-fetch", "notion-update-page"}
    assert session.requested_cursors == [None, "next-page"]


def test_http_status_code_from_exception_reads_nested_exception_group():
    error = ExceptionGroup(
        "stream failure",
        [
            RuntimeError("outer failure"),
            _HttpStatusError(_HttpResponse(status_code=401)),
        ],
    )

    assert _http_status_code_from_exception(error) == 401


def test_notion_mcp_client_rejects_unadvertised_tool_before_calling_it():
    session = _CallToolSession(available_tool_names={"notion-fetch"})
    client = _FakeSessionNotionMcpClient(session)

    with pytest.raises(ValueError, match="not advertised"):
        asyncio.run(
            client.send_call(
                NotionMcpToolCall(
                    operation_key="replace:landing_page",
                    tool_name="notion-update-page",
                    arguments={},
                )
            )
        )

    assert session.call_tool_requests == []


def test_notion_mcp_client_caches_available_tool_names():
    session = _CallToolSession(available_tool_names={"notion-fetch"})
    client = _FakeSessionNotionMcpClient(session)

    asyncio.run(client.fetch_task_page_content("page-a"))
    asyncio.run(client.fetch_task_page_content("page-b"))

    assert session.list_tools_call_count == 1
    assert [request["name"] for request in session.call_tool_requests] == [
        "notion-fetch",
        "notion-fetch",
    ]


def test_notion_mcp_client_queries_data_source_rows():
    session = _CallToolSession(
        available_tool_names={"notion-query-data-sources"},
        result_by_tool_name={
            "notion-query-data-sources": _ToolResult(
                content=[
                    {
                        "text": (
                            '{"results":[{"Ticket page":"Task","Ticket ID":"1"}],'
                            '"has_more":false}'
                        )
                    }
                ]
            )
        },
    )
    client = _FakeSessionNotionMcpClient(session)

    query_results = asyncio.run(
        client.query_data_source(
            data_source_url="collection://database",
            query='SELECT * FROM "collection://database"',
        )
    )

    assert query_results == [{"Ticket page": "Task", "Ticket ID": "1"}]
    assert session.call_tool_requests == [
        {
            "name": "notion-query-data-sources",
            "arguments": {
                "data": {
                    "mode": "sql",
                    "data_source_urls": ["collection://database"],
                    "query": 'SELECT * FROM "collection://database"',
                }
            },
        }
    ]


def test_notion_mcp_client_queries_database_view_rows():
    session = _CallToolSession(
        available_tool_names={"notion-query-data-sources"},
        result_by_tool_name={
            "notion-query-data-sources": _ToolResult(
                content=[
                    {
                        "text": (
                            '{"results":[{"Ticket page":"Task","Ticket ID":"1"}],'
                            '"has_more":false}'
                        )
                    }
                ]
            )
        },
    )
    client = _FakeSessionNotionMcpClient(session)

    query_results = asyncio.run(
        client.query_database_view(
            view_url="https://www.notion.so/wayve/database?v=view",
        )
    )

    assert query_results == [{"Ticket page": "Task", "Ticket ID": "1"}]
    assert session.call_tool_requests == [
        {
            "name": "notion-query-data-sources",
            "arguments": {
                "data": {
                    "mode": "view",
                    "view_url": "https://www.notion.so/wayve/database?v=view",
                    "page_size": 100,
                }
            },
        }
    ]


@dataclass(frozen=True)
class _ToolResult:
    content: list


@dataclass(frozen=True)
class _TextContent:
    text: str


@dataclass(frozen=True)
class _ListToolsResult:
    tools: list
    nextCursor: str | None = None


@dataclass(frozen=True)
class _Tool:
    name: str


@dataclass(frozen=True)
class _HttpResponse:
    status_code: int


class _HttpStatusError(Exception):
    def __init__(self, response: _HttpResponse):
        super().__init__("HTTP status error")
        self.response = response


class _ListToolsSession:
    def __init__(self, results_by_cursor: dict):
        self.results_by_cursor = results_by_cursor
        self.requested_cursors = []

    async def list_tools(self, cursor=None):
        self.requested_cursors.append(cursor)
        return self.results_by_cursor[cursor]


class _FakeSessionNotionMcpClient(NotionMcpClient):
    def __init__(self, session):
        super().__init__(access_token="token", server_url="https://example.invalid/mcp")
        self.session = session

    async def _call_notion_tool(self, tool_name, tool_arguments):
        await self._raise_if_tool_is_not_available(self.session, tool_name)
        return await self.session.call_tool(tool_name, tool_arguments)


class _CallToolSession:
    def __init__(self, available_tool_names: set[str], result_by_tool_name: dict | None = None):
        self.available_tool_names = available_tool_names
        self.result_by_tool_name = result_by_tool_name or {}
        self.call_tool_requests = []
        self.list_tools_call_count = 0

    async def list_tools(self, cursor=None):
        self.list_tools_call_count += 1
        return _ListToolsResult(
            tools=[
                _Tool(name=tool_name)
                for tool_name in sorted(self.available_tool_names)
            ],
        )

    async def call_tool(self, name, arguments):
        self.call_tool_requests.append(
            {
                "name": name,
                "arguments": arguments,
            }
        )
        return self.result_by_tool_name.get(name, _ToolResult(content=[]))
