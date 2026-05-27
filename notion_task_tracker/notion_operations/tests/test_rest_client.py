import asyncio
import json

from notion_task_tracker import NotionPageReference, NotionPageRegistry, NotionWriteIntent
from notion_task_tracker.notion_operations.rest_client import (
    NotionRestClient,
    _notion_rest_error_message,
    _task_database_row_from_rest_page,
)


def test_fetch_task_page_content_uses_page_properties_and_markdown():
    notion_client = _FakeNotionRestClient(
        responses=[
            {
                "id": "22222222-2222-2222-2222-222222222222",
                "url": "https://www.notion.so/22222222222222222222222222222222",
                "properties": _task_properties(ticket_number=1),
            },
            {"markdown": "## Timeline log"},
        ]
    )

    fetched_page_content = asyncio.run(
        notion_client.fetch_task_page_content("22222222222222222222222222222222")
    )

    assert '"Ticket ID": "1"' in fetched_page_content
    assert "## Timeline log" in fetched_page_content
    assert notion_client.requests == [
        ("GET", "/v1/pages/22222222222222222222222222222222", None),
        ("GET", "/v1/pages/22222222222222222222222222222222/markdown", None),
    ]


def test_fetch_page_goes_through_notion_sdk_page_endpoint():
    notion_client = NotionRestClient(
        access_token="ntn_test",
        base_url="https://api.notion.test",
        notion_version="2026-03-11",
    )
    notion_client.client = _FakeNotionSdkClient(
        page_result={"id": "22222222222222222222222222222222"}
    )

    page = asyncio.run(notion_client.fetch_page("22222222222222222222222222222222"))

    assert page == {"id": "22222222222222222222222222222222"}
    assert notion_client.client.pages.requests == [
        ("retrieve", "22222222222222222222222222222222")
    ]


def test_query_data_source_maps_rest_pages_to_database_rows():
    notion_client = _FakeNotionRestClient(
        responses=[
            {
                "results": [
                    {
                        "id": "22222222-2222-2222-2222-222222222222",
                        "url": "https://www.notion.so/22222222222222222222222222222222",
                        "properties": _task_properties(ticket_number=7),
                    }
                ],
                "has_more": False,
            }
        ]
    )

    rows = asyncio.run(notion_client.query_data_source("collection://data-source-a", "ignored"))

    assert rows == [
        {
            "Ticket page": "Root task",
            "Ticket ID": "7",
            "Priority": "P1",
            "Status": "Active",
            "Parent": "[]",
            "url": "https://www.notion.so/22222222222222222222222222222222",
        }
    ]
    assert notion_client.requests == [
        ("POST", "/v1/data_sources/data-source-a/query", {"page_size": 100})
    ]


def test_update_properties_call_uses_rest_page_property_shape():
    notion_client = _FakeNotionRestClient(
        responses=[{"id": "22222222-2222-2222-2222-222222222222"}]
    )

    asyncio.run(
        notion_client.execute_write_intent(
            NotionWriteIntent(
                operation_key="update_properties:task:ALOVYA-1",
                operation_name="update_page_properties",
                target_page_key="task:ALOVYA-1",
                arguments={
                    "properties": {
                        "Ticket page": "Root task",
                        "Priority": "P2",
                        "Status": "Blocked",
                    },
                },
            ),
            _page_registry(),
        )
    )

    assert notion_client.requests == [
        (
            "PATCH",
            "/v1/pages/22222222222222222222222222222222",
            {
                "properties": {
                    "Ticket page": {"title": [{"type": "text", "text": {"content": "Root task"}}]},
                    "Priority": {"select": {"name": "P2"}},
                    "Status": {"select": {"name": "Blocked"}},
                }
            },
        )
    ]


def test_replace_content_uses_page_markdown_endpoint():
    notion_client = _FakeNotionRestClient(
        responses=[{}]
    )

    asyncio.run(
        notion_client.execute_write_intent(
            NotionWriteIntent(
                operation_key="replace:ongoing_landing_page",
                operation_name="replace_page_markdown",
                target_page_key="ongoing_landing_page",
                arguments={
                    "markdown": "## P1\n- Active task",
                },
            ),
            _page_registry(),
        )
    )

    assert notion_client.requests == [
        (
        "PATCH",
        "/v1/pages/11111111111111111111111111111111/markdown",
        {
            "type": "replace_content",
            "replace_content": {"new_str": "## P1\n- Active task"},
        },
        )
    ]


