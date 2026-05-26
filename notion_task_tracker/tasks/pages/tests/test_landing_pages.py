from notion_task_tracker.notion_pages import PagePointer
from notion_task_tracker.tasks import Priority, Task, TaskStatus
from notion_task_tracker.tasks.pages.landing_pages import CompletedTasksLandingPage, OngoingTasksLandingPage


def test_ongoing_tasks_landing_page_renders_priority_sections_and_child_depth():
    tasks = {
        "ALOVYA-1": Task(
            task_id="ALOVYA-1",
            title="Root",
            configured_priority=Priority.P1,
            displayed_priority=Priority.P1,
            status=TaskStatus.ACTIVE,
            child_task_ids=["ALOVYA-2"],
        ),
        "ALOVYA-2": Task(
            task_id="ALOVYA-2",
            title="Child",
            configured_priority=Priority.P1,
            displayed_priority=Priority.P1,
            status=TaskStatus.COMPLETE,
            parent_task_id="ALOVYA-1",
        ),
    }

    blocks = OngoingTasksLandingPage(PagePointer("landing_page", "Landing")).render_blocks(tasks)

    assert blocks == [
        {"type": "heading_2", "text": "P1 (high impact)"},
        {
            "type": "bulleted_list_item",
            "depth": 0,
            "text": "[P1] Root: Active",
            "page_key": "task:ALOVYA-1",
            "color": "orange",
        },
        {
            "type": "bulleted_list_item",
            "depth": 1,
            "text": "[N/A] Child: Complete",
            "page_key": "task:ALOVYA-2",
            "color": "green",
        },
    ]


def test_completed_tasks_landing_page_only_starts_from_completed_top_level_tasks():
    tasks = {
        "ALOVYA-1": Task(
            task_id="ALOVYA-1",
            title="Ongoing root",
            configured_priority=Priority.P1,
            displayed_priority=Priority.P1,
            status=TaskStatus.ACTIVE,
            child_task_ids=["ALOVYA-2"],
        ),
        "ALOVYA-2": Task(
            task_id="ALOVYA-2",
            title="Completed child",
            configured_priority=Priority.P1,
            displayed_priority=Priority.P1,
            status=TaskStatus.COMPLETE,
            parent_task_id="ALOVYA-1",
        ),
    }

    blocks = CompletedTasksLandingPage(PagePointer("completed_landing_page", "Completed")).render_blocks(tasks)

    assert blocks == [{"type": "paragraph", "text": "No completed tasks yet."}]
