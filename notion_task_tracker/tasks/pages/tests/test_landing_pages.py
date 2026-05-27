from notion_task_tracker import PagePointer
from notion_task_tracker.page_registry import NotionPageRegistry
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
            notion_page_id="11111111111111111111111111111111",
        ),
        "ALOVYA-2": Task(
            task_id="ALOVYA-2",
            title="Child",
            configured_priority=Priority.P1,
            displayed_priority=Priority.P1,
            status=TaskStatus.COMPLETE,
            parent_task_id="ALOVYA-1",
            notion_page_id="22222222222222222222222222222222",
        ),
    }

    markdown = OngoingTasksLandingPage(PagePointer("landing_page", "Landing")).render_markdown(
        tasks,
        NotionPageRegistry.from_page_pointers([
            PagePointer("task:ALOVYA-1", "Root", "11111111111111111111111111111111"),
            PagePointer("task:ALOVYA-2", "Child", "22222222222222222222222222222222"),
        ]),
    )

    assert markdown == "\n".join([
        "## P1 (high impact)",
        '- [P1] <mention-page url="https://www.notion.so/11111111111111111111111111111111"/>: Active {color="orange"}',
        '\t- [N/A] <mention-page url="https://www.notion.so/22222222222222222222222222222222"/>: Complete {color="green"}',
    ])


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

    markdown = CompletedTasksLandingPage(PagePointer("completed_landing_page", "Completed")).render_markdown(
        tasks,
        NotionPageRegistry(pages={}),
    )

    assert markdown == "No completed tasks yet."
