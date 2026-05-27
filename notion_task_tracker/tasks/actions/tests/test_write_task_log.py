import asyncio

from notion_task_tracker.apply_tracker_command import TrackerCommandResult
from notion_task_tracker.notion_io.writes import NotionWriteIntent
from notion_task_tracker.tasks.actions.tests.helpers import (
    FakeNotionClient,
    tracker_state_with_root_task,
)
from notion_task_tracker.tasks.actions.write_task_log import (
    command_result_with_context_repairs,
    repair_result_for_command_context,
    timeline_state_for_task_command,
    tracker_state_with_fetched_task_timeline_dates,
)


def test_repair_result_for_command_context_plans_repairs_without_writing_them():
    before_tracker_state = tracker_state_with_root_task()
    after_tracker_state = tracker_state_with_root_task()
    after_tracker_state["tasks"]["ALOVYA-1"]["title"] = "Root task edited in Notion"

    repair_result = repair_result_for_command_context(
        before_tracker_state=before_tracker_state,
        command_ready_result=TrackerCommandResult(tracker_state=after_tracker_state),
    )

    assert repair_result.tracker_state["tasks"]["ALOVYA-1"]["title"] == "Root task edited in Notion"
    assert [write_intent.operation_key for write_intent in repair_result.write_intents] == [
        "update_properties:task:ALOVYA-1",
        "replace:landing_page",
    ]


def test_command_result_with_context_repairs_keeps_one_ordered_write_set_and_command_wins():
    context_repair_result = TrackerCommandResult(
        tracker_state={"phase": "ready"},
        write_intents=[
            NotionWriteIntent(
                operation_key="replace:landing_page",
                operation_name="replace_page_markdown",
                target_page_key="landing_page",
                arguments={"markdown": "Stale landing"},
            ),
            NotionWriteIntent(
                operation_key="update_properties:task:ALOVYA-1",
                operation_name="update_page_properties",
                target_page_key="task:ALOVYA-1",
                arguments={"properties": {"Status": "Active"}},
            ),
        ],
    )
    command_result = TrackerCommandResult(
        tracker_state={"phase": "command"},
        write_intents=[
            NotionWriteIntent(
                operation_key="replace:landing_page",
                operation_name="replace_page_markdown",
                target_page_key="landing_page",
                arguments={"markdown": "Command landing"},
            ),
            NotionWriteIntent(
                operation_key="update_timeline_log:task:ALOVYA-1:2026-05-26",
                operation_name="update_timeline_log",
                target_page_key="task:ALOVYA-1",
                arguments={"timeline_section_markdown": "### 2026-05-26"},
            ),
        ],
    )

    combined_result = command_result_with_context_repairs(context_repair_result, command_result)

    assert combined_result.tracker_state == {"phase": "command"}
    assert [write_intent.operation_key for write_intent in combined_result.write_intents] == [
        "replace:landing_page",
        "update_properties:task:ALOVYA-1",
        "update_timeline_log:task:ALOVYA-1:2026-05-26",
    ]
    assert combined_result.write_intents[0].arguments["markdown"] == "Command landing"


def test_tracker_state_with_fetched_task_timeline_dates_remembers_manual_date_before_logging():
    tracker_state = tracker_state_with_root_task()
    notion_client = FakeNotionClient(
        fetched_page_content_by_id={
            "22222222222222222222222222222222": "\n".join(
                [
                    "## Timeline log",
                    '### <mention-date start="2026-05-26"/>',
                    "- Human note.",
                ]
            )
        }
    )

    updated_tracker_state = asyncio.run(
        tracker_state_with_fetched_task_timeline_dates(
            task_id="ALOVYA-1",
            tracker_state=tracker_state,
            notion_client=notion_client,
        )
    )

    assert updated_tracker_state["tasks"]["ALOVYA-1"]["timeline_entries"] == [
        {
            "entry_date": "2026-05-26",
            "heading": '<mention-date start="2026-05-26"/>',
            "lines": [],
        }
    ]
    assert notion_client.fetched_pages == ["22222222222222222222222222222222"]


def test_timeline_state_for_task_command_records_missing_timeline_log_without_writing():
    tracker_state = tracker_state_with_root_task()
    notion_client = FakeNotionClient(
        fetched_page_content_by_id={
            "22222222222222222222222222222222": "\n".join(
                [
                    "<page>",
                    "<properties>",
                    '{"Ticket ID":"1","Ticket page":"Root task"}',
                    "</properties>",
                    "Loose notes written before the tracker touched the page.",
                    "</page>",
                ]
            )
        }
    )

    timeline_state = asyncio.run(
        timeline_state_for_task_command(
            task_id="ALOVYA-1",
            entry_date="2026-05-26",
            tracker_state=tracker_state,
            notion_client=notion_client,
        )
    )

    assert not timeline_state.has_usable_timeline_log
    assert timeline_state.tracker_state["tasks"]["ALOVYA-1"]["timeline_entries"] == [
        {
            "entry_date": "2026-05-26",
            "heading": '<mention-date start="2026-05-26"/>',
            "lines": [],
        }
    ]
    assert notion_client.calls == []


def test_timeline_state_for_task_command_records_empty_timeline_log_without_writing():
    tracker_state = tracker_state_with_root_task()
    notion_client = FakeNotionClient(
        fetched_page_content_by_id={
            "22222222222222222222222222222222": "\n".join(
                [
                    "## Timeline log",
                    "Loose notes already under the heading.",
                ]
            )
        }
    )

    timeline_state = asyncio.run(
        timeline_state_for_task_command(
            task_id="ALOVYA-1",
            entry_date="2026-05-26",
            tracker_state=tracker_state,
            notion_client=notion_client,
        )
    )

    assert not timeline_state.has_usable_timeline_log
    assert timeline_state.tracker_state["tasks"]["ALOVYA-1"]["timeline_entries"][0]["entry_date"] == "2026-05-26"
    assert notion_client.calls == []


def test_timeline_state_for_task_command_keeps_usable_timeline_log():
    tracker_state = tracker_state_with_root_task()
    notion_client = FakeNotionClient(
        fetched_page_content_by_id={
            "22222222222222222222222222222222": "\n".join(
                [
                    "## Timeline log",
                    '### <mention-date start="2026-05-25"/>',
                    "- Existing log.",
                ]
            )
        }
    )

    timeline_state = asyncio.run(
        timeline_state_for_task_command(
            task_id="ALOVYA-1",
            entry_date="2026-05-26",
            tracker_state=tracker_state,
            notion_client=notion_client,
        )
    )

    assert timeline_state.has_usable_timeline_log
    assert notion_client.calls == []
    assert timeline_state.tracker_state["tasks"]["ALOVYA-1"]["timeline_entries"] == [
        {
            "entry_date": "2026-05-25",
            "heading": '<mention-date start="2026-05-25"/>',
            "lines": [],
        }
    ]
