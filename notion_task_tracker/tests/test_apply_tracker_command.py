import json

from notion_task_tracker.apply_tracker_command import apply_command_to_tracker_state
from notion_task_tracker.tasks import Priority, Task, TaskStatus, TaskDependencyGraph


class TestApplyCommandToTrackerState:
    def test_append_task_timeline_log_updates_tracker_state_and_produces_write_intent(self):
        command_result = apply_command_to_tracker_state(
            command={
                "command": "append_task_timeline_log",
                "task_id": "ALOVYA-1",
                "timeline_entry": {
                    "entry_date": "2026-05-24",
                    "heading": '<mention-date start="2026-05-24"/>',
                    "lines": ["Found the remaining blocker."],
                },
            },
            tracker_state=_combined_tracker_state(),
        )

        assert command_result.tracker_state["tasks"]["ALOVYA-1"]["timeline_entries"] == [
            {
                "entry_date": "2026-05-24",
                "heading": '<mention-date start="2026-05-24"/>',
                "lines": [],
            }
        ]
        assert [write_intent.operation_key for write_intent in command_result.write_intents] == [
            "update_timeline_log:task:ALOVYA-1:2026-05-24"
        ]
        assert command_result.write_intents[0].operation_name == "update_timeline_log"
        assert command_result.write_intents[0].arguments["timeline_section_markdown"] == "\n".join([
            '### <mention-date start="2026-05-24"/>',
            "- Found the remaining blocker.",
        ])

    def test_append_task_timeline_log_inserts_after_existing_date_heading(self):
        tracker_state = _combined_tracker_state()
        tracker_state["tasks"]["ALOVYA-1"]["timeline_entries"] = [
            {
                "entry_date": "2026-05-24",
                "heading": '<mention-date start="2026-05-24"/>',
                "lines": ["Existing handwritten or reconciled line."],
            }
        ]

        command_result = apply_command_to_tracker_state(
            command={
                "command": "append_task_timeline_log",
                "task_id": "ALOVYA-1",
                "timeline_entry": {
                    "entry_date": "2026-05-24",
                    "heading": '<mention-date start="2026-05-24"/>',
                    "lines": ["New agent line."],
                },
            },
            tracker_state=tracker_state,
        )

        assert command_result.write_intents[0].arguments["existing_timeline_heading"] == (
            '<mention-date start="2026-05-24"/>'
        )
        assert command_result.write_intents[0].arguments["appended_markdown"] == "- New agent line."

    def test_append_task_timeline_log_preserves_manual_existing_date_heading(self):
        tracker_state = _combined_tracker_state()
        tracker_state["tasks"]["ALOVYA-1"]["timeline_entries"] = [
            {
                "entry_date": "2026-05-24",
                "heading": "2026-05-24",
                "lines": [],
            }
        ]

        command_result = apply_command_to_tracker_state(
            command={
                "command": "append_task_timeline_log",
                "task_id": "ALOVYA-1",
                "timeline_entry": {
                    "entry_date": "2026-05-24",
                    "heading": '<mention-date start="2026-05-24"/>',
                    "lines": ["New agent line."],
                },
            },
            tracker_state=tracker_state,
        )

        assert command_result.tracker_state["tasks"]["ALOVYA-1"]["timeline_entries"][0]["heading"] == "2026-05-24"
        assert command_result.write_intents[0].arguments["existing_timeline_heading"] == "2026-05-24"

    def test_append_task_timeline_log_with_subheading_inserts_toggle(self):
        tracker_state = _combined_tracker_state()
        tracker_state["tasks"]["ALOVYA-1"]["timeline_entries"] = [
            {
                "entry_date": "2026-05-24",
                "heading": '<mention-date start="2026-05-24"/>',
                "lines": [],
            }
        ]

        command_result = apply_command_to_tracker_state(
            command={
                "command": "append_task_timeline_log",
                "task_id": "ALOVYA-1",
                "timeline_entry": {
                    "entry_date": "2026-05-24",
                    "heading": '<mention-date start="2026-05-24"/>',
                    "subheading": "Design notes",
                    "lines": ["Moved task metadata into the database."],
                },
            },
            tracker_state=tracker_state,
        )

        assert command_result.write_intents[0].arguments["appended_markdown"] == "\n".join([
            "<details>",
            "<summary>Design notes</summary>",
            "\t- Moved task metadata into the database.",
            "</details>",
        ])

    def test_complete_task_updates_status_and_produces_write_intents(self):
        tracker_state = _combined_tracker_state()
        tracker_state["completed_landing_page"]["notion_page_id"] = "33333333333333333333333333333333"
        command_result = apply_command_to_tracker_state(
            command={
                "command": "complete_task",
                "task_id": "ALOVYA-1",
                "timeline_entry": {
                    "entry_date": "2026-05-24",
                    "heading": '<mention-date start="2026-05-24"/>',
                    "lines": ["Completed the task."],
                },
            },
            tracker_state=tracker_state,
        )

        assert command_result.tracker_state["tasks"]["ALOVYA-1"]["status"] == "Complete"
        assert command_result.tracker_state["tasks"]["ALOVYA-1"]["timeline_entries"] == [
            {
                "entry_date": "2026-05-24",
                "heading": '<mention-date start="2026-05-24"/>',
                "lines": [],
            }
        ]
        assert [write_intent.operation_key for write_intent in command_result.write_intents] == [
            "update_properties:task:ALOVYA-1",
            "replace:landing_page",
            "replace:completed_landing_page",
            "update_timeline_log:task:ALOVYA-1:2026-05-24",
        ]
        write_intents_by_key = {
            write_intent.operation_key: write_intent
            for write_intent in command_result.write_intents
        }
        assert write_intents_by_key["update_properties:task:ALOVYA-1"].target_page_key == "task:ALOVYA-1"
        assert write_intents_by_key["update_properties:task:ALOVYA-1"].arguments["properties"]["Status"] == "Complete"
        assert write_intents_by_key["replace:landing_page"].operation_name == "replace_page_markdown"
        assert write_intents_by_key["replace:completed_landing_page"].arguments["markdown"].startswith("## Completed")
        assert write_intents_by_key["update_timeline_log:task:ALOVYA-1:2026-05-24"].operation_name == (
            "update_timeline_log"
        )

    def test_append_miscellaneous_note_command_updates_combined_tracker_state(self):
        command_result = apply_command_to_tracker_state(
            command={
                "command": "append_miscellaneous_note",
                "note_date": "2026-05-24",
                "lines": ["Recent context."],
            },
            tracker_state=_combined_tracker_state(),
        )

        assert "tasks" in command_result.tracker_state
        assert command_result.tracker_state["miscellaneous_notes"]["dated_pages"]["2026-05-24"]["entries"][0]["lines"] == [
            "Recent context."
        ]
        assert command_result.write_intents[0].operation_name == "append_miscellaneous_context"
        assert command_result.write_intents[0].target_page_key == "miscellaneous:2026-05-24"

    def test_create_synthesis_page_command_updates_combined_tracker_state(self):
        command_result = apply_command_to_tracker_state(
            command={
                "command": "create_synthesis_page",
                "synthesis_key": "onnx_qdq",
                "title": "ONNX QDQ",
                "summary": "Reusable explanation.",
                "sources": [
                    {
                        "source_type": "Notion page",
                        "label": "ALOVYA-1",
                        "page_key": "task:ALOVYA-1",
                    }
                ],
                "lines": ["QDQ nodes preserve quantisation boundaries."],
            },
            tracker_state=_combined_tracker_state(),
        )

        assert "tasks" in command_result.tracker_state
        assert command_result.tracker_state["synthesis_notes"]["pages"]["onnx_qdq"]["sources"][0]["page_key"] == (
            "task:ALOVYA-1"
        )
        assert command_result.write_intents[0].operation_name == "create_synthesis_page"
        assert command_result.write_intents[0].arguments["page"]["local_page_key"] == "synthesis:onnx_qdq"
        assert command_result.write_intents[0].arguments["markdown"].startswith("## Sources")

    def test_reconcile_synthesis_root_page_mentions_updates_tracker_state_without_rest_writes(self):
        tracker_state = _combined_tracker_state()
        tracker_state["synthesis_notes"]["existing_page_mentions"] = {
            "stale": {
                "mention_key": "stale",
                "title": "Stale page",
                "notion_page_id": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
            },
        }

        command_result = apply_command_to_tracker_state(
            command={
                "command": "reconcile_synthesis_root_page_mentions",
                "root_page_content": (
                    '<mention-page url="https://www.notion.so/wayve/Useful-guide-'
                    'bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb">Useful guide</mention-page>'
                ),
            },
            tracker_state=tracker_state,
        )

        assert command_result.tracker_state["synthesis_notes"]["existing_page_mentions"] == {
            "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb": {
                "mention_key": "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
                "title": "Useful guide",
                "notion_page_id": "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
                "display_order": 0,
                "root_block_type": "page_mention",
            },
        }
        assert command_result.write_intents == []

    def test_record_page_id_command_updates_combined_synthesis_tracker_state(self):
        tracker_state = _combined_tracker_state()
        tracker_state["synthesis_notes"]["pages"]["onnx_qdq"] = {
            "synthesis_key": "onnx_qdq",
            "title": "ONNX QDQ",
            "summary": "",
            "lines": [],
            "sources": [],
            "notion_page_id": None,
        }

        command_result = apply_command_to_tracker_state(
            command={
                "command": "record_page_id",
                "local_page_key": "synthesis:onnx_qdq",
                "notion_page_id": "66666666666666666666666666666666",
            },
            tracker_state=tracker_state,
        )

        assert command_result.tracker_state["tasks"] == tracker_state["tasks"]
        assert command_result.tracker_state["synthesis_notes"]["pages"]["onnx_qdq"]["notion_page_id"] == (
            "66666666666666666666666666666666"
        )


def _combined_tracker_state():
    tracker_state = _task_tracker_state()
    tracker_state["miscellaneous_notes"] = {
        "page": {
            "local_page_key": "miscellaneous_notes",
            "title": "Alovya's miscellanous notes",
            "notion_page_id": "44444444444444444444444444444444",
            "parent_page_key": None,
        },
        "dated_pages": {},
    }
    tracker_state["synthesis_notes"] = {
        "page": {
            "local_page_key": "synthesis_notes",
            "title": "Alovya's synthesis notes",
            "notion_page_id": "55555555555555555555555555555555",
            "parent_page_key": None,
        },
        "pages": {},
    }
    return tracker_state


def _task_tracker_state():
    work_graph = TaskDependencyGraph()
    work_graph.ongoing_tasks_landing_page.page.notion_page_id = "11111111111111111111111111111111"
    work_graph.add_task(
        Task(
            task_id="ALOVYA-1",
            title="Root task",
            configured_priority=Priority.P1,
            status=TaskStatus.ACTIVE,
            notion_page_id="22222222222222222222222222222222",
        )
    )
    return work_graph.to_tracker_state()
