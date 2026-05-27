import asyncio

import pytest

from notion_task_tracker.tasks.actions.refresh_task_tracker_state import (
    refresh_tracker_state_for_command_targets,
    refresh_tracker_state_from_task_database,
)
from notion_task_tracker.tasks.actions.tests.helpers import (
    FakeNotionClient,
    fetched_task_page,
    tracker_state_with_root_and_child_task,
    tracker_state_with_root_task,
)
from notion_task_tracker.tasks.database import default_task_database_tracker_state


def test_refresh_tracker_state_from_task_database_uses_database_view_when_configured():
    tracker_state = tracker_state_with_root_task()
    tracker_state["task_database"] = default_task_database_tracker_state()
    notion_client = FakeNotionClient(
        database_rows=[
            {
                "Ticket page": "Root task edited in database",
                "Ticket ID": "1",
                "Priority": "P2",
                "Status": "Blocked",
                "Parent": "[]",
                "url": "https://www.notion.so/22222222222222222222222222222222",
            }
        ]
    )

    command_result = asyncio.run(
        refresh_tracker_state_from_task_database(tracker_state, notion_client)
    )

    assert command_result.tracker_state["tasks"]["ALOVYA-1"]["title"] == "Root task edited in database"
    assert command_result.tracker_state["tasks"]["ALOVYA-1"]["configured_priority"] == "P2"
    assert command_result.tracker_state["tasks"]["ALOVYA-1"]["status"] == "Blocked"
    assert notion_client.view_queries == [
        "https://www.notion.so/wayve/36b03da5d69a80b4acacf711623b59e8?v=36b03da5d69a800c893f000cf2aefead"
    ]
    assert notion_client.queries == []
    assert notion_client.fetched_pages == []


def test_refresh_tracker_state_from_task_database_uses_sql_when_view_is_not_configured():
    tracker_state = tracker_state_with_root_task()
    tracker_state["task_database"] = default_task_database_tracker_state()
    tracker_state["task_database"].pop("view_url")
    notion_client = FakeNotionClient(
        database_rows=[
            {
                "Ticket page": "Root task edited in database",
                "Ticket ID": "1",
                "Priority": "P2",
                "Status": "Blocked",
                "Parent": "[]",
                "url": "https://www.notion.so/22222222222222222222222222222222",
            }
        ]
    )

    command_result = asyncio.run(
        refresh_tracker_state_from_task_database(tracker_state, notion_client)
    )

    assert command_result.tracker_state["tasks"]["ALOVYA-1"]["configured_priority"] == "P2"
    assert notion_client.view_queries == []
    assert notion_client.queries == [
        {
            "data_source_url": "collection://36b03da5-d69a-8080-91d1-000b5d7c1c8d",
            "query": (
                'SELECT * FROM "collection://36b03da5-d69a-8080-91d1-000b5d7c1c8d" '
                'WHERE "Priority" IS NOT NULL AND "Status" IS NOT NULL'
            ),
        }
    ]


def test_refresh_tracker_state_for_command_targets_fetches_only_relevant_pages():
    tracker_state = tracker_state_with_root_and_child_task()
    notion_client = FakeNotionClient(
        fetched_page_content_by_id={
            "22222222222222222222222222222222": fetched_task_page(
                ticket_id="1",
                title="Root task",
                priority="P1",
                status="Active",
                parent_urls=[],
            ),
            "33333333333333333333333333333333": fetched_task_page(
                ticket_id="2",
                title="Child task edited in database",
                priority="P2",
                status="Blocked",
                parent_urls=["https://www.notion.so/22222222222222222222222222222222"],
            ),
        }
    )

    command_result = asyncio.run(
        refresh_tracker_state_for_command_targets(
            command={
                "command": "create_sibling_task",
                "sibling_task_id": "ALOVYA-2",
                "sibling_task": {
                    "title": "Sibling task",
                    "configured_priority": "P2",
                    "status": "Active",
                },
            },
            tracker_state=tracker_state,
            notion_client=notion_client,
        )
    )

    assert command_result.tracker_state["tasks"]["ALOVYA-2"]["title"] == "Child task edited in database"
    assert command_result.tracker_state["tasks"]["ALOVYA-2"]["configured_priority"] == "P2"
    assert command_result.tracker_state["tasks"]["ALOVYA-2"]["status"] == "Blocked"
    assert command_result.tracker_state["tasks"]["ALOVYA-2"]["parent_task_id"] == "ALOVYA-1"
    assert notion_client.fetched_pages == [
        "33333333333333333333333333333333",
        "22222222222222222222222222222222",
    ]
    assert notion_client.view_queries == []
    assert notion_client.queries == []


def test_refresh_tracker_state_for_command_targets_requires_known_tasks():
    tracker_state = tracker_state_with_root_task()
    notion_client = FakeNotionClient()

    with pytest.raises(ValueError, match="ALOVYA-99"):
        asyncio.run(
            refresh_tracker_state_for_command_targets(
                command={
                    "command": "complete_task",
                    "task_id": "ALOVYA-99",
                    "timeline_entry": {
                        "entry_date": "2026-05-26",
                        "heading": '<mention-date start="2026-05-26"/>',
                        "lines": ["Completed missing task."],
                    },
                },
                tracker_state=tracker_state,
                notion_client=notion_client,
            )
        )

    assert notion_client.fetched_pages == []
    assert notion_client.view_queries == []
    assert notion_client.queries == []
