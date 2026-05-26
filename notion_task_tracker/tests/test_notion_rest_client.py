from notion_task_tracker.notion_rest_client import _notion_rest_error_message


def test_notion_rest_error_message_includes_request_context():
    error_message = _notion_rest_error_message(
        method="PATCH",
        path="/v1/pages/page-a/markdown",
        status_code=400,
        error_text='{"code":"validation_error","message":"old_str not found"}',
    )

    assert "PATCH" in error_message
    assert "/v1/pages/page-a/markdown" in error_message
    assert "validation_error" in error_message
