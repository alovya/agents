import asyncio
import json
from pathlib import Path

from notion_task_tracker import COMPLETED_LANDING_PAGE_TITLE, ONGOING_LANDING_PAGE_TITLE
from notion_task_tracker.apply_tracker_command import TrackerCommandResult
from notion_task_tracker.notion_operations.client import NotionWriteExecutionResult
from notion_task_tracker.tracker_cli_workflow import repair_and_write_refreshed_tracker_state


def test_repair_and_write_refreshed_tracker_state_pushes_repairs_for_changed_task(
    tmp_path: Path,
):
    notion_client = _FakeNotionClient()
    tracker_state_path = tmp_path / "tracker_state.json"
    output_path = tmp_path / "output.json"
    backup_path = tmp_path / "backup.json"
    before_tracker_state = _tracker_state(title="Investigate baseline behaviour", priority="P1")
    after_tracker_state = _tracker_state(title="Investigate edited behaviour", priority="P2")
    tracker_state_path.write_text(json.dumps(before_tracker_state), encoding="utf-8")
    backup_path.write_text(json.dumps(before_tracker_state), encoding="utf-8")

    refresh_summary = asyncio.run(
        repair_and_write_refreshed_tracker_state(
            source_tracker_state_path=tracker_state_path,
            destination_output_path=output_path,
            destination_backup_path=backup_path,
            before_tracker_state=before_tracker_state,
            refreshed_result=TrackerCommandResult(
                tracker_state=after_tracker_state,
                warnings=[{"kind": "manual_repair", "message": "Derived Notion views need repair"}],
            ),
            notion_client=notion_client,
        ),
    )

    assert json.loads(backup_path.read_text(encoding="utf-8")) == before_tracker_state
    assert json.loads(tracker_state_path.read_text(encoding="utf-8")) == after_tracker_state
    assert [write_intent.operation_key for write_intent in notion_client.write_intents] == [
        "update_properties:task:ALOVYA-1",
        "replace:ongoing_landing_page",
    ]
    assert json.loads(output_path.read_text(encoding="utf-8"))["completed_operations"] == [
        "update_properties:task:ALOVYA-1",
        "replace:ongoing_landing_page",
    ]
    assert refresh_summary.to_json_summary() == {
        "backup_path": str(backup_path),
        "completed_operations": [
            "update_properties:task:ALOVYA-1",
            "replace:ongoing_landing_page",
        ],
        "output_path": str(output_path),
        "tracker_state_path": str(tracker_state_path),
        "task_count": 1,
        "repair_operation_count": 2,
        "task_graph_changes": [
            {
                "task_id": "ALOVYA-1",
                "fields": {
                    "configured_priority": {"before": "P1", "after": "P2"},
                    "title": {
                        "before": "Investigate baseline behaviour",
                        "after": "Investigate edited behaviour",
                    },
                },
            }
        ],
        "warnings": [{"kind": "manual_repair", "message": "Derived Notion views need repair"}],
    }


def test_repair_and_write_refreshed_tracker_state_skips_repairs_when_nothing_changed(
    tmp_path: Path,
):
    notion_client = _FakeNotionClient()
    tracker_state_path = tmp_path / "tracker_state.json"
    output_path = tmp_path / "output.json"
    backup_path = tmp_path / "backup.json"
    tracker_state = _tracker_state(title="Stable task", priority="P1")
    tracker_state_path.write_text(json.dumps(tracker_state), encoding="utf-8")
    backup_path.write_text(json.dumps(tracker_state), encoding="utf-8")

    refresh_summary = asyncio.run(
        repair_and_write_refreshed_tracker_state(
            source_tracker_state_path=tracker_state_path,
            destination_output_path=output_path,
            destination_backup_path=backup_path,
            before_tracker_state=tracker_state,
            refreshed_result=TrackerCommandResult(
                tracker_state=tracker_state,
                warnings=[],
            ),
            notion_client=notion_client,
        ),
    )

    assert json.loads(output_path.read_text(encoding="utf-8"))["completed_operations"] == []
    assert notion_client.write_intents == []
    assert refresh_summary.to_json_summary()["task_graph_changes"] == []
    assert refresh_summary.to_json_summary()["repair_operation_count"] == 0


class _FakeNotionClient:
    def __init__(self):
        self.write_intents = []

    async def execute_command_result(self, command_result: TrackerCommandResult):
        self.write_intents.extend(command_result.write_intents)
        return NotionWriteExecutionResult(
            completed_operation_keys=[
                write_intent.operation_key
                for write_intent in command_result.write_intents
            ],
        )


def _tracker_state(title: str, priority: str) -> dict:
    return {
        "ongoing_landing_page": {
            "local_page_key": "ongoing_landing_page",
            "title": ONGOING_LANDING_PAGE_TITLE,
            "notion_page_id": "11111111111111111111111111111111",
            "parent_page_key": None,
        },
        "completed_landing_page": {
            "local_page_key": "completed_landing_page",
            "title": COMPLETED_LANDING_PAGE_TITLE,
            "notion_page_id": None,
            "parent_page_key": None,
        },
        "tasks": {
            "ALOVYA-1": {
                "task_id": "ALOVYA-1",
                "title": title,
                "configured_priority": priority,
                "displayed_priority": priority,
                "status": "Active",
                "status_update": "",
                "parent_task_id": None,
                "child_task_ids": [],
                "timeline_entries": [],
                "links": [],
                "notion_page_id": "22222222222222222222222222222222",
            }
        },
    }
