"""Small helpers for the Notion enhanced Markdown we intentionally emit."""

from __future__ import annotations

from notion_task_tracker.notion_operations.write_intent import NotionPlanningError
from notion_task_tracker.notion_operations.page_registry import NotionPageRegistry


def join_markdown_blocks(markdown_blocks: list[str]) -> str:
    return "\n".join(block.rstrip() for block in markdown_blocks if block.strip())


def heading(level: int, text: str) -> str:
    return f"{'#' * level} {text}"


def bullet(text: str, depth: int = 0, colour: str | None = None) -> str:
    colour_suffix = f' {{color="{colour}"}}' if colour else ""
    return f"{'\t' * depth}- {text}{colour_suffix}"


def page_mention(page_key: str, page_registry: NotionPageRegistry) -> str:
    return f'<mention-page url="{page_registry.page_url(page_key)}"/>'


def child_page(page_key: str, page_registry: NotionPageRegistry) -> str:
    return f'<page url="{page_registry.page_url(page_key)}">{page_registry.page_title(page_key)}</page>'


def date_mention(entry_date: str) -> str:
    return f'<mention-date start="{entry_date}"/>'


def toggle(summary: str, body_markdown: str) -> str:
    child_lines = [f"\t{line}" for line in body_markdown.splitlines()]
    return join_markdown_blocks([
        "<details>",
        f"<summary>{summary}</summary>",
        "\n".join(child_lines),
        "</details>",
    ])


def page_reference(
    page_key: str,
    root_block_type: str,
    page_registry: NotionPageRegistry,
) -> str:
    if root_block_type == "child_page":
        return child_page(page_key, page_registry)
    if root_block_type == "page_mention":
        return page_mention(page_key, page_registry)
    raise NotionPlanningError(f"Unsupported page reference type {root_block_type!r}")
