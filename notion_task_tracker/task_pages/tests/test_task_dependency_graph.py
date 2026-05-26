from __future__ import annotations

import json

import pytest

from notion_task_tracker.common import COMPLETED_LANDING_PAGE_TITLE, LANDING_PAGE_TITLE
from notion_task_tracker.task_pages import (
    Priority,
    TaskDependencyGraph,
    TaskPageMetadata,
    TaskStatus,
    TimelineEntry,
)
from notion_task_tracker.task_pages.tests.task_page_test_helpers import (
    _build_recursive_work_graph,
    _visible_strikethrough_text,
)


class TestTaskDependencyGraphRecalculateDisplayPriorities:
    def test_active_deep_child_priority_rolls_up_to_ancestors(self):
        work_graph = _build_recursive_work_graph()

        work_graph.recalculate_display_priorities()

        assert work_graph.tasks["ALOVYA-5"].displayed_priority == Priority.P0
        assert work_graph.tasks["ALOVYA-3"].displayed_priority == Priority.P0
        assert work_graph.tasks["ALOVYA-2"].displayed_priority == Priority.P0
        assert work_graph.tasks["ALOVYA-4"].displayed_priority == Priority.P3

    def test_completed_deep_child_priority_stops_rolling_up(self):
        work_graph = _build_recursive_work_graph()
        work_graph.tasks["ALOVYA-5"].status = TaskStatus.COMPLETE

        work_graph.recalculate_display_priorities()

        assert work_graph.tasks["ALOVYA-5"].displayed_priority == Priority.P0
        assert work_graph.tasks["ALOVYA-3"].displayed_priority == Priority.P1
        assert work_graph.tasks["ALOVYA-2"].displayed_priority == Priority.P1


class TestTaskDependencyGraphValidate:
    def test_rejects_parent_child_link_mismatch(self):
        work_graph = _build_recursive_work_graph()
        work_graph.tasks["ALOVYA-5"].parent_task_id = "ALOVYA-2"

        with pytest.raises(ValueError, match="should have parent ALOVYA-3"):
            work_graph.validate()

    def test_rejects_task_hierarchy_cycle(self):
        work_graph = TaskDependencyGraph()
        work_graph.add_task(
            TaskPageMetadata(
                task_id="ALOVYA-1",
                title="Root",
                configured_priority=Priority.P1,
                status=TaskStatus.ACTIVE,
                parent_task_id="ALOVYA-2",
                child_task_ids=["ALOVYA-2"],
            )
        )
        work_graph.add_task(
            TaskPageMetadata(
                task_id="ALOVYA-2",
                title="Child",
                configured_priority=Priority.P1,
                status=TaskStatus.ACTIVE,
                parent_task_id="ALOVYA-1",
                child_task_ids=["ALOVYA-1"],
            )
        )

        with pytest.raises(ValueError, match="Task hierarchy has a cycle"):
            work_graph.validate()


class TestTaskDependencyGraphFromSnapshot:
    def test_loads_null_completed_landing_page_as_missing_page_id(self):
        work_graph = TaskDependencyGraph.from_snapshot(
            {
                "landing_page": {
                    "local_page_key": "landing_page",
                    "title": LANDING_PAGE_TITLE,
                    "notion_page_id": "11111111111111111111111111111111",
                    "parent_page_key": None,
                },
                "completed_landing_page": None,
                "tasks": {},
            }
        )

        assert work_graph.completed_landing_page.title == COMPLETED_LANDING_PAGE_TITLE
        assert work_graph.completed_landing_page.notion_page_id is None


