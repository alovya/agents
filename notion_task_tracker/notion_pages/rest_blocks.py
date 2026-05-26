"""Convert tracker block shapes to and from Notion REST blocks."""

from __future__ import annotations

import re
from typing import Any

from notion_task_tracker.notion_pages.references import canonical_notion_page_id, notion_page_id_from_url


_DATE_MENTION_PATTERN = re.compile(r'<mention-date\s+[^>]*start="([^"]+)"[^>]*/>')
_PAGE_MENTION_PATTERN = re.compile(r'<mention-page\s+[^>]*url="([^"]+)"[^>]*/>')


def rest_blocks_from_tracker_blocks(blocks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    root_blocks: list[dict[str, Any]] = []
    bullet_stack: list[dict[str, Any]] = []

    for block in blocks:
        rest_block = _rest_block_from_tracker_block(block)
        if block.get("type") != "bulleted_list_item":
            root_blocks.append(rest_block)
            bullet_stack = []
            continue

        depth = int(block.get("depth", 0))
        if depth == 0 or not bullet_stack:
            root_blocks.append(rest_block)
            bullet_stack = [rest_block]
            continue

        parent_block = bullet_stack[min(depth - 1, len(bullet_stack) - 1)]
        parent_block[parent_block["type"]].setdefault("children", []).append(rest_block)
        bullet_stack = bullet_stack[:depth] + [rest_block]

    return root_blocks


def markdown_from_rest_blocks(blocks: list[dict[str, Any]]) -> str:
    return "\n".join(
        line
        for block in blocks
        for line in _markdown_lines_from_rest_block(block)
    )


def find_matching_top_level_block(
    blocks: list[dict[str, Any]],
    tracker_block: dict[str, Any],
) -> dict[str, Any] | None:
    for block in blocks:
        if _block_matches_tracker_block(block, tracker_block):
            return block
    return None


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


def _rest_block_from_tracker_block(block: dict[str, Any]) -> dict[str, Any]:
    block_type = block["type"]
    if block_type.startswith("heading_"):
        return _rest_heading_block(block)
    if block_type == "paragraph":
        return _rest_rich_text_block("paragraph", block["text"], {})
    if block_type == "bulleted_list_item":
        return _rest_rich_text_block(
            "bulleted_list_item",
            _landing_text_with_page_mention(block),
            {"color": block.get("color", "default")},
        )
    if block_type == "toggle":
        return _rest_toggle_block(block)
    if block_type == "page_mention":
        return _rest_rich_text_block("paragraph", _page_mention_text(block), {})
    if block_type == "child_page":
        return _rest_rich_text_block("paragraph", _page_mention_text(block), {})
    raise ValueError(f"Unsupported tracker block type {block_type!r}")


def _rest_heading_block(block: dict[str, Any]) -> dict[str, Any]:
    block_type = block["type"]
    return {
        "object": "block",
        "type": block_type,
        block_type: {
            "rich_text": rich_text_items(block["text"]),
            "is_toggleable": False,
        },
    }


def _rest_toggle_block(block: dict[str, Any]) -> dict[str, Any]:
    return {
        "object": "block",
        "type": "toggle",
        "toggle": {
            "rich_text": rich_text_items(block["text"]),
            "children": rest_blocks_from_tracker_blocks(block.get("children", [])),
        },
    }


def _rest_rich_text_block(block_type: str, text: str, extra_fields: dict[str, Any]) -> dict[str, Any]:
    return {
        "object": "block",
        "type": block_type,
        block_type: {
            "rich_text": rich_text_items(text),
            **extra_fields,
        },
    }


def _landing_text_with_page_mention(block: dict[str, Any]) -> str:
    text = block["text"]
    if "page_key" not in block:
        return text

    return _page_mention_text(block)


def _page_mention_text(block: dict[str, Any]) -> str:
    page_url = block.get("page_url")
    if page_url is not None:
        return f'<mention-page url="{page_url}"/>'

    page_key = block["page_key"]
    return f"<mention-page page_key=\"{page_key}\"/>"


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


def _markdown_lines_from_rest_block(block: dict[str, Any]) -> list[str]:
    block_type = block.get("type")
    if block_type in {"heading_1", "heading_2", "heading_3"}:
        level = int(block_type.removeprefix("heading_"))
        return [f"{'#' * level} {_plain_text_from_block(block)}"]
    if block_type == "paragraph":
        return [_plain_text_from_block(block)]
    if block_type == "bulleted_list_item":
        return [f"- {_plain_text_from_block(block)}"]
    if block_type == "toggle":
        return [
            "<details>",
            f"<summary>{_plain_text_from_block(block)}</summary>",
            "</details>",
        ]
    return []


def _plain_text_from_block(block: dict[str, Any]) -> str:
    block_type = block["type"]
    return plain_text_from_rich_text_items(block[block_type].get("rich_text", []))


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


def _block_matches_tracker_block(rest_block: dict[str, Any], tracker_block: dict[str, Any]) -> bool:
    return (
        rest_block.get("type") == tracker_block["type"]
        and _plain_text_from_block(rest_block) == tracker_block["text"]
    )
