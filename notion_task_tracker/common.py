"""Shared metadata primitives for Notion page planning."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlparse


LANDING_PAGE_LOCAL_KEY = "landing_page"
COMPLETED_LANDING_PAGE_LOCAL_KEY = "completed_landing_page"
MISCELLANEOUS_NOTES_PAGE_LOCAL_KEY = "miscellaneous_notes"
SYNTHESIS_NOTES_PAGE_LOCAL_KEY = "synthesis_notes"

LANDING_PAGE_TITLE = "Alovya's ongoing tasks landing page"
COMPLETED_LANDING_PAGE_TITLE = "Alovya's completed tasks landing page"
MISCELLANEOUS_NOTES_PAGE_TITLE = "Alovya's miscellanous notes"
SYNTHESIS_NOTES_PAGE_TITLE = "Alovya's synthesis notes"

_COMPACT_NOTION_PAGE_ID_PATTERN = re.compile(r"^[0-9a-f]{32}$")
_TRAILING_NOTION_PAGE_ID_PATTERN = re.compile(r"([0-9a-fA-F]{32})$")


@dataclass
class PagePointer:
    """Stable reference to a Notion page."""

    local_page_key: str
    title: str
    notion_page_id: str | None = None
    parent_page_key: str | None = None


@dataclass(frozen=True)
class NotionPageReference:
    """Resolved or expected Notion page address."""

    local_page_key: str
    title: str
    notion_page_id: str | None = None
    notion_url: str | None = None
    parent_page_key: str | None = None

    def resolved_notion_url(self) -> str:
        if self.notion_url:
            return self.notion_url

        if self.notion_page_id:
            return f"https://www.notion.so/{self.notion_page_id.replace('-', '')}"

        raise NotionPlanningError(f"Page {self.local_page_key!r} has no Notion URL or page id")


@dataclass
class NotionPageRegistry:
    """Local page-key lookup used while rendering Notion calls."""

    pages: dict[str, NotionPageReference]

    @classmethod
    def from_page_pointers(cls, page_pointers: list[PagePointer]) -> "NotionPageRegistry":
        return cls(
            pages={
                page.local_page_key: NotionPageReference(
                    local_page_key=page.local_page_key,
                    title=page.title,
                    notion_page_id=page.notion_page_id,
                    parent_page_key=page.parent_page_key,
                )
                for page in page_pointers
            }
        )

    @classmethod
    def from_snapshot(cls, snapshot: dict[str, Any]) -> "NotionPageRegistry":
        return cls(
            pages={
                local_page_key: notion_page_reference_from_snapshot(reference_snapshot)
                for local_page_key, reference_snapshot in snapshot.items()
            }
        )

    def page_reference(self, local_page_key: str) -> NotionPageReference:
        try:
            return self.pages[local_page_key]
        except KeyError as error:
            raise NotionPlanningError(f"Page {local_page_key!r} is not registered") from error

    def page_id(self, local_page_key: str) -> str:
        page = self.page_reference(local_page_key)

        if page.notion_page_id is None:
            raise NotionPlanningError(f"Page {local_page_key!r} has no Notion page id")

        return page.notion_page_id

    def page_url(self, local_page_key: str) -> str:
        return self.page_reference(local_page_key).resolved_notion_url()

    def page_title(self, local_page_key: str) -> str:
        return self.page_reference(local_page_key).title

    def with_page_id(
        self,
        local_page_key: str,
        notion_page_id: str,
        notion_url: str | None = None,
    ) -> "NotionPageRegistry":
        page = self.page_reference(local_page_key)
        updated_page = NotionPageReference(
            local_page_key=page.local_page_key,
            title=page.title,
            notion_page_id=notion_page_id,
            notion_url=notion_url,
            parent_page_key=page.parent_page_key,
        )
        return NotionPageRegistry(pages={**self.pages, local_page_key: updated_page})

    def to_snapshot(self) -> dict[str, Any]:
        return {
            local_page_key: notion_page_reference_to_snapshot(page)
            for local_page_key, page in sorted(self.pages.items())
        }


@dataclass
class ExternalLink:
    """Link from an internal page to an external artefact."""

    label: str
    external_url: str


@dataclass(frozen=True)
class NotionWriteIntent:
    """Notion write planner input."""

    operation_key: str
    operation_name: str
    target_page_key: str | None
    arguments: dict[str, Any]


class NotionPlanningError(ValueError):
    """Raised when a write intent cannot become an exact Notion call."""


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


def heading_block(level: int, text: str) -> dict[str, Any]:
    return {
        "type": f"heading_{level}",
        "text": text,
    }


def paragraph_block(text: str) -> dict[str, Any]:
    return {
        "type": "paragraph",
        "text": text,
    }


def toggle_block(text: str, children: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "type": "toggle",
        "text": text,
        "children": children,
    }


def metadata_bullet_block(text: str) -> dict[str, Any]:
    return {
        "type": "bulleted_list_item",
        "depth": 0,
        "text": text,
    }


def linked_metadata_bullet_block(text: str, page_key: str) -> dict[str, Any]:
    return {
        "type": "bulleted_list_item",
        "depth": 0,
        "text": text,
        "page_key": page_key,
    }


def page_mention_block(page_key: str) -> dict[str, Any]:
    return {
        "type": "page_mention",
        "page_key": page_key,
    }


def child_page_block(page_key: str) -> dict[str, Any]:
    return {
        "type": "child_page",
        "page_key": page_key,
    }


def page_pointer_to_snapshot(page: PagePointer) -> dict[str, Any]:
    return {
        "local_page_key": page.local_page_key,
        "title": page.title,
        "notion_page_id": page.notion_page_id,
        "parent_page_key": page.parent_page_key,
    }


def notion_page_reference_to_snapshot(page: NotionPageReference) -> dict[str, Any]:
    return {
        "local_page_key": page.local_page_key,
        "title": page.title,
        "notion_page_id": page.notion_page_id,
        "notion_url": page.notion_url,
        "parent_page_key": page.parent_page_key,
    }


def notion_page_reference_from_snapshot(snapshot: dict[str, Any]) -> NotionPageReference:
    return NotionPageReference(
        local_page_key=snapshot["local_page_key"],
        title=snapshot["title"],
        notion_page_id=snapshot.get("notion_page_id"),
        notion_url=snapshot.get("notion_url"),
        parent_page_key=snapshot.get("parent_page_key"),
    )


def write_json_snapshot(snapshot: dict[str, Any], snapshot_path: str | Path) -> None:
    destination_path = Path(snapshot_path)
    destination_path.write_text(
        json.dumps(snapshot, indent=2, sort_keys=True),
        encoding="utf-8",
    )


def fixed_page_pointer_from_snapshot(
    snapshot: dict[str, Any],
    local_page_key: str,
    title: str,
) -> PagePointer:
    return PagePointer(
        local_page_key=local_page_key,
        title=title,
        notion_page_id=snapshot.get("notion_page_id"),
        parent_page_key=snapshot.get("parent_page_key"),
    )


def validate_fixed_page_pointer(
    page: PagePointer,
    expected_local_page_key: str,
    expected_title: str,
) -> None:
    if page.local_page_key != expected_local_page_key:
        raise ValueError(
            f"Fixed page key {page.local_page_key!r} should be {expected_local_page_key!r}"
        )

    if page.title != expected_title:
        raise ValueError(
            f"Fixed page title {page.title!r} should be {expected_title!r}"
        )


def external_link_to_snapshot(link: ExternalLink) -> dict[str, Any]:
    return {
        "label": link.label,
        "external_url": link.external_url,
    }


def external_link_from_snapshot(snapshot: dict[str, Any]) -> ExternalLink:
    return ExternalLink(
        label=snapshot["label"],
        external_url=snapshot["external_url"],
    )
