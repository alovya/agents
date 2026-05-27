import pytest

from notion_task_tracker import NotionPlanningError
from notion_task_tracker.page_registry import canonical_notion_page_id, notion_page_id_from_url


def test_canonical_notion_page_id_accepts_hyphenated_page_ids():
    page_id = canonical_notion_page_id("22222222-2222-2222-2222-222222222222")

    assert page_id == "22222222222222222222222222222222"


def test_notion_page_id_from_url_rejects_urls_without_page_ids():
    with pytest.raises(NotionPlanningError):
        notion_page_id_from_url("https://www.notion.so/wayve/no-page-id")
