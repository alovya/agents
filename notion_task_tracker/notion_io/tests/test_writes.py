from notion_task_tracker.notion_io.writes import NotionWriteIntent


def test_notion_write_intent_records_operation_and_target():
    write_intent = NotionWriteIntent(
        operation_key="replace:landing_page",
        operation_name="replace_page_markdown",
        target_page_key="landing_page",
        arguments={"markdown": "Landing page body"},
    )

    assert write_intent.operation_key == "replace:landing_page"
    assert write_intent.arguments == {"markdown": "Landing page body"}
