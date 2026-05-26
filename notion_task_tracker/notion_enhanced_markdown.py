"""Render internal blocks as Notion enhanced Markdown."""

from __future__ import annotations

from typing import Any

from notion_task_tracker.common import NotionPageRegistry, NotionPlanningError


class NotionMarkdownRenderer:
    """Renderer for the block dictionaries emitted by metadata objects."""

    def __init__(self, page_registry: NotionPageRegistry):
        self.page_registry = page_registry

    def render_blocks(self, blocks: list[dict[str, Any]]) -> str:
        return "\n".join(
            rendered_block
            for block in blocks
            for rendered_block in self._render_block(block)
        )

    def _render_block(self, block: dict[str, Any]) -> list[str]:
        block_type = block["type"]

        if block_type.startswith("heading_"):
            return [self._render_heading_block(block)]

        if block_type == "paragraph":
            return [block["text"]]

        if block_type == "code":
            return self._render_code_block(block)

        if block_type == "page_mention":
            return [self._render_page_mention(block["page_key"])]

        if block_type == "child_page":
            return [self._render_child_page(block["page_key"])]

        if block_type == "bulleted_list_item":
            return [self._render_bullet_block(block)]

        if block_type == "toggle":
            return self._render_toggle_block(block)

        raise NotionPlanningError(f"Unsupported Notion block type {block_type!r}")

    def _render_heading_block(self, block: dict[str, Any]) -> str:
        heading_level = int(block["type"].removeprefix("heading_"))
        return f"{'#' * heading_level} {block['text']}"

    def _render_code_block(self, block: dict[str, Any]) -> list[str]:
        language = block.get("language", "")
        return [
            f"```{language}",
            block["text"],
            "```",
        ]

    def _render_bullet_block(self, block: dict[str, Any]) -> str:
        indent = "\t" * block.get("depth", 0)
        text = self._render_block_text(block)
        color = self._render_color_suffix(block)
        return f"{indent}- {text}{color}"

    def _render_toggle_block(self, block: dict[str, Any]) -> list[str]:
        return [
            "<details>",
            f"<summary>{block['text']}</summary>",
            *self._render_indented_child_blocks(block.get("children", [])),
            "</details>",
        ]

    def _render_indented_child_blocks(self, child_blocks: list[dict[str, Any]]) -> list[str]:
        return [
            f"\t{child_line}"
            for child_block in child_blocks
            for child_line in self._render_block(child_block)
        ]

    def _render_block_text(self, block: dict[str, Any]) -> str:
        if "page_key" not in block:
            return block["text"]

        page_key = block["page_key"]
        page_mention = self._render_page_mention(page_key)
        text = block["text"]

        if text.startswith("["):
            return self._render_landing_page_mention_text(text, page_mention)

        if self._looks_like_status_suffix(text):
            status = text.rsplit(": ", 1)[1]
            return f"{page_mention}: {status}"

        if ": " in text:
            prefix = text.split(": ", 1)[0]
            return f"{prefix}: {page_mention}"

        return page_mention

    def _render_landing_page_mention_text(self, text: str, page_mention: str) -> str:
        priority_prefix, task_text = text.split("] ", 1)
        status = task_text.rsplit(": ", 1)[1]
        return f"{priority_prefix}] {page_mention}: {status}"

    def _render_page_mention(self, page_key: str) -> str:
        page_url = self.page_registry.page_url(page_key)
        return f'<mention-page url="{page_url}"/>'

    def _render_child_page(self, page_key: str) -> str:
        page_url = self.page_registry.page_url(page_key)
        page_title = self.page_registry.page_title(page_key)
        return f'<page url="{page_url}">{page_title}</page>'

    def _render_color_suffix(self, block: dict[str, Any]) -> str:
        if "color" not in block:
            return ""

        return f' {{color="{block["color"]}"}}'

    def _looks_like_status_suffix(self, text: str) -> bool:
        if ": " not in text:
            return False

        status = text.rsplit(": ", 1)[1]
        return status in {"Active", "Blocked", "Parked", "Complete", "Cancelled"}
