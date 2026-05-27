"""Convert Notion database property rich text at the package boundary."""

from __future__ import annotations

import re
from typing import Any

from notion_task_tracker.page_registry import canonical_notion_page_id, notion_page_id_from_url


_DATE_MENTION_PATTERN = re.compile(r'<mention-date\s+[^>]*start="([^"]+)"[^>]*/>')
_PAGE_MENTION_PATTERN = re.compile(r'<mention-page\s+[^>]*url="([^"]+)"[^>]*/>')


def plain_text_from_rich_text_items(rich_text_items: list[dict[str, Any]]) -> str:
    return "".join(_plain_text_from_rich_text_item(rich_text_item) for rich_text_item in rich_text_items)


def rich_text_items(text: str) -> list[dict[str, Any]]:
    rich_text_items = []
    remaining_text = text

    while remaining_text:
        mention_match = _first_mention_match(remaining_text)
        if mention_match is None:
            rich_text_items.append(_text_item(remaining_text))
            break

        if mention_match.start() > 0:
            rich_text_items.append(_text_item(remaining_text[:mention_match.start()]))
        rich_text_items.append(_mention_item_from_match(mention_match))
        remaining_text = remaining_text[mention_match.end():]

    return rich_text_items or [_text_item("")]


def _first_mention_match(text: str) -> re.Match[str] | None:
    matches = [
        match
        for match in [_DATE_MENTION_PATTERN.search(text), _PAGE_MENTION_PATTERN.search(text)]
        if match is not None
    ]
    if not matches:
        return None
    return min(matches, key=lambda match: match.start())


def _mention_item_from_match(match: re.Match[str]) -> dict[str, Any]:
    if match.re is _DATE_MENTION_PATTERN:
        return {
            "type": "mention",
            "mention": {
                "type": "date",
                "date": {"start": match.group(1)},
            },
        }

    return {
        "type": "mention",
        "mention": {
            "type": "page",
            "page": {"id": notion_page_id_from_url(match.group(1))},
        },
    }


def _text_item(text: str) -> dict[str, Any]:
    return {
        "type": "text",
        "text": {"content": text},
    }


def _plain_text_from_rich_text_item(rich_text_item: dict[str, Any]) -> str:
    if rich_text_item.get("type") == "mention":
        return _plain_text_from_mention(rich_text_item["mention"])
    if "plain_text" in rich_text_item:
        return str(rich_text_item["plain_text"])
    return str(rich_text_item.get("text", {}).get("content", ""))


def _plain_text_from_mention(mention: dict[str, Any]) -> str:
    if mention.get("type") == "date":
        return f'<mention-date start="{mention["date"]["start"]}"/>'
    if mention.get("type") == "page":
        page_id = canonical_notion_page_id(mention["page"]["id"])
        return f'<mention-page url="https://www.notion.so/{page_id}"/>'
    return ""
