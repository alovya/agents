"""Plan Notion writes for task graph changes."""

from __future__ import annotations

from collections.abc import Callable

from notion_task_tracker.fixed_pages import (
    COMPLETED_LANDING_PAGE_LOCAL_KEY,
    COMPLETED_LANDING_PAGE_TITLE,
    ONGOING_LANDING_PAGE_LOCAL_KEY,
    ONGOING_LANDING_PAGE_TITLE,
)
from notion_task_tracker.notion_operations.markdown import (
    bullet,
    code_block,
    heading,
    join_markdown_blocks,
    page_mention,
    toggle,
)
from notion_task_tracker.notion_operations.page_registry import NotionPageRegistry
from notion_task_tracker.notion_operations.write_intent import NotionWriteIntent
from notion_task_tracker.tasks.landing_pages import (
    landing_root_task_ids_matching,
    task_should_appear_inside_ongoing_landing_tree,
    top_level_task_ids_matching,
)
from notion_task_tracker.tasks.task import (
    COMPLETED_TASK_PRIORITY_LABEL,
    LANDING_COLOR_BY_PRIORITY,
    LANDING_COLOR_BY_STATUS,
    LANDING_HEADING_BY_PRIORITY,
    TASK_DATABASE_PRIORITY_PROPERTY,
    TASK_DATABASE_STATUS_PROPERTY,
    TASK_DATABASE_TITLE_PROPERTY,
    TASK_PAGE_TIMELINE_LOG_HEADING,
    UPDATE_TIMELINE_LOG_OPERATION_NAME,
    Priority,
    Task,
    TaskCompletionChange,
    TaskStatus,
    TimelineEntry,
    TimelineLogChange,
    task_id_sort_key,
)
from notion_task_tracker.tasks.dependency_graph import TaskDependencyGraph
from notion_task_tracker.tracked_pages import TrackedPage


def build_page_registry_for_task_graph(task_graph: TaskDependencyGraph) -> NotionPageRegistry:
    return NotionPageRegistry.from_tracked_pages(_collect_pages_that_should_exist(task_graph))


def plan_notion_writes_for_task_graph(task_graph: TaskDependencyGraph) -> list[NotionWriteIntent]:
    task_graph.validate()
    task_graph.recalculate_display_priorities()
    page_registry = build_page_registry_for_task_graph(task_graph)
    return [
        *_plan_missing_page_creation_intents(task_graph, page_registry),
        *_plan_fixed_page_title_refresh_intents(task_graph),
        *_plan_existing_task_property_refresh_intents(task_graph),
        build_ongoing_landing_page_refresh_intent(task_graph, page_registry),
        *plan_completed_landing_page_refresh_intents(task_graph, page_registry),
    ]


def build_timeline_log_write_intent(timeline_log_change: TimelineLogChange) -> NotionWriteIntent:
    timeline_entry = timeline_log_change.timeline_entry
    arguments = {
        "task_id": timeline_log_change.task_id,
        "timeline_log_heading": TASK_PAGE_TIMELINE_LOG_HEADING,
        "timeline_entry": timeline_entry.to_tracker_state(),
        "timeline_section_markdown": render_timeline_entry_section_markdown(timeline_entry),
    }
    if timeline_log_change.existing_timeline_entry is not None:
        arguments["existing_timeline_heading"] = timeline_log_change.existing_timeline_entry.heading
        arguments["old_timeline_section_markdown"] = render_timeline_entry_section_markdown(
            timeline_log_change.existing_timeline_entry
        )
        arguments["new_timeline_section_markdown"] = render_timeline_entry_section_markdown(timeline_entry)
        arguments["appended_markdown"] = render_timeline_entry_content_markdown(
            timeline_log_change.appended_timeline_entry
        )

    return NotionWriteIntent(
        operation_key=(
            f"{UPDATE_TIMELINE_LOG_OPERATION_NAME}:task:{timeline_log_change.task_id}:"
            f"{timeline_entry.entry_date}"
        ),
        operation_name=UPDATE_TIMELINE_LOG_OPERATION_NAME,
        target_page_key=f"task:{timeline_log_change.task_id}",
        arguments=arguments,
    )


def plan_completion_write_intents(
    task_graph: TaskDependencyGraph,
    completion_change: TaskCompletionChange,
) -> list[NotionWriteIntent]:
    page_registry = build_page_registry_for_task_graph(task_graph)
    return [
        build_task_database_property_refresh_intent(task_graph.tasks[completion_change.task_id]),
        build_ongoing_landing_page_refresh_intent(task_graph, page_registry),
        *plan_completed_landing_page_refresh_intents(task_graph, page_registry),
        build_timeline_log_write_intent(completion_change.timeline_log_change),
    ]


