import asyncio
import json

from notion_task_tracker.common import NotionPageReference, NotionPageRegistry, NotionWriteIntent
from notion_task_tracker.rest.client import (
    NotionRestClient,
    _markdown_from_rest_blocks,
    _notion_rest_error_message,
    _rich_text_items,
    _task_database_row_from_rest_page,
)


def test_fetch_task_page_content_uses_page_properties_and_block_children():
    notion_client = _FakeNotionRestClient(
        responses=[
            {
                "id": "22222222-2222-2222-2222-222222222222",
                "url": "https://www.notion.so/22222222222222222222222222222222",
                "properties": _task_properties(ticket_number=1),
            },
            {
                "results": [
                    {
                        "id": "block-a",
                        "type": "heading_2",
                        "heading_2": {"rich_text": [{"plain_text": "Timeline log"}]},
                    }
                ],
                "has_more": False,
            },
        ]
    )

    fetched_page_content = asyncio.run(
        notion_client.fetch_task_page_content("22222222222222222222222222222222")
    )

    assert '"Ticket ID": "1"' in fetched_page_content
    assert "## Timeline log" in fetched_page_content
    assert notion_client.requests == [
        ("GET", "/v1/pages/22222222222222222222222222222222", None),
        ("GET", "/v1/blocks/22222222222222222222222222222222/children?page_size=100", None),
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


def test_replace_content_archives_existing_blocks_then_appends_rest_blocks():
    notion_client = _FakeNotionRestClient(
        responses=[
            {
                "results": [{"id": "old-block", "type": "paragraph", "paragraph": {"rich_text": []}}],
                "has_more": False,
            },
            {},
            {},
        ]
    )

    asyncio.run(
        notion_client.execute_write_intent(
            NotionWriteIntent(
                operation_key="replace:landing_page",
                operation_name="replace_page_children",
                target_page_key="landing_page",
                arguments={
                    "blocks": [
                        {"type": "heading_2", "text": "P1"},
                        {"type": "bulleted_list_item", "depth": 0, "text": "Active task"},
                    ],
                },
            ),
            _page_registry(),
        )
    )

    assert notion_client.requests[0] == (
        "GET",
        "/v1/blocks/11111111111111111111111111111111/children?page_size=100",
        None,
    )
    assert notion_client.requests[1] == (
        "PATCH",
        "/v1/blocks/old-block",
        {"in_trash": True},
    )
    assert notion_client.requests[2][0:2] == (
        "PATCH",
        "/v1/blocks/11111111111111111111111111111111/children",
    )
    assert [block["type"] for block in notion_client.requests[2][2]["children"]] == [
        "heading_2",
        "bulleted_list_item",
    ]


def test_update_content_inserts_new_blocks_after_matching_heading():
    notion_client = _FakeNotionRestClient(
        responses=[
            {
                "results": [
                    {
                        "id": "timeline-heading",
                        "type": "heading_2",
                        "heading_2": {"rich_text": [{"plain_text": "Timeline log"}]},
                    }
                ],
                "has_more": False,
            },
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
                    "blocks": [
                        {"type": "heading_3", "text": '<mention-date start="2026-05-26"/>'},
                        {"type": "bulleted_list_item", "depth": 0, "text": "New log."},
                    ],
                },
            ),
            _page_registry(),
        )
    )

    assert notion_client.requests[1] == (
        "PATCH",
        "/v1/blocks/22222222222222222222222222222222/children",
        {
            "children": [
                {
                    "object": "block",
                    "type": "heading_3",
                    "heading_3": {
                        "rich_text": [
                            {
                                "type": "mention",
                                "mention": {
                                    "type": "date",
                                    "date": {"start": "2026-05-26"},
                                },
                            }
                        ],
                        "is_toggleable": False,
                    },
                },
                {
                    "object": "block",
                    "type": "bulleted_list_item",
                    "bulleted_list_item": {
                        "rich_text": [{"type": "text", "text": {"content": "New log."}}],
                        "color": "default",
                    },
                },
            ],
            "position": {"type": "after_block", "after_block": {"id": "timeline-heading"}},
        },
    )


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
            blocks=[
                {
                    "type": "heading_2",
                    "text": "Timeline log",
                },
            ],
        )
    )

    assert result["url"] == "https://www.notion.so/33333333333333333333333333333333"
    assert notion_client.requests[0][0:2] == ("POST", "/v1/pages")
    assert notion_client.requests[0][2]["properties"]["Parent"] == {
        "relation": [{"id": "22222222222222222222222222222222"}]
    }
    assert notion_client.requests[0][2]["children"][0]["type"] == "heading_2"


def test_rich_text_items_render_date_and_page_mentions():
    rich_text_items = _rich_text_items(
        'See <mention-date start="2026-05-26"/> and <mention-page url="https://www.notion.so/22222222222222222222222222222222"/>.'
    )

    assert rich_text_items == [
        {"type": "text", "text": {"content": "See "}},
        {"type": "mention", "mention": {"type": "date", "date": {"start": "2026-05-26"}}},
        {"type": "text", "text": {"content": " and "}},
        {
            "type": "mention",
            "mention": {
                "type": "page",
                "page": {"id": "22222222222222222222222222222222"},
            },
        },
        {"type": "text", "text": {"content": "."}},
    ]


def test_markdown_from_rest_blocks_preserves_date_mentions():
    markdown = _markdown_from_rest_blocks([
        {
            "type": "heading_3",
            "heading_3": {
                "rich_text": [
                    {
                        "type": "mention",
                        "mention": {
                            "type": "date",
                            "date": {"start": "2026-05-26"},
                        },
                        "plain_text": "2026-05-26",
                    }
                ]
            },
        }
    ])

    assert markdown == '### <mention-date start="2026-05-26"/>'


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


def _page_registry() -> NotionPageRegistry:
    return NotionPageRegistry(
        pages={
            "landing_page": NotionPageReference(
                local_page_key="landing_page",
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
