from notion_task_tracker.notion_operations.database_properties import rich_text_items


def test_rich_text_items_preserves_date_mentions_as_notion_mentions():
    rich_text = rich_text_items('Logged <mention-date start="2026-05-27"/>')

    assert rich_text == [
        {"type": "text", "text": {"content": "Logged "}},
        {
            "type": "mention",
            "mention": {
                "type": "date",
                "date": {"start": "2026-05-27"},
            },
        },
    ]
