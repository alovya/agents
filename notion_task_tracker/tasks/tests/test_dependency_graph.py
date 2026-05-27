from __future__ import annotations

import pytest

from notion_task_tracker import COMPLETED_LANDING_PAGE_TITLE, ONGOING_LANDING_PAGE_TITLE
from notion_task_tracker.notion_operations.plan_task_page_write_intents import (
    plan_completion_write_intents,
    plan_notion_writes_for_task_graph,
    build_timeline_log_write_intent,
)
from notion_task_tracker.tasks import (
    Priority,
    TaskDependencyGraph,
    Task,
    TaskStatus,
    TimelineEntry,
)
from notion_task_tracker.tasks.tests.helpers import (
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
            Task(
                task_id="ALOVYA-1",
                title="Root",
                configured_priority=Priority.P1,
                status=TaskStatus.ACTIVE,
                parent_task_id="ALOVYA-2",
                child_task_ids=["ALOVYA-2"],
            )
        )
        work_graph.add_task(
            Task(
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
        work_graph = TaskDependencyGraph.from_tracker_state(
            {
                "ongoing_landing_page": {
                    "local_page_key": "ongoing_landing_page",
                    "title": ONGOING_LANDING_PAGE_TITLE,
                    "notion_page_id": "11111111111111111111111111111111",
                    "parent_page_key": None,
                },
                "completed_landing_page": None,
                "tasks": {},
            }
        )

        assert work_graph.completed_tasks_landing_page.page.title == COMPLETED_LANDING_PAGE_TITLE
        assert work_graph.completed_tasks_landing_page.page.notion_page_id is None


class TestTaskDependencyGraphTaskIdsGroupedForLandingPage:
    def test_groups_live_top_level_tasks_by_displayed_priority(self):
        work_graph = _build_recursive_work_graph()
        work_graph.add_task(
            Task(
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
            Task(
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
            Task(
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

        write_intents = plan_notion_writes_for_task_graph(work_graph)

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
            "create:ongoing_landing_page",
            "create:completed_landing_page",
            "replace:ongoing_landing_page",
            "update_properties:task:ALOVYA-2",
            "update_properties:task:ALOVYA-4",
        }

    def test_renders_landing_page_trees_from_database_graph(self):
        work_graph = _build_recursive_work_graph()

        landing_refresh_intent = next(
            write_intent
            for write_intent in plan_notion_writes_for_task_graph(work_graph)
            if write_intent.operation_key == "replace:ongoing_landing_page"
        )

        landing_markdown = landing_refresh_intent.arguments["markdown"]

        assert "## P0 (high impact and urgent)" in landing_markdown
        assert '- [P0] <mention-page url="https://www.notion.so/22222222222222222222222222222222"/>: Active {color="red"}' in landing_markdown
        assert '\t- [P0] <mention-page url="https://www.notion.so/33333333333333333333333333333333"/>: Active {color="red"}' in landing_markdown
        assert '\t\t- [P0] <mention-page url="https://www.notion.so/55555555555555555555555555555555"/>: Blocked {color="red"}' in landing_markdown
        assert '\t- [N/A] <mention-page url="https://www.notion.so/44444444444444444444444444444444"/>: Complete {color="green"}' in landing_markdown

    def test_renders_completed_page_from_completed_top_level_tasks_only(self):
        work_graph = _build_recursive_work_graph()
        work_graph.completed_tasks_landing_page.page.notion_page_id = "completed-landing-page-id"

        completed_landing_refresh_intent = next(
            write_intent
            for write_intent in plan_notion_writes_for_task_graph(work_graph)
            if write_intent.operation_key == "replace:completed_landing_page"
        )

        assert completed_landing_refresh_intent.arguments["markdown"] == "No completed tasks yet."

    def test_completed_task_page_title_strikes_through_and_properties_include_database_metadata(self):
        work_graph = _build_recursive_work_graph()

        title_refresh_intent = next(
            write_intent
            for write_intent in plan_notion_writes_for_task_graph(work_graph)
            if write_intent.operation_key == "update_properties:task:ALOVYA-4"
        )

        assert title_refresh_intent.arguments["properties"] == {
            "Priority": "P3",
            "Status": "Complete",
            "Ticket page": _visible_strikethrough_text("Complete calibration branch"),
        }


class TestTaskDependencyGraphRepairOperationKeysForChanges:
    def test_includes_changed_tasks_ancestors_and_landing_pages(self):
        work_graph = TaskDependencyGraph()
        work_graph.add_task(
            Task(
                task_id="ALOVYA-1",
                title="Root",
                configured_priority=Priority.P1,
                status=TaskStatus.ACTIVE,
            )
        )
        work_graph.add_task(
            Task(
                task_id="ALOVYA-2",
                title="Child",
                configured_priority=Priority.P1,
                status=TaskStatus.ACTIVE,
            )
        )
        work_graph.add_task(
            Task(
                task_id="ALOVYA-3",
                title="Grandchild",
                configured_priority=Priority.P2,
                status=TaskStatus.ACTIVE,
            )
        )
        work_graph.link_parent_to_child("ALOVYA-1", "ALOVYA-2")
        work_graph.link_parent_to_child("ALOVYA-2", "ALOVYA-3")

        operation_keys = work_graph.repair_operation_keys_for_changes(
            [
                {
                    "task_id": "ALOVYA-3",
                    "fields": {
                        "configured_priority": {
                            "before": "P2",
                            "after": "P1",
                        }
                    },
                }
            ]
        )

        assert operation_keys == [
            "replace:ongoing_landing_page",
            "replace:completed_landing_page",
            "update_properties:task:ALOVYA-1",
            "update_properties:task:ALOVYA-2",
            "update_properties:task:ALOVYA-3",
        ]


class TestTaskDependencyGraphAppendTaskTimelineLog:
    def test_returns_single_timeline_update_intent(self):
        work_graph = _build_recursive_work_graph()
        timeline_entry = TimelineEntry(
            entry_date="2026-05-25",
            heading='<mention-date start="2026-05-25"/>',
            lines=["Tested the mismatch fix and found one remaining failing node."],
        )

        timeline_log_change = work_graph.append_task_timeline_log(
            task_id="ALOVYA-5",
            timeline_entry=timeline_entry,
        )
        write_intent = build_timeline_log_write_intent(timeline_log_change)

        assert work_graph.tasks["ALOVYA-5"].timeline_entries[-1] == timeline_entry
        assert write_intent.operation_name == "update_timeline_log"
        assert write_intent.target_page_key == "task:ALOVYA-5"
        assert write_intent.arguments["task_id"] == "ALOVYA-5"
        assert write_intent.arguments["timeline_log_heading"] == "Timeline log"
        assert write_intent.arguments["timeline_entry"]["entry_date"] == "2026-05-25"
        assert '### <mention-date start="2026-05-25"/>' in write_intent.arguments["timeline_section_markdown"]
        assert "old_timeline_section_markdown" not in write_intent.arguments

    def test_appends_lines_to_existing_timeline_entry_for_same_date(self):
        work_graph = _build_recursive_work_graph()
        work_graph.tasks["ALOVYA-5"].timeline_entries.append(
            TimelineEntry(
                entry_date="2026-05-25",
                heading='<mention-date start="2026-05-25"/>',
                lines=["Started debugging the repair path."],
            )
        )

        timeline_log_change = work_graph.append_task_timeline_log(
            task_id="ALOVYA-5",
            timeline_entry=TimelineEntry(
                entry_date="2026-05-25",
                heading='<mention-date start="2026-05-25"/>',
                lines=["Found the stale REST request."],
            ),
        )
        write_intent = build_timeline_log_write_intent(timeline_log_change)

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
        assert write_intent.arguments["appended_markdown"] == "- Found the stale REST request."
        assert write_intent.arguments["new_timeline_section_markdown"] == "\n".join([
            '### <mention-date start="2026-05-25"/>',
            "- Started debugging the repair path.",
            "- Found the stale REST request.",
        ])

    def test_appends_subheaded_lines_as_toggle_content(self):
        work_graph = _build_recursive_work_graph()
        work_graph.tasks["ALOVYA-5"].timeline_entries.append(
            TimelineEntry(
                entry_date="2026-05-25",
                heading='<mention-date start="2026-05-25"/>',
            )
        )

        timeline_log_change = work_graph.append_task_timeline_log(
            task_id="ALOVYA-5",
            timeline_entry=TimelineEntry(
                entry_date="2026-05-25",
                heading='<mention-date start="2026-05-25"/>',
                subheading="Design notes",
                lines=["Moved task metadata into the database."],
            ),
        )
        write_intent = build_timeline_log_write_intent(timeline_log_change)

        assert write_intent.arguments["appended_markdown"] == "\n".join([
            "<details>",
            "<summary>Design notes</summary>",
            "\t- Moved task metadata into the database.",
            "</details>",
        ])

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

        completion_change = work_graph.complete_task(
            task_id="ALOVYA-5",
            timeline_entry=timeline_entry,
        )
        write_intents = plan_completion_write_intents(work_graph, completion_change)

        assert work_graph.tasks["ALOVYA-5"].status == TaskStatus.COMPLETE
        assert work_graph.tasks["ALOVYA-5"].timeline_entries[-1] == timeline_entry
        assert [write_intent.operation_key for write_intent in write_intents] == [
            "update_properties:task:ALOVYA-5",
            "replace:ongoing_landing_page",
            "update_timeline_log:task:ALOVYA-5:2026-05-25",
        ]


class TestTaskDependencyGraphFromTrackerState:
    def test_normalizes_fixed_page_titles(self):
        tracker_state = TaskDependencyGraph().to_tracker_state()
        tracker_state["ongoing_landing_page"]["title"] = "User-edited landing title"
        tracker_state["ongoing_landing_page"]["notion_page_id"] = "landing-page-id"

        loaded_work_graph = TaskDependencyGraph.from_tracker_state(tracker_state)

        assert loaded_work_graph.ongoing_tasks_landing_page.page.title == ONGOING_LANDING_PAGE_TITLE
        assert loaded_work_graph.ongoing_tasks_landing_page.page.notion_page_id == "landing-page-id"
