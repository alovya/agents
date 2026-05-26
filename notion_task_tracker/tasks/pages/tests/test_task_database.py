from __future__ import annotations

import pytest

from notion_task_tracker.common import COMPLETED_LANDING_PAGE_TITLE, LANDING_PAGE_TITLE, PagePointer
from notion_task_tracker.tasks.pages import Priority, TaskDependencyGraph, TaskPageMetadata, TaskStatus
from notion_task_tracker.tasks.pages.task_database import (
    TASK_DATABASE_DATA_SOURCE_URL,
    TASK_DATABASE_VIEW_URL,
    default_task_database_tracker_state,
    task_database_data_source_url_from_tracker_state,
    task_database_query_for_tracker_state,
    task_database_view_url_from_tracker_state,
    task_dependency_graph_from_database_query_results,
    task_id_from_fetched_task_database_page,
)


class TestTaskDependencyGraphFromDatabaseQueryResults:
    def test_builds_graph_from_ticket_ids_and_parent_relations(self):
        previous_work_graph = TaskDependencyGraph()
        previous_work_graph.add_task(
            TaskPageMetadata(
                task_id="ALOVYA-1",
                title="Old root title",
                configured_priority=Priority.P1,
                status=TaskStatus.ACTIVE,
                status_update="Keep local status detail.",
                notion_page_id="11111111111111111111111111111111",
            )
        )

        work_graph = task_dependency_graph_from_database_query_results(
            query_results=[
                {
                    "Ticket page": "ALOVYA-1: Root task",
                    "Ticket ID": "68",
                    "Priority": "P1",
                    "Status": "Active",
                    "Parent": "[]",
                    "url": "https://www.notion.so/11111111111111111111111111111111",
                },
                {
                    "Ticket page": "ALOVYA-2: Child task",
                    "Ticket ID": "69",
                    "Priority": "P2",
                    "Status": "Blocked",
                    "Parent": '["https://www.notion.so/11111111111111111111111111111111"]',
                    "url": "https://www.notion.so/22222222222222222222222222222222",
                },
            ],
            landing_page=PagePointer(
                local_page_key="landing_page",
                title=LANDING_PAGE_TITLE,
                notion_page_id="landing-page-id",
            ),
            previous_work_graph=previous_work_graph,
        )

        assert work_graph.tasks["ALOVYA-68"].title == "Root task"
        assert work_graph.tasks["ALOVYA-68"].status_update == "Keep local status detail."
        assert work_graph.tasks["ALOVYA-68"].child_task_ids == ["ALOVYA-69"]
        assert work_graph.tasks["ALOVYA-69"].parent_task_id == "ALOVYA-68"
        assert work_graph.tasks["ALOVYA-69"].configured_priority == Priority.P2
        assert work_graph.tasks["ALOVYA-69"].status == TaskStatus.BLOCKED

    def test_preserves_completed_landing_page_from_previous_graph(self):
        previous_work_graph = TaskDependencyGraph()
        previous_work_graph.completed_landing_page.notion_page_id = "completed-landing-page-id"

        work_graph = task_dependency_graph_from_database_query_results(
            query_results=[],
            landing_page=PagePointer(
                local_page_key="landing_page",
                title=LANDING_PAGE_TITLE,
                notion_page_id="landing-page-id",
            ),
            previous_work_graph=previous_work_graph,
        )

        assert work_graph.completed_landing_page.title == COMPLETED_LANDING_PAGE_TITLE
        assert work_graph.completed_landing_page.notion_page_id == "completed-landing-page-id"

    def test_uses_notion_ticket_id_for_task_id(self):
        work_graph = task_dependency_graph_from_database_query_results(
            query_results=[
                {
                    "Ticket page": "New database-native task",
                    "Ticket ID": "70",
                    "Priority": "P1",
                    "Status": "Active",
                    "url": "https://www.notion.so/33333333333333333333333333333333",
                },
            ],
            landing_page=PagePointer(
                local_page_key="landing_page",
                title=LANDING_PAGE_TITLE,
                notion_page_id="landing-page-id",
            ),
        )

        assert list(work_graph.tasks) == ["ALOVYA-70"]
        assert work_graph.tasks["ALOVYA-70"].title == "New database-native task"

    def test_accepts_slugged_notion_urls(self):
        work_graph = task_dependency_graph_from_database_query_results(
            query_results=[
                {
                    "Ticket page": "Root task",
                    "Ticket ID": "1",
                    "Priority": "P1",
                    "Status": "Active",
                    "Parent": "[]",
                    "url": "https://www.notion.so/Root-task-22222222222222222222222222222222",
                },
            ],
            landing_page=PagePointer(
                local_page_key="landing_page",
                title=LANDING_PAGE_TITLE,
                notion_page_id="landing-page-id",
            ),
        )

        assert work_graph.tasks["ALOVYA-1"].notion_page_id == "22222222222222222222222222222222"

    def test_reads_completed_struckthrough_title_as_plain_task_title(self):
        work_graph = task_dependency_graph_from_database_query_results(
            query_results=[
                {
                    "Ticket page": (
                        "A\u0336L\u0336O\u0336V\u0336Y\u0336A\u0336-\u03362\u0336:\u0336 \u0336"
                        "A\u0336L\u0336O\u0336V\u0336Y\u0336A\u0336-\u03362\u0336:\u0336 \u0336Finished task"
                    ),
                    "Ticket ID": "68",
                    "Priority": "P3",
                    "Status": "Complete",
                    "url": "https://www.notion.so/11111111111111111111111111111111",
                },
            ],
            landing_page=PagePointer(
                local_page_key="landing_page",
                title=LANDING_PAGE_TITLE,
                notion_page_id="landing-page-id",
            ),
        )

        assert work_graph.tasks["ALOVYA-68"].title == "Finished task"

    def test_sorts_child_relations_by_task_number(self):
        work_graph = task_dependency_graph_from_database_query_results(
            query_results=[
                {
                    "Ticket page": "ALOVYA-1: Root task",
                    "Ticket ID": "68",
                    "Priority": "P1",
                    "Status": "Active",
                    "url": "https://www.notion.so/11111111111111111111111111111111",
                },
                {
                    "Ticket page": "ALOVYA-10: Later child",
                    "Ticket ID": "70",
                    "Priority": "P1",
                    "Status": "Active",
                    "Parent": '["https://www.notion.so/11111111111111111111111111111111"]',
                    "url": "https://www.notion.so/33333333333333333333333333333333",
                },
                {
                    "Ticket page": "ALOVYA-2: Earlier child",
                    "Ticket ID": "69",
                    "Priority": "P1",
                    "Status": "Active",
                    "Parent": '["https://www.notion.so/11111111111111111111111111111111"]',
                    "url": "https://www.notion.so/22222222222222222222222222222222",
                },
            ],
            landing_page=PagePointer(
                local_page_key="landing_page",
                title=LANDING_PAGE_TITLE,
                notion_page_id="landing-page-id",
            ),
        )

        assert work_graph.tasks["ALOVYA-68"].child_task_ids == ["ALOVYA-69", "ALOVYA-70"]

    def test_skips_rows_that_point_to_unknown_parent_rows(self):
        work_graph = task_dependency_graph_from_database_query_results(
            query_results=[
                {
                    "Ticket page": "ALOVYA-2: Child task",
                    "Ticket ID": "69",
                    "Priority": "P2",
                    "Status": "Blocked",
                    "Parent": '["https://www.notion.so/11111111111111111111111111111111"]',
                    "url": "https://www.notion.so/22222222222222222222222222222222",
                },
            ],
            landing_page=PagePointer(
                local_page_key="landing_page",
                title=LANDING_PAGE_TITLE,
                notion_page_id="landing-page-id",
            )
        )

        assert work_graph.tasks == {}

    def test_skips_orphan_subtrees(self):
        work_graph = task_dependency_graph_from_database_query_results(
            query_results=[
                {
                    "Ticket page": "Parent prototype",
                    "Ticket ID": "15",
                    "Priority": "P1",
                    "Status": "Active",
                    "Parent": '["https://www.notion.so/11111111111111111111111111111111"]',
                    "url": "https://www.notion.so/22222222222222222222222222222222",
                },
                {
                    "Ticket page": "Child prototype",
                    "Ticket ID": "16",
                    "Priority": "P1",
                    "Status": "Active",
                    "Parent": '["https://www.notion.so/22222222222222222222222222222222"]',
                    "url": "https://www.notion.so/33333333333333333333333333333333",
                },
            ],
            landing_page=PagePointer(
                local_page_key="landing_page",
                title=LANDING_PAGE_TITLE,
                notion_page_id="landing-page-id",
            )
        )

        assert work_graph.tasks == {}

    def test_rejects_duplicate_task_ids(self):
        with pytest.raises(ValueError, match="Duplicate task id ALOVYA-68"):
            task_dependency_graph_from_database_query_results(
                query_results=[
                    {
                        "Ticket page": "ALOVYA-1: First task",
                        "Ticket ID": "68",
                        "Priority": "P1",
                        "Status": "Active",
                        "url": "https://www.notion.so/11111111111111111111111111111111",
                    },
                    {
                        "Ticket page": "ALOVYA-1: Duplicate task",
                        "Ticket ID": "68",
                        "Priority": "P2",
                        "Status": "Active",
                        "url": "https://www.notion.so/22222222222222222222222222222222",
                    },
                ],
                landing_page=PagePointer(
                    local_page_key="landing_page",
                    title=LANDING_PAGE_TITLE,
                    notion_page_id="landing-page-id",
                ),
            )


class TestTaskDatabaseTrackerState:
    def test_defaults_to_task_property_filtered_query(self):
        tracker_state = default_task_database_tracker_state()

        assert task_database_data_source_url_from_tracker_state(tracker_state={"task_database": tracker_state}) == (
            TASK_DATABASE_DATA_SOURCE_URL
        )
        assert task_database_view_url_from_tracker_state(tracker_state={"task_database": tracker_state}) == (
            TASK_DATABASE_VIEW_URL
        )
        assert task_database_query_for_tracker_state({"task_database": tracker_state}) == (
            f'SELECT * FROM "{TASK_DATABASE_DATA_SOURCE_URL}" '
            'WHERE "Priority" IS NOT NULL AND "Status" IS NOT NULL'
        )


class TestTaskIdFromFetchedTaskDatabasePage:
    def test_reads_notion_assigned_ticket_id_from_properties(self):
        task_id = task_id_from_fetched_task_database_page(
            "\n".join(
                [
                    "<page>",
                    "<properties>",
                    '{"Ticket ID":"72","Ticket page":"Fresh task"}',
                    "</properties>",
                    "</page>",
                ]
            )
        )

        assert task_id == "ALOVYA-72"
