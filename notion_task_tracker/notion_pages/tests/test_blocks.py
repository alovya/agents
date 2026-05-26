from notion_task_tracker.notion_pages.blocks import heading_block, linked_metadata_bullet_block


def test_heading_block_records_level_and_text():
    assert heading_block(level=2, text="Timeline log") == {
        "type": "heading_2",
        "text": "Timeline log",
    }


def test_linked_metadata_bullet_block_records_page_key():
    assert linked_metadata_bullet_block(text="Parent", page_key="task:ALOVYA-1") == {
        "type": "bulleted_list_item",
        "depth": 0,
        "text": "Parent",
        "page_key": "task:ALOVYA-1",
    }
