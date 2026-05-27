import json

from notion_task_tracker.tasks import Priority, Task, TaskDependencyGraph, TaskStatus


def build_tracker_state_with_root_task() -> dict:
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


def build_tracker_state_with_root_and_child_task() -> dict:
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
    work_graph.add_task(
        Task(
            task_id="ALOVYA-2",
            title="Child task",
            configured_priority=Priority.P1,
            status=TaskStatus.ACTIVE,
            notion_page_id="33333333333333333333333333333333",
        )
    )
    work_graph.link_parent_to_child(parent_task_id="ALOVYA-1", child_task_id="ALOVYA-2")
    return work_graph.to_tracker_state()


def build_fetched_task_page(
    ticket_id: str,
    title: str,
    priority: str,
    status: str,
    parent_urls: list[str],
) -> str:
    return "\n".join(
        [
            "<page>",
            "<properties>",
            json.dumps(
                {
                    "Ticket ID": ticket_id,
                    "Ticket page": title,
                    "Priority": priority,
                    "Status": status,
                    "Parent": json.dumps(parent_urls),
                }
            ),
            "</properties>",
            "<content>",
            "## Timeline log",
            "</content>",
            "</page>",
        ]
    )