def build_task_database_property_refresh_intent(task: Task) -> NotionWriteIntent:
    return NotionWriteIntent(
        operation_key=f"update_properties:{task.local_page_key}",
        operation_name="update_page_properties",
        target_page_key=task.local_page_key,
        arguments={
            "properties": {
                TASK_DATABASE_TITLE_PROPERTY: task.page_title(),
                TASK_DATABASE_PRIORITY_PROPERTY: task.configured_priority.value,
                TASK_DATABASE_STATUS_PROPERTY: task.status.value,
            }
        },
    )


def build_ongoing_landing_page_refresh_intent(
    task_graph: TaskDependencyGraph,
    page_registry: NotionPageRegistry,
) -> NotionWriteIntent:
    return NotionWriteIntent(
        operation_key="replace:ongoing_landing_page",
        operation_name="replace_page_markdown",
        target_page_key=task_graph.ongoing_tasks_landing_page.page.local_page_key,
        arguments={"markdown": render_ongoing_landing_page_markdown(task_graph.tasks, page_registry)},
    )


def plan_completed_landing_page_refresh_intents(
    task_graph: TaskDependencyGraph,
    page_registry: NotionPageRegistry,
) -> list[NotionWriteIntent]:
    if task_graph.completed_tasks_landing_page.page.notion_page_id is None:
        return []

    return [
        NotionWriteIntent(
            operation_key="replace:completed_landing_page",
            operation_name="replace_page_markdown",
            target_page_key=task_graph.completed_tasks_landing_page.page.local_page_key,
            arguments={"markdown": render_completed_landing_page_markdown(task_graph.tasks, page_registry)},
        )
    ]


def render_ongoing_landing_page_markdown(
    tasks: dict[str, Task],
    page_registry: NotionPageRegistry,
) -> str:
    markdown_blocks = []
    for priority, task_ids in _group_task_ids_by_priority(tasks).items():
        if task_ids:
            markdown_blocks.append(heading(2, LANDING_HEADING_BY_PRIORITY[priority]))
            for task_id in task_ids:
                markdown_blocks.append(
                    _render_task_tree_markdown(
                        tasks=tasks,
                        task_id=task_id,
                        depth=0,
                        task_should_be_visible=task_should_appear_inside_ongoing_landing_tree,
                        page_registry=page_registry,
                    )
                )
    return join_markdown_blocks(markdown_blocks)


def render_completed_landing_page_markdown(
    tasks: dict[str, Task],
    page_registry: NotionPageRegistry,
) -> str:
    markdown_blocks = []
    _append_completed_status_section(TaskStatus.COMPLETE, "Completed", tasks, markdown_blocks, page_registry)
    _append_completed_status_section(TaskStatus.CANCELLED, "Cancelled", tasks, markdown_blocks, page_registry)
    return join_markdown_blocks(markdown_blocks) or "No completed tasks yet."


def render_timeline_entry_content_markdown(timeline_entry: TimelineEntry) -> str:
    content_markdown = join_markdown_blocks([
        *[_render_timeline_entry_block_markdown(block) for block in timeline_entry.blocks],
        *[bullet(line) for line in timeline_entry.lines],
    ])
    if timeline_entry.subheading:
        return toggle(timeline_entry.subheading, content_markdown)

    return content_markdown


def render_timeline_entry_section_markdown(timeline_entry: TimelineEntry) -> str:
    return join_markdown_blocks([
        heading(3, timeline_entry.heading),
        render_timeline_entry_content_markdown(timeline_entry),
    ])


def _render_timeline_entry_block_markdown(block: dict[str, str]) -> str:
    if block["type"] == "paragraph":
        return block["text"]
    if block["type"] == "code":
        return code_block(block["text"], language=block.get("language", ""))

    raise ValueError(f"Unsupported timeline entry block type {block['type']!r}.")


def _plan_missing_page_creation_intents(
    task_graph: TaskDependencyGraph,
    page_registry: NotionPageRegistry,
) -> list[NotionWriteIntent]:
    write_intents = []
    for page, markdown in [
        (
            task_graph.ongoing_tasks_landing_page.page,
            render_ongoing_landing_page_markdown(task_graph.tasks, page_registry),
        ),
        (
            task_graph.completed_tasks_landing_page.page,
            render_completed_landing_page_markdown(task_graph.tasks, page_registry),
        ),
    ]:
        if page.notion_page_id is None:
            write_intents.append(_build_page_creation_intent(page, markdown))
    return write_intents


