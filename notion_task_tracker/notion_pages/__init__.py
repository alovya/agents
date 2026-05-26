"""Notion page references, block shapes, and write intents."""

from notion_task_tracker.notion_pages.blocks import (
    child_page_block,
    heading_block,
    linked_metadata_bullet_block,
    metadata_bullet_block,
    page_mention_block,
    paragraph_block,
    toggle_block,
)
from notion_task_tracker.notion_pages.external_links import (
    ExternalLink,
    external_link_from_snapshot,
    external_link_to_snapshot,
)
from notion_task_tracker.notion_pages.fixed_pages import (
    COMPLETED_LANDING_PAGE_LOCAL_KEY,
    COMPLETED_LANDING_PAGE_TITLE,
    LANDING_PAGE_LOCAL_KEY,
    LANDING_PAGE_TITLE,
    MISCELLANEOUS_NOTES_PAGE_LOCAL_KEY,
    MISCELLANEOUS_NOTES_PAGE_TITLE,
    SYNTHESIS_NOTES_PAGE_LOCAL_KEY,
    SYNTHESIS_NOTES_PAGE_TITLE,
)
from notion_task_tracker.notion_pages.json_snapshot import write_json_snapshot
from notion_task_tracker.notion_pages.references import (
    NotionPageReference,
    NotionPageRegistry,
    PagePointer,
    canonical_notion_page_id,
    fixed_page_pointer_from_snapshot,
    notion_page_id_from_url,
    notion_page_reference_from_snapshot,
    notion_page_reference_to_snapshot,
    page_pointer_to_snapshot,
    validate_fixed_page_pointer,
)
from notion_task_tracker.notion_pages.write_intents import NotionPlanningError, NotionWriteIntent

__all__ = [
    "COMPLETED_LANDING_PAGE_LOCAL_KEY",
    "COMPLETED_LANDING_PAGE_TITLE",
    "ExternalLink",
    "LANDING_PAGE_LOCAL_KEY",
    "LANDING_PAGE_TITLE",
    "MISCELLANEOUS_NOTES_PAGE_LOCAL_KEY",
    "MISCELLANEOUS_NOTES_PAGE_TITLE",
    "NotionPageReference",
    "NotionPageRegistry",
    "NotionPlanningError",
    "NotionWriteIntent",
    "PagePointer",
    "SYNTHESIS_NOTES_PAGE_LOCAL_KEY",
    "SYNTHESIS_NOTES_PAGE_TITLE",
    "canonical_notion_page_id",
    "child_page_block",
    "external_link_from_snapshot",
    "external_link_to_snapshot",
    "fixed_page_pointer_from_snapshot",
    "heading_block",
    "linked_metadata_bullet_block",
    "metadata_bullet_block",
    "notion_page_id_from_url",
    "notion_page_reference_from_snapshot",
    "notion_page_reference_to_snapshot",
    "page_mention_block",
    "page_pointer_to_snapshot",
    "paragraph_block",
    "toggle_block",
    "validate_fixed_page_pointer",
    "write_json_snapshot",
]
