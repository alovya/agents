"""Local references to Notion pages."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from notion_task_tracker.notion_operations.write_intent import NotionPlanningError
from notion_task_tracker.notion_operations.notion_id import canonical_notion_page_id, notion_page_id_from_url
from notion_task_tracker.tracked_pages import TrackedPage


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
    def from_tracked_pages(cls, tracked_pages: list[TrackedPage]) -> "NotionPageRegistry":
        return cls(
            pages={
                page.local_page_key: NotionPageReference(
                    local_page_key=page.local_page_key,
                    title=page.title,
                    notion_page_id=page.notion_page_id,
                    parent_page_key=page.parent_page_key,
                )
                for page in tracked_pages
            }
        )

    @classmethod
    def from_tracker_state(cls, tracker_state: dict[str, Any]) -> "NotionPageRegistry":
        return cls(
            pages={
                local_page_key: notion_page_reference_from_tracker_state(reference_state)
                for local_page_key, reference_state in tracker_state.items()
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

    def to_tracker_state(self) -> dict[str, Any]:
        return {
            local_page_key: notion_page_reference_to_tracker_state(page)
            for local_page_key, page in sorted(self.pages.items())
        }


def notion_page_reference_to_tracker_state(page: NotionPageReference) -> dict[str, Any]:
    return {
        "local_page_key": page.local_page_key,
        "title": page.title,
        "notion_page_id": page.notion_page_id,
        "notion_url": page.notion_url,
        "parent_page_key": page.parent_page_key,
    }


def notion_page_reference_from_tracker_state(tracker_state: dict[str, Any]) -> NotionPageReference:
    return NotionPageReference(
        local_page_key=tracker_state["local_page_key"],
        title=tracker_state["title"],
        notion_page_id=tracker_state.get("notion_page_id"),
        notion_url=tracker_state.get("notion_url"),
        parent_page_key=tracker_state.get("parent_page_key"),
    )

