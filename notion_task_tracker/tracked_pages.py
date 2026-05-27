"""Tracker-owned references to pages that may exist in Notion."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class TrackedPage:
    """Page identity stored in tracker state."""

    local_page_key: str
    title: str
    notion_page_id: str | None = None
    parent_page_key: str | None = None


def tracked_page_to_tracker_state(page: TrackedPage) -> dict[str, str | None]:
    return {
        "local_page_key": page.local_page_key,
        "title": page.title,
        "notion_page_id": page.notion_page_id,
        "parent_page_key": page.parent_page_key,
    }


def fixed_tracked_page_from_tracker_state(
    tracker_state: dict[str, str | None],
    local_page_key: str,
    title: str,
) -> TrackedPage:
    return TrackedPage(
        local_page_key=local_page_key,
        title=title,
        notion_page_id=tracker_state.get("notion_page_id"),
        parent_page_key=tracker_state.get("parent_page_key"),
    )


def validate_fixed_tracked_page(
    page: TrackedPage,
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