def test_update_content_inserts_new_markdown_after_matching_heading():
    notion_client = _FakeNotionRestClient(
        responses=[
            {},
        ]
    )

    asyncio.run(
        notion_client.execute_write_intent(
            NotionWriteIntent(
                operation_key="update_timeline_log:task:ALOVYA-1:2026-05-26",
                operation_name="update_timeline_log",
                target_page_key="task:ALOVYA-1",
                arguments={
                    "timeline_log_heading": "Timeline log",
                    "timeline_section_markdown": '### <mention-date start="2026-05-26"/>\n- New log.',
                },
            ),
            _page_registry(),
        )
    )

    assert notion_client.requests == [
        (
        "PATCH",
        "/v1/pages/22222222222222222222222222222222/markdown",
        {
            "type": "update_content",
            "update_content": {
                "content_updates": [
                    {
                        "old_str": "## Timeline log",
                        "new_str": '## Timeline log\n### <mention-date start="2026-05-26"/>\n- New log.',
                    }
                ]
            },
        },
        ),
    ]


def test_create_pages_call_creates_database_page_with_children():
    notion_client = _FakeNotionRestClient(
        responses=[
            {
                "id": "33333333-3333-3333-3333-333333333333",
                "url": "https://www.notion.so/33333333333333333333333333333333",
            }
        ]
    )

    result = asyncio.run(
        notion_client.create_database_page(
            data_source_id="data-source-a",
            properties={
                "Ticket page": "Child task",
                "Priority": "P1",
                "Status": "Active",
                "Parent": json.dumps([
                    "https://www.notion.so/22222222222222222222222222222222"
                ]),
            },
            markdown="## Timeline log",
        )
    )

    assert result["url"] == "https://www.notion.so/33333333333333333333333333333333"
    assert notion_client.requests[0][0:2] == ("POST", "/v1/pages")
    assert notion_client.requests[0][2]["properties"]["Parent"] == {
        "relation": [{"id": "22222222222222222222222222222222"}]
    }
    assert notion_client.requests[0][2]["markdown"] == "## Timeline log"


def test_notion_rest_error_message_includes_request_context():
    error_message = _notion_rest_error_message(
        method="PATCH",
        path="/v1/pages/page-a/markdown",
        status_code=400,
        error_text='{"code":"validation_error","message":"old_str not found"}',
    )

    assert "PATCH" in error_message
    assert "/v1/pages/page-a/markdown" in error_message
    assert "validation_error" in error_message


def test_notion_rest_error_message_includes_permission_hint():
    error_message = _notion_rest_error_message(
        method="PATCH",
        path="/v1/blocks/block-a/children",
        status_code=403,
        error_text='{"code":"restricted_resource"}',
    )

    assert "insert-content" in error_message


def test_notion_rest_error_message_includes_not_found_hint():
    error_message = _notion_rest_error_message(
        method="GET",
        path="/v1/blocks/page-a/children",
        status_code=404,
        error_text='{"code":"object_not_found"}',
    )

    assert "shared with the Notion integration" in error_message


class _FakeNotionRestClient(NotionRestClient):
    def __init__(self, responses: list[dict]):
        super().__init__(
            access_token="ntn_test",
            base_url="https://api.notion.test",
            notion_version="2026-03-11",
        )
        self.responses = list(responses)
        self.requests = []

    async def _send_json(self, method: str, path: str, body: dict | None):
        self.requests.append((method, path, body))
        return self.responses.pop(0)


class _FakeNotionSdkClient:
    def __init__(self, page_result: dict):
        self.pages = _FakePagesEndpoint(page_result)


class _FakePagesEndpoint:
    def __init__(self, page_result: dict):
        self.page_result = page_result
        self.requests = []

    async def retrieve(self, page_id: str):
        self.requests.append(("retrieve", page_id))
        return self.page_result


def _page_registry() -> NotionPageRegistry:
    return NotionPageRegistry(
        pages={
            "ongoing_landing_page": NotionPageReference(
                local_page_key="ongoing_landing_page",
                title="Landing page",
                notion_page_id="11111111111111111111111111111111",
            ),
            "task:ALOVYA-1": NotionPageReference(
                local_page_key="task:ALOVYA-1",
                title="Root task",
                notion_page_id="22222222222222222222222222222222",
            ),
        }
    )


def _task_properties(ticket_number: int) -> dict:
    return {
        "Ticket page": {
            "type": "title",
            "title": [{"plain_text": "Root task"}],
        },
        "Ticket ID": {
            "type": "unique_id",
            "unique_id": {"number": ticket_number},
        },
        "Priority": {
            "type": "select",
            "select": {"name": "P1"},
        },
        "Status": {
            "type": "status",
            "status": {"name": "Active"},
        },
        "Parent": {
            "type": "relation",
            "relation": [],
        },
    }
