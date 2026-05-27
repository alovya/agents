from pathlib import Path


PACKAGE_PATH = Path(__file__).resolve().parents[1]


def test_rest_client_does_not_import_mcp_symbols():
    source = _source("notion_io/rest_client.py")

    assert "notion_task_tracker.mcp" not in source
    assert "NotionMcp" not in source


def test_mcp_client_does_not_import_rest_symbols():
    source = _source("notion_io/mcp_client.py")

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
        "tracker_cli_workflow.py",
        "tasks/actions/write_task_log.py",
        "tasks/actions/create_task_page_in_database.py",
        "tasks/actions/refresh_task_tracker_state.py",
        "notion_io/write_executor.py",
    ]

    for workflow_file in workflow_files:
        source = _source(workflow_file)
        assert not any(forbidden in source for forbidden in forbidden_text), workflow_file


def test_tracker_metadata_modules_do_not_import_notion_io():
    metadata_files = [
        "tasks/task.py",
        "tasks/dependency_graph.py",
        "tasks/database.py",
        "tasks/pages/landing_pages.py",
        "miscellaneous_pages.py",
        "synthesis_pages.py",
    ]

    for metadata_file in metadata_files:
        assert "notion_task_tracker.notion_io" not in _source(metadata_file), metadata_file


def test_legacy_common_module_has_been_deleted():
    assert not (PACKAGE_PATH / "common.py").exists()


def test_legacy_notion_pages_package_has_been_deleted():
    assert not (PACKAGE_PATH / "notion_pages").exists()


def test_legacy_commands_module_has_been_renamed():
    assert not (PACKAGE_PATH / "commands.py").exists()


def test_one_function_complete_task_action_has_been_deleted():
    assert not (PACKAGE_PATH / "tasks" / "actions" / "complete_task.py").exists()


def test_internal_page_body_block_layer_has_been_deleted():
    assert not (PACKAGE_PATH / "internal_blocks.py").exists()
    assert not (PACKAGE_PATH / "enhanced_markdown_renderer.py").exists()
    assert not (PACKAGE_PATH / "notion_block_fallback.py").exists()


def test_rest_client_uses_notion_sdk_not_raw_http_transport():
    source = _source("notion_io/rest_client.py")

    assert "from notion_client import AsyncClient" in source
    assert "urlopen" not in source
    assert "urllib.request" not in source


def _source(relative_path: str) -> str:
    return (PACKAGE_PATH / relative_path).read_text(encoding="utf-8")
