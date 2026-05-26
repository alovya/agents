from notion_task_tracker.notion_pages.rest_blocks import markdown_from_rest_blocks, rich_text_items


def test_rich_text_items_render_date_and_page_mentions():
    items = rich_text_items(
        'See <mention-date start="2026-05-26"/> and <mention-page url="https://www.notion.so/22222222222222222222222222222222"/>.'
    )

    assert items == [
        {"type": "text", "text": {"content": "See "}},
        {"type": "mention", "mention": {"type": "date", "date": {"start": "2026-05-26"}}},
        {"type": "text", "text": {"content": " and "}},
        {
            "type": "mention",
            "mention": {
                "type": "page",
                "page": {"id": "22222222222222222222222222222222"},
            },
        },
        {"type": "text", "text": {"content": "."}},
    ]


def test_markdown_from_rest_blocks_preserves_date_mentions():
    markdown = markdown_from_rest_blocks([
        {
            "type": "heading_3",
            "heading_3": {
                "rich_text": [
                    {
                        "type": "mention",
                        "mention": {
                            "type": "date",
                            "date": {"start": "2026-05-26"},
                        },
                        "plain_text": "2026-05-26",
                    }
                ]
            },
        }
    ])

    assert markdown == '### <mention-date start="2026-05-26"/>'
