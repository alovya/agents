from notion_task_tracker.apply_tracker_command import TrackerCommandResult
from notion_task_tracker.notion_operations.prepare_task_page_timeline_log_write import (
    merge_context_repairs_into_command_result,
    plan_context_repair_result,
)
from notion_task_tracker.notion_operations.write_intent import NotionWriteIntent
from notion_task_tracker.tasks.tests.build_task_command_fixtures import build_tracker_state_with_root_task


def test_plan_context_repair_result_plans_repairs_without_writing_them():
    before_tracker_state = build_tracker_state_with_root_task()
    after_tracker_state = build_tracker_state_with_root_task()
    after_tracker_state["tasks"]["ALOVYA-1"]["title"] = "Root task edited in Notion"

    repair_result = plan_context_repair_result(
        before_tracker_state=before_tracker_state,
        command_ready_result=TrackerCommandResult(tracker_state=after_tracker_state),
    )

    assert repair_result.tracker_state["tasks"]["ALOVYA-1"]["title"] == "Root task edited in Notion"
    assert [write_intent.operation_key for write_intent in repair_result.write_intents] == [
        "update_properties:task:ALOVYA-1",
        "replace:landing_page",
    ]


def test_merge_context_repairs_into_command_result_keeps_one_ordered_write_set_and_command_wins():
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

    combined_result = merge_context_repairs_into_command_result(context_repair_result, command_result)

    assert combined_result.tracker_state == {"phase": "command"}
    assert [write_intent.operation_key for write_intent in combined_result.write_intents] == [
        "replace:landing_page",
        "update_properties:task:ALOVYA-1",
        "update_timeline_log:task:ALOVYA-1:2026-05-26",
    ]
    assert combined_result.write_intents[0].arguments["markdown"] == "Command landing"
