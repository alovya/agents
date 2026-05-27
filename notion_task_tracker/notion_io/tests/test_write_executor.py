import asyncio

from notion_task_tracker import NotionPageReference, NotionPageRegistry, NotionWriteIntent
from notion_task_tracker.apply_tracker_command import TrackerCommandResult
from notion_task_tracker.notion_io.client import NotionWriteExecutionResult
from notion_task_tracker.notion_io.write_executor import execute_command_result_writes


def test_execute_command_result_writes_sends_intents_to_selected_client():
    notion_client = FakeNotionClient()
    command_result = TrackerCommandResult(
        tracker_state={},
        write_intents=[
            NotionWriteIntent(
                operation_key="replace:landing_page",
                operation_name="replace_page_markdown",
                target_page_key="landing_page",
                arguments={"markdown": "A"},
            ),
            NotionWriteIntent(
                operation_key="update_properties:task:ALOVYA-1",
                operation_name="update_page_properties",
                target_page_key="task:ALOVYA-1",
                arguments={"properties": {"Status": "Active"}},
            ),
        ],
        page_registry=NotionPageRegistry(
            pages={
                "landing_page": NotionPageReference(
                    local_page_key="landing_page",
                    title="Landing",
                    notion_page_id="11111111111111111111111111111111",
                ),
                "task:ALOVYA-1": NotionPageReference(
                    local_page_key="task:ALOVYA-1",
                    title="Task",
                    notion_page_id="22222222222222222222222222222222",
                ),
            }
        ),
    )

    _tracker_state, completed_operation_keys = asyncio.run(
        execute_command_result_writes(command_result, notion_client)
    )

    assert [tool_call.operation_key for tool_call in notion_client.calls] == [
        "replace:landing_page",
        "update_properties:task:ALOVYA-1",
    ]
    assert completed_operation_keys == [
        "replace:landing_page",
        "update_properties:task:ALOVYA-1",
    ]


class FakeNotionClient:
    def __init__(self):
        self.calls = []

    async def execute_command_result(self, command_result: TrackerCommandResult):
        self.calls.extend(command_result.write_intents)
        return NotionWriteExecutionResult(
            completed_operation_keys=[
                write_intent.operation_key
                for write_intent in command_result.write_intents
            ],
        )
