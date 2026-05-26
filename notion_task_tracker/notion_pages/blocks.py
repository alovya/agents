"""Internal Notion block shapes used by tracker page renderers."""

from __future__ import annotations

from typing import Any


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
