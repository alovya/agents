from pathlib import Path


PACKAGE_PATH = Path(__file__).resolve().parents[1]


def test_rest_client_does_not_import_mcp_symbols():
    source = _source("notion_rest_client.py")

    assert "notion_task_tracker.mcp" not in source
    assert "NotionMcp" not in source


def test_mcp_client_does_not_import_rest_symbols():
    source = _source("notion_mcp_client.py")

    assert "notion_task_tracker.rest" not in source
    assert "NotionRest" not in source


def test_workflow_modules_do_not_import_notion_protocol_details():
    forbidden_text = [
        "NotionMcpToolCall",
        "NotionMcpCallPlanner",
        "NotionRestClient",
        "execute_write_intent",
        "send_call",
    ]
    workflow_files = [
        "tasks/workflow.py",
        "tasks/actions/write_log.py",
        "tasks/actions/create_task_page_in_database.py",
        "tasks/actions/update_task_dependencies.py",
        "notion_write_executor.py",
    ]

    for workflow_file in workflow_files:
        source = _source(workflow_file)
        assert not any(forbidden in source for forbidden in forbidden_text), workflow_file


def _source(relative_path: str) -> str:
    return (PACKAGE_PATH / relative_path).read_text(encoding="utf-8")
