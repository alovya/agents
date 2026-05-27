"""Validate and normalise Notion page identifiers stored by the tracker."""

from __future__ import annotations

import re
from urllib.parse import urlparse

from notion_task_tracker.errors import NotionPlanningError


_COMPACT_NOTION_PAGE_ID_PATTERN = re.compile(r"^[0-9a-f]{32}$")
_TRAILING_NOTION_PAGE_ID_PATTERN = re.compile(r"([0-9a-fA-F]{32})$")


def canonical_notion_page_id(notion_page_id: str) -> str:
    compact_page_id = notion_page_id.replace("-", "").lower()

    if not _COMPACT_NOTION_PAGE_ID_PATTERN.fullmatch(compact_page_id):
        raise NotionPlanningError(f"Invalid Notion page id {notion_page_id!r}")

    return compact_page_id


def notion_page_id_from_url(notion_url: str) -> str:
    parsed_url = urlparse(notion_url)
    final_path_part = parsed_url.path.rstrip("/").rsplit("/", 1)[-1].replace("-", "")
    page_id_match = _TRAILING_NOTION_PAGE_ID_PATTERN.search(final_path_part)

    if page_id_match is None:
        raise NotionPlanningError(f"Notion URL {notion_url!r} does not contain a page id")

    return canonical_notion_page_id(page_id_match.group(1))
