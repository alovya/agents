"""Notion read/write boundary for the tracker."""

from notion_task_tracker.notion_io.client import (
    CreatedTaskDatabasePage,
    NotionClient,
    NotionWriteExecutionResult,
    notion_client_from_credentials_path,
)
from notion_task_tracker.notion_io.page_registry import (
    NotionPageReference,
    NotionPageRegistry,
    PagePointer,
    canonical_notion_page_id,
    fixed_page_pointer_from_tracker_state,
    notion_page_id_from_url,
    page_pointer_to_tracker_state,
    validate_fixed_page_pointer,
)
from notion_task_tracker.notion_io.writes import (
    NotionPlanningError,
    NotionWriteIntent,
)

__all__ = [
    "CreatedTaskDatabasePage",
    "NotionClient",
    "NotionPageReference",
    "NotionPageRegistry",
    "NotionPlanningError",
    "NotionWriteExecutionResult",
    "NotionWriteIntent",
    "PagePointer",
    "canonical_notion_page_id",
    "fixed_page_pointer_from_tracker_state",
    "notion_client_from_credentials_path",
    "notion_page_id_from_url",
    "page_pointer_to_tracker_state",
    "validate_fixed_page_pointer",
]
