from notion_task_tracker.tasks.pages.timeline_log import (
    initialised_task_timeline_blocks,
    timeline_entries_from_fetched_task_page_content,
)


def test_timeline_entries_from_fetched_task_page_content_reads_unique_date_headings():
    timeline_entries = timeline_entries_from_fetched_task_page_content(
        "\n".join(
            [
                "<page>",
                "<content>",
                "## Timeline log",
                '### <mention-date start="2026-05-26"/>',
                "- First entry",
                '### <mention-date start="2026-05-26"/>',
                "- Duplicate heading",
                '### <mention-date start="2026-05-25"/>',
                "</content>",
                "</page>",
            ]
        )
    )

    assert timeline_entries == [
        {"entry_date": "2026-05-26", "heading": '<mention-date start="2026-05-26"/>'},
        {"entry_date": "2026-05-25", "heading": '<mention-date start="2026-05-25"/>'},
    ]


def test_initialised_task_timeline_blocks_subsumes_existing_body_under_today():
    blocks = initialised_task_timeline_blocks(
        entry_date="2026-05-26",
        timeline_blocks=[{"type": "bulleted_list_item", "depth": 0, "text": "Started task."}],
        fetched_page_content="<content>Loose note from the page body.</content>",
    )

    assert blocks == [
        {"type": "heading_2", "text": "Timeline log"},
        {"type": "heading_3", "text": '<mention-date start="2026-05-26"/>'},
        {"type": "bulleted_list_item", "depth": 0, "text": "Started task."},
        {"type": "paragraph", "text": "Loose note from the page body."},
    ]
