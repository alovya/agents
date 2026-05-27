import asyncio

from notion_task_tracker.tasks.actions.create_task_page_in_database import execute_task_creation_command
from notion_task_tracker.tasks.actions.tests.helpers import (
    FakeNotionClient,
    tracker_state_with_root_task,
)
from notion_task_tracker.tasks.database import default_task_database_tracker_state


def test_execute_task_creation_command_creates_database_row_then_refreshes_landing():
    tracker_state = tracker_state_with_root_task()
    tracker_state["task_database"] = default_task_database_tracker_state()
    notion_client = FakeNotionClient(
        results=[
            {"result": {"text": "https://www.notion.so/33333333333333333333333333333333"}},
            {"result": {"text": ""}},
            {"result": {"text": ""}},
            {"result": {"text": ""}},
        ],
        fetched_page_content_by_id={
            "33333333333333333333333333333333": "\n".join(
                [
                    "<page>",
                    "<properties>",
                    '{"Ticket ID":"72","Ticket page":"Child task"}',
                    "</properties>",
                    "</page>",
                ]
            )
        },
    )

    updated_tracker_state, completed_operation_keys = asyncio.run(
        execute_task_creation_command(
            command={
                "command": "create_child_task",
                "parent_task_id": "ALOVYA-1",
                "child_task": {
                    "title": "Child task",
                    "configured_priority": "P2",
                    "status": "Active",
                },
                "parent_timeline_entry": {
                    "entry_date": "2026-05-25",
                    "heading": '<mention-date start="2026-05-25"/>',
                    "lines": ["Spawned child task."],
                },
            },
            tracker_state=tracker_state,
            notion_client=notion_client,
        )
    )

    assert updated_tracker_state["tasks"]["ALOVYA-72"]["parent_task_id"] == "ALOVYA-1"
    assert updated_tracker_state["tasks"]["ALOVYA-72"]["notion_page_id"] == "33333333333333333333333333333333"
    assert updated_tracker_state["tasks"]["ALOVYA-72"]["timeline_entries"] == [
        {
            "entry_date": "2026-05-25",
            "heading": '<mention-date start="2026-05-25"/>',
            "lines": [],
        }
    ]
    assert completed_operation_keys == [
        "create_database_task:create_child_task",
        "update_properties:task:ALOVYA-72",
        "update_timeline_log:task:ALOVYA-1:2026-05-25",
        "replace:landing_page",
    ]
    assert notion_client.calls[0].tool_name == "notion-create-pages"
    assert notion_client.calls[0].arguments["parent"] == {
        "type": "data_source_id",
        "data_source_id": "36b03da5-d69a-8080-91d1-000b5d7c1c8d",
    }
    assert notion_client.calls[0].arguments["pages"][0]["properties"] == {
        "Ticket page": "Child task",
        "Priority": "P2",
        "Status": "Active",
        "Parent": '["https://www.notion.so/22222222222222222222222222222222"]',
    }
    assert notion_client.calls[0].arguments["pages"][0]["content"] == "\n".join(
        [
            "## Timeline log",
            '### <mention-date start="2026-05-25"/>',
            '- Spawned from parent task: <mention-page url="https://www.notion.so/22222222222222222222222222222222"/>.',
        ]
    )
    assert notion_client.calls[1].arguments["properties"] == {
        "Ticket page": "Child task",
    }
    assert notion_client.calls[2].arguments["new_str"] == "\n".join(
        [
            "## Timeline log",
            '### <mention-date start="2026-05-25"/>',
            '- Spawned child task: <mention-page url="https://www.notion.so/33333333333333333333333333333333"/>.',
        ]
    )
    assert notion_client.calls[-1].arguments["command"] == "replace_content"