class TestTaskDependencyGraphTaskIdsGroupedForLandingPage:
    def test_groups_live_top_level_tasks_by_displayed_priority(self):
        work_graph = _build_recursive_work_graph()
        work_graph.add_task(
            TaskPageMetadata(
                task_id="ALOVYA-9",
                title="Parked cleanup",
                configured_priority=Priority.P3,
                status=TaskStatus.PARKED,
                notion_page_id="99999999999999999999999999999999",
            )
        )

        grouped_task_ids = work_graph.task_ids_grouped_for_landing_page()

        assert grouped_task_ids[Priority.P0] == ["ALOVYA-2"]
        assert grouped_task_ids[Priority.P3] == ["ALOVYA-9"]

    def test_keeps_completed_top_level_tasks_in_completed_section(self):
        work_graph = _build_recursive_work_graph()
        work_graph.add_task(
            TaskPageMetadata(
                task_id="ALOVYA-9",
                title="Completed optimisation",
                configured_priority=Priority.P0,
                status=TaskStatus.COMPLETE,
                notion_page_id="99999999999999999999999999999999",
            )
        )

        grouped_task_ids = work_graph.task_ids_grouped_for_landing_page()

        assert grouped_task_ids[Priority.P0] == ["ALOVYA-2"]
        assert work_graph.completed_task_ids_for_landing_page() == ["ALOVYA-9"]

    def test_orders_top_level_tasks_by_ticket_number_not_title(self):
        work_graph = _build_recursive_work_graph()
        work_graph.add_task(
            TaskPageMetadata(
                task_id="ALOVYA-10",
                title="A title that would sort before the existing task",
                configured_priority=Priority.P0,
                status=TaskStatus.ACTIVE,
                notion_page_id="aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
            )
        )

        grouped_task_ids = work_graph.task_ids_grouped_for_landing_page()

        assert grouped_task_ids[Priority.P0] == ["ALOVYA-2", "ALOVYA-10"]


class TestTaskDependencyGraphBuildNotionWritePlan:
    def test_refreshes_fixed_pages_and_database_task_properties_without_creating_task_pages(self):
        work_graph = _build_recursive_work_graph()

        write_intents = work_graph.build_notion_write_plan()

        assert not any(
            write_intent.operation_key.startswith("create:task:")
            for write_intent in write_intents
        )
        assert not any(
            write_intent.operation_key.startswith("replace:task:")
            for write_intent in write_intents
        )
        assert {
            write_intent.operation_key
            for write_intent in write_intents
        } >= {
            "create:landing_page",
            "create:completed_landing_page",
            "replace:landing_page",
            "update_properties:task:ALOVYA-2",
            "update_properties:task:ALOVYA-4",
        }

    def test_renders_landing_page_trees_from_database_graph(self):
        work_graph = _build_recursive_work_graph()

        landing_refresh_intent = next(
            write_intent
            for write_intent in work_graph.build_notion_write_plan()
            if write_intent.operation_key == "replace:landing_page"
        )

        landing_blocks = landing_refresh_intent.arguments["blocks"]
        landing_task_blocks = [
            block
            for block in landing_blocks
            if block["type"] == "bulleted_list_item"
        ]
        assert landing_blocks[0] == {"type": "heading_2", "text": "P0 (high impact and urgent)"}
        assert landing_task_blocks[0]["page_key"] == "task:ALOVYA-2"
        assert landing_task_blocks[0]["depth"] == 0
        assert landing_task_blocks[0]["text"] == "[P0] Activation quantisation stack: Active"
        assert landing_task_blocks[0]["color"] == "red"
        assert landing_task_blocks[1]["page_key"] == "task:ALOVYA-3"
        assert landing_task_blocks[1]["depth"] == 1
        assert landing_task_blocks[1]["color"] == "red"
        assert landing_task_blocks[2]["page_key"] == "task:ALOVYA-5"
        assert landing_task_blocks[2]["depth"] == 2
        assert landing_task_blocks[2]["color"] == "red"
        assert landing_task_blocks[3]["page_key"] == "task:ALOVYA-4"
        assert landing_task_blocks[3]["color"] == "green"
        assert landing_task_blocks[3]["text"].startswith("[N/A]")

    def test_renders_completed_page_from_completed_top_level_tasks_only(self):
        work_graph = _build_recursive_work_graph()
        work_graph.completed_landing_page.notion_page_id = "completed-landing-page-id"

        completed_landing_refresh_intent = next(
            write_intent
            for write_intent in work_graph.build_notion_write_plan()
            if write_intent.operation_key == "replace:completed_landing_page"
        )

        assert completed_landing_refresh_intent.arguments["blocks"] == [
            {"type": "paragraph", "text": "No completed tasks yet."}
        ]

    def test_completed_task_page_title_strikes_through_and_properties_include_database_metadata(self):
        work_graph = _build_recursive_work_graph()

        title_refresh_intent = next(
            write_intent
            for write_intent in work_graph.build_notion_write_plan()
            if write_intent.operation_key == "update_properties:task:ALOVYA-4"
        )

        assert title_refresh_intent.arguments["properties"] == {
            "Priority": "P3",
            "Status": "Complete",
            "Ticket page": _visible_strikethrough_text("Complete calibration branch"),
        }