def _plan_fixed_page_title_refresh_intents(task_graph: TaskDependencyGraph) -> list[NotionWriteIntent]:
    return [
        _build_page_title_refresh_intent(page)
        for page in [
            task_graph.ongoing_tasks_landing_page.page,
            task_graph.completed_tasks_landing_page.page,
        ]
        if page.notion_page_id is not None
    ]


def _plan_existing_task_property_refresh_intents(task_graph: TaskDependencyGraph) -> list[NotionWriteIntent]:
    return [
        build_task_database_property_refresh_intent(task)
        for task in sorted(task_graph.tasks.values(), key=lambda task: task_id_sort_key(task.task_id))
        if task.notion_page_id is not None
    ]


def _build_page_creation_intent(page: TrackedPage, markdown: str) -> NotionWriteIntent:
    return NotionWriteIntent(
        operation_key=f"create:{page.local_page_key}",
        operation_name="create_page",
        target_page_key=None,
        arguments={
            "local_page_key": page.local_page_key,
            "title": page.title,
            "parent_page_key": page.parent_page_key,
            "markdown": markdown,
        },
    )


def _build_page_title_refresh_intent(page: TrackedPage) -> NotionWriteIntent:
    return NotionWriteIntent(
        operation_key=f"update_properties:{page.local_page_key}",
        operation_name="update_page_properties",
        target_page_key=page.local_page_key,
        arguments={"properties": {"title": page.title}},
    )


def _collect_pages_that_should_exist(task_graph: TaskDependencyGraph) -> list[TrackedPage]:
    pages = [
        task_graph.ongoing_tasks_landing_page.page,
        task_graph.completed_tasks_landing_page.page,
    ]
    for task in task_graph.tasks.values():
        pages.append(
            TrackedPage(
                local_page_key=task.local_page_key,
                title=task.page_title(),
                notion_page_id=task.notion_page_id,
                parent_page_key=None,
            )
        )
    return pages


def _group_task_ids_by_priority(tasks: dict[str, Task]) -> dict[Priority, list[str]]:
    return {
        priority: [
            task_id
            for task_id in landing_root_task_ids_matching(
                tasks,
                lambda task: task.status not in {TaskStatus.COMPLETE, TaskStatus.CANCELLED},
            )
            if tasks[task_id].displayed_priority == priority
        ]
        for priority in Priority
    }


def _append_completed_status_section(
    status: TaskStatus,
    section_title: str,
    tasks: dict[str, Task],
    markdown_blocks: list[str],
    page_registry: NotionPageRegistry,
) -> None:
    task_should_be_visible = lambda task: task.status == status
    task_ids = top_level_task_ids_matching(tasks, task_should_be_visible)
    if task_ids:
        markdown_blocks.append(heading(2, section_title))
        for task_id in task_ids:
            markdown_blocks.append(
                _render_task_tree_markdown(
                    tasks=tasks,
                    task_id=task_id,
                    depth=0,
                    task_should_be_visible=task_should_be_visible,
                    page_registry=page_registry,
                )
            )


def _render_task_tree_markdown(
    tasks: dict[str, Task],
    task_id: str,
    depth: int,
    task_should_be_visible: Callable[[Task], bool],
    page_registry: NotionPageRegistry,
) -> str:
    task = tasks[task_id]
    displayed_priority = task.displayed_priority or task.configured_priority
    lines = [
        bullet(
            text=_format_landing_task_text(task, displayed_priority, page_registry),
            depth=depth,
            colour=_choose_landing_color_for_task(task, displayed_priority),
        )
    ]
    for child_task_id in sorted(task.child_task_ids, key=task_id_sort_key):
        child_task = tasks[child_task_id]
        if task_should_be_visible(child_task):
            lines.append(
                _render_task_tree_markdown(
                    tasks=tasks,
                    task_id=child_task_id,
                    depth=depth + 1,
                    task_should_be_visible=task_should_be_visible,
                    page_registry=page_registry,
                )
            )
    return join_markdown_blocks(lines)


def _format_landing_task_text(
    task: Task,
    displayed_priority: Priority,
    page_registry: NotionPageRegistry,
) -> str:
    priority_label = _format_priority_label_for_task(task, displayed_priority)
    return f"[{priority_label}] {page_mention(task.local_page_key, page_registry)}: {task.status.value}"


def _choose_landing_color_for_task(task: Task, displayed_priority: Priority) -> str:
    return LANDING_COLOR_BY_STATUS.get(
        task.status,
        LANDING_COLOR_BY_PRIORITY[displayed_priority],
    )


def _format_priority_label_for_task(task: Task, displayed_priority: Priority) -> str:
    if task.status in {TaskStatus.COMPLETE, TaskStatus.CANCELLED}:
        return COMPLETED_TASK_PRIORITY_LABEL

    return displayed_priority.value
