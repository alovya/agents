import pytest

from notion_task_tracker.common import (
    NotionPageReference,
    NotionPageRegistry,
    NotionPlanningError,
)
from notion_task_tracker.notion_enhanced_markdown import NotionMarkdownRenderer


class TestNotionMarkdownRendererRenderBlocks:
    def test_renders_headings_paragraphs_nested_bullets_colours_and_page_mentions(self):
        renderer = NotionMarkdownRenderer(_page_registry())

        markdown = renderer.render_blocks(
            [
                {"type": "heading_2", "text": "P0 (high impact and urgent)"},
                {
                    "type": "page_mention",
                    "page_key": "task:ALOVYA-1",
                },
                {
                    "type": "child_page",
                    "page_key": "task:ALOVYA-2",
                },
                {
                    "type": "bulleted_list_item",
                    "depth": 0,
                    "text": "[P0] ALOVYA-1: Root task: Active",
                    "page_key": "task:ALOVYA-1",
                    "color": "red",
                },
                {
                    "type": "bulleted_list_item",
                    "depth": 1,
                    "text": "ALOVYA-2: Active",
                    "page_key": "task:ALOVYA-2",
                    "color": "orange",
                },
                {"type": "paragraph", "text": "No timeline entries yet."},
            ]
        )

        assert markdown == "\n".join(
            [
                "## P0 (high impact and urgent)",
                (
                    '<mention-page url="https://www.notion.so/aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"/>'
                ),
                (
                    '<page url="https://www.notion.so/bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb">'
                    "ALOVYA-2: Child task</page>"
                ),
                (
                    '- [P0] <mention-page url="https://www.notion.so/aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"/>'
                    ': Active {color="red"}'
                ),
                (
                    '\t- <mention-page url="https://www.notion.so/bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"/>'
                    ': Active {color="orange"}'
                ),
                "No timeline entries yet.",
            ]
        )

    def test_renders_source_mentions_with_prefix_text(self):
        renderer = NotionMarkdownRenderer(_page_registry())

        markdown = renderer.render_blocks(
            [
                {
                    "type": "bulleted_list_item",
                    "depth": 0,
                    "text": "Notion page: ALOVYA-2",
                    "page_key": "task:ALOVYA-2",
                },
            ]
        )

        assert markdown == "\n".join(
            [
                (
                    '- Notion page: <mention-page url="https://www.notion.so/bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"/>'
                ),
            ]
        )

    def test_renders_toggle_with_indented_children(self):
        renderer = NotionMarkdownRenderer(_page_registry())

        markdown = renderer.render_blocks(
            [
                {
                    "type": "toggle",
                    "text": "Design notes",
                    "children": [
                        {
                            "type": "bulleted_list_item",
                            "depth": 0,
                            "text": "Moved task metadata into the database.",
                        }
                    ],
                }
            ]
        )

        assert markdown == "\n".join(
            [
                "<details>",
                "<summary>Design notes</summary>",
                "\t- Moved task metadata into the database.",
                "</details>",
            ]
        )

    def test_renders_code_blocks(self):
        renderer = NotionMarkdownRenderer(_page_registry())

        markdown = renderer.render_blocks(
            [
                {"type": "paragraph", "text": "Commands run:"},
                {
                    "type": "code",
                    "language": "bash",
                    "text": "st status\nstax rs --restack",
                },
            ]
        )

        assert markdown == "\n".join(
            [
                "Commands run:",
                "```bash",
                "st status\nstax rs --restack",
                "```",
            ]
        )

    def test_rejects_missing_page_ids_for_mentions(self):
        renderer = NotionMarkdownRenderer(
            NotionPageRegistry(
                pages={
                    "task:ALOVYA-1": NotionPageReference(
                        local_page_key="task:ALOVYA-1",
                        title="ALOVYA-1: Root task",
                    )
                }
            )
        )

        with pytest.raises(NotionPlanningError, match="has no Notion URL or page id"):
            renderer.render_blocks(
                [
                    {
                        "type": "bulleted_list_item",
                        "depth": 0,
                        "text": "ALOVYA-1: Active",
                        "page_key": "task:ALOVYA-1",
                    }
                ]
            )


def _page_registry() -> NotionPageRegistry:
    return NotionPageRegistry(
        pages={
            "task:ALOVYA-1": NotionPageReference(
                local_page_key="task:ALOVYA-1",
                title="ALOVYA-1: Root task",
                notion_page_id="aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
            ),
            "task:ALOVYA-2": NotionPageReference(
                local_page_key="task:ALOVYA-2",
                title="ALOVYA-2: Child task",
                notion_page_id="bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
            ),
        }
    )