class TestTaskDependencyGraphAppendTaskTimelineLog:
    def test_returns_single_timeline_update_intent(self):
        work_graph = _build_recursive_work_graph()
        timeline_entry = TimelineEntry(
            entry_date="2026-05-25",
            heading='<mention-date start="2026-05-25"/>',
            lines=["Tested the mismatch fix and found one remaining failing node."],
        )

        write_intent = work_graph.append_task_timeline_log(
            task_id="ALOVYA-5",
            timeline_entry=timeline_entry,
        )

        assert work_graph.tasks["ALOVYA-5"].timeline_entries[-1] == timeline_entry
        assert write_intent.operation_name == "update_timeline_log"
        assert write_intent.target_page_key == "task:ALOVYA-5"
        assert write_intent.arguments["task_id"] == "ALOVYA-5"
        assert write_intent.arguments["timeline_log_heading"] == "Timeline log"
        assert write_intent.arguments["timeline_entry"]["entry_date"] == "2026-05-25"
        assert write_intent.arguments["blocks"][0]["text"] == '<mention-date start="2026-05-25"/>'
        assert "existing_blocks" not in write_intent.arguments

    def test_appends_lines_to_existing_timeline_entry_for_same_date(self):
        work_graph = _build_recursive_work_graph()
        work_graph.tasks["ALOVYA-5"].timeline_entries.append(
            TimelineEntry(
                entry_date="2026-05-25",
                heading='<mention-date start="2026-05-25"/>',
                lines=["Started debugging the repair path."],
            )
        )

        write_intent = work_graph.append_task_timeline_log(
            task_id="ALOVYA-5",
            timeline_entry=TimelineEntry(
                entry_date="2026-05-25",
                heading='<mention-date start="2026-05-25"/>',
                lines=["Found the stale REST request."],
            ),
        )

        assert work_graph.tasks["ALOVYA-5"].timeline_entries == [
            TimelineEntry(
                entry_date="2026-05-25",
                heading='<mention-date start="2026-05-25"/>',
                lines=[
                    "Started debugging the repair path.",
                    "Found the stale REST request.",
                ],
            )
        ]
        assert write_intent.arguments["timeline_entry"]["lines"] == []
        assert write_intent.arguments["append_blocks"] == [
            {
                "type": "bulleted_list_item",
                "depth": 0,
                "text": "Found the stale REST request.",
            },
        ]

    def test_appends_subheaded_lines_as_toggle_content(self):
        work_graph = _build_recursive_work_graph()
        work_graph.tasks["ALOVYA-5"].timeline_entries.append(
            TimelineEntry(
                entry_date="2026-05-25",
                heading='<mention-date start="2026-05-25"/>',
            )
        )

        write_intent = work_graph.append_task_timeline_log(
            task_id="ALOVYA-5",
            timeline_entry=TimelineEntry(
                entry_date="2026-05-25",
                heading='<mention-date start="2026-05-25"/>',
                subheading="Design notes",
                lines=["Moved task metadata into the database."],
            ),
        )

        assert write_intent.arguments["append_blocks"] == [
            {
                "type": "toggle",
                "text": "Design notes",
                "children": [
                    {
                        "type": "bulleted_list_item",
                        "depth": 0,
                        "text": "Moved task metadata into the database.",
                    }
                ],
            }
        ]

    def test_collapses_existing_duplicate_date_headings_before_appending_lines(self):
        work_graph = _build_recursive_work_graph()
        work_graph.tasks["ALOVYA-5"].timeline_entries.extend(
            [
                TimelineEntry(
                    entry_date="2026-05-25",
                    heading='<mention-date start="2026-05-25"/>',
                    lines=["Started debugging the repair path."],
                ),
                TimelineEntry(
                    entry_date="2026-05-25",
                    heading='<mention-date start="2026-05-25"/>',
                    lines=["Found the stale REST request."],
                ),
            ]
        )

        work_graph.append_task_timeline_log(
            task_id="ALOVYA-5",
            timeline_entry=TimelineEntry(
                entry_date="2026-05-25",
                heading='<mention-date start="2026-05-25"/>',
                lines=["Patched the call generator."],
            ),
        )

        assert work_graph.tasks["ALOVYA-5"].timeline_entries == [
            TimelineEntry(
                entry_date="2026-05-25",
                heading='<mention-date start="2026-05-25"/>',
                lines=[
                    "Started debugging the repair path.",
                    "Found the stale REST request.",
                    "Patched the call generator.",
                ],
            )
        ]


