"""Task-specific Notion page shapes and parsers."""

from notion_task_tracker.tasks.pages.landing_pages import CompletedTasksLandingPage, OngoingTasksLandingPage
from notion_task_tracker.tasks.pages.timeline_log import (
    body_content_to_subsume_under_initial_timeline_date,
    fetched_task_page_has_usable_timeline_log,
    initialised_task_timeline_markdown,
    timeline_entries_from_fetched_task_page_content,
    timeline_entry_for_date,
)

__all__ = [
    "CompletedTasksLandingPage",
    "OngoingTasksLandingPage",
    "body_content_to_subsume_under_initial_timeline_date",
    "fetched_task_page_has_usable_timeline_log",
    "initialised_task_timeline_markdown",
    "timeline_entries_from_fetched_task_page_content",
    "timeline_entry_for_date",
]