class TestTaskDependencyGraphCompleteTask:
    def test_marks_task_complete_and_updates_database_properties_plus_derived_views(self):
        work_graph = _build_recursive_work_graph()
        timeline_entry = TimelineEntry(
            entry_date="2026-05-25",
            heading='<mention-date start="2026-05-25"/>',
            lines=["Completed the mismatch investigation."],
        )

        write_intents = work_graph.complete_task(
            task_id="ALOVYA-5",
            timeline_entry=timeline_entry,
        )

        assert work_graph.tasks["ALOVYA-5"].status == TaskStatus.COMPLETE
        assert work_graph.tasks["ALOVYA-5"].timeline_entries[-1] == timeline_entry
        assert [write_intent.operation_key for write_intent in write_intents] == [
            "update_properties:task:ALOVYA-5",
            "replace:landing_page",
            "update_timeline_log:task:ALOVYA-5:2026-05-25",
        ]


class TestTaskDependencyGraphSnapshot:
    def test_round_trip_preserves_graph_metadata(self, tmp_path):
        snapshot_path = tmp_path / "notion_tasks_graph.json"
        work_graph = _build_recursive_work_graph()
        work_graph.recalculate_display_priorities()

        work_graph.write_snapshot(snapshot_path)
        loaded_work_graph = TaskDependencyGraph.from_snapshot_path(snapshot_path)

        assert loaded_work_graph.to_snapshot() == work_graph.to_snapshot()
        assert loaded_work_graph.tasks["ALOVYA-2"].displayed_priority == Priority.P0

    def test_load_normalizes_fixed_page_titles(self, tmp_path):
        snapshot_path = tmp_path / "notion_tasks_graph.json"
        snapshot = TaskDependencyGraph().to_snapshot()
        snapshot["landing_page"]["title"] = "User-edited landing title"
        snapshot["landing_page"]["notion_page_id"] = "landing-page-id"
        snapshot_path.write_text(json.dumps(snapshot), encoding="utf-8")

        loaded_work_graph = TaskDependencyGraph.from_snapshot_path(snapshot_path)

        assert loaded_work_graph.landing_page.title == LANDING_PAGE_TITLE
        assert loaded_work_graph.landing_page.notion_page_id == "landing-page-id"
