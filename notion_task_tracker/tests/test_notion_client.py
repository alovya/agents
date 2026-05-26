import asyncio
import json
from pathlib import Path
import pytest

from notion_task_tracker.commands import CommandResult
from notion_task_tracker.common import (
    COMPLETED_LANDING_PAGE_TITLE,
    LANDING_PAGE_TITLE,
    NotionPageReference,
    NotionPageRegistry,
    NotionWriteIntent,
)
from notion_task_tracker.notion_mcp_calls import NotionMcpCallPlan, NotionMcpToolCall
from notion_task_tracker.notion_client import (
    _execute_database_task_creation_command,
    _execute_command_result_writes,
    _notion_client_from_credentials_path,
    _repair_and_write_reconciled_tracker_state,
    _raise_if_call_plan_has_blocked_operations,
    _repair_operation_keys_for_reconciled_task_pages,
    _reconcile_tracker_state_for_command_targets,
    _reconcile_tracker_state_from_notion_pages,
    _timeline_entries_from_fetched_task_page_content,
    _tracker_state_ready_for_task_timeline_write,
    _tracker_state_with_fetched_task_timeline_dates,
)
from notion_task_tracker.notion_mcp_client import NotionMcpClient
from notion_task_tracker.notion_rest_client import NotionRestClient
from notion_task_tracker.task_pages import Priority, TaskDependencyGraph, TaskPageMetadata, TaskStatus
from notion_task_tracker.task_pages.task_database import default_task_database_tracker_state


def test_rest_client_does_not_import_notion_mcp_runtime():
    package_path = Path(__file__).resolve().parents[1]
    runtime_source = (package_path / "notion_rest_client.py").read_text(encoding="utf-8")

    assert "from mcp" not in runtime_source
    assert "import mcp" not in runtime_source
    assert "streamable_http" not in runtime_source
    assert "NotionMcpToolCall" not in runtime_source


def test_notion_client_from_credentials_path_defaults_to_rest(monkeypatch, tmp_path):
    credentials_path = tmp_path / ".credentials.json"
    credentials_path.write_text("{}", encoding="utf-8")
    monkeypatch.setenv("NOTION_API_KEY", "ntn_test")

    notion_client = _notion_client_from_credentials_path(credentials_path)

    assert isinstance(notion_client, NotionRestClient)


def test_notion_client_from_credentials_path_keeps_mcp_fallback(tmp_path):
    credentials_path = tmp_path / ".credentials.json"
    credentials_path.write_text(
        json.dumps(
            {
                "Notion|workspace": {
                    "access_token": "mcp-token",
                    "server_url": "https://mcp.notion.test/mcp",
                }
            }
        ),
        encoding="utf-8",
    )

    notion_client = _notion_client_from_credentials_path(credentials_path, "mcp")

    assert isinstance(notion_client, NotionMcpClient)


def test_repair_and_write_reconciled_tracker_state_pushes_repairs_for_changed_task(
    tmp_path: Path,
):
    notion_client = _FakeNotionMcpClient()
    tracker_state_path = tmp_path / "tracker_state.json"
    output_path = tmp_path / "output.json"
    backup_path = tmp_path / "backup.json"
    before_tracker_state = {
        "landing_page": {
            "local_page_key": "landing_page",
            "title": LANDING_PAGE_TITLE,
            "notion_page_id": "11111111111111111111111111111111",
            "parent_page_key": None,
        },
        "completed_landing_page": {
            "local_page_key": "completed_landing_page",
            "title": COMPLETED_LANDING_PAGE_TITLE,
            "notion_page_id": None,
            "parent_page_key": None,
        },
        "tasks": {
            "ALOVYA-1": {
                "task_id": "ALOVYA-1",
                "title": "Investigate baseline behaviour",
                "configured_priority": "P1",
                "displayed_priority": "P1",
                "status": "Active",
                "status_update": "",
                "parent_task_id": None,
                "child_task_ids": [],
                "timeline_entries": [],
                "links": [],
                "notion_page_id": "22222222222222222222222222222222",
            }
        },
    }
    after_tracker_state = {
        "landing_page": {
            "local_page_key": "landing_page",
            "title": LANDING_PAGE_TITLE,
            "notion_page_id": "11111111111111111111111111111111",
            "parent_page_key": None,
        },
        "completed_landing_page": {
            "local_page_key": "completed_landing_page",
            "title": COMPLETED_LANDING_PAGE_TITLE,
            "notion_page_id": None,
            "parent_page_key": None,
        },
        "tasks": {
            "ALOVYA-1": {
                "task_id": "ALOVYA-1",
                "title": "Investigate edited behaviour",
                "configured_priority": "P2",
                "displayed_priority": "P2",
                "status": "Active",
                "status_update": "",
                "parent_task_id": None,
                "child_task_ids": [],
                "timeline_entries": [],
                "links": [],
                "notion_page_id": "22222222222222222222222222222222",
            }
        },
    }
    tracker_state_path.write_text(json.dumps(before_tracker_state), encoding="utf-8")
    backup_path.write_text(json.dumps(before_tracker_state), encoding="utf-8")

    reconcile_summary = asyncio.run(
        _repair_and_write_reconciled_tracker_state(
            source_tracker_state_path=tracker_state_path,
            destination_output_path=output_path,
            destination_backup_path=backup_path,
            before_tracker_state=before_tracker_state,
            reconcile_result=CommandResult(
                tracker_state=after_tracker_state,
                warnings=[{"kind": "manual_repair", "message": "Derived Notion views need repair"}],
            ),
            notion_client=notion_client,
        ),
    )

    assert json.loads(backup_path.read_text(encoding="utf-8")) == before_tracker_state
    assert json.loads(tracker_state_path.read_text(encoding="utf-8")) == after_tracker_state
    assert [tool_call.operation_key for tool_call in notion_client.calls] == [
        "update_properties:task:ALOVYA-1",
        "replace:landing_page",
    ]
    output = json.loads(output_path.read_text(encoding="utf-8"))
    assert output["completed_operations"] == [
        "update_properties:task:ALOVYA-1",
        "replace:landing_page",
    ]
    assert reconcile_summary.to_json_summary() == {
        "backup_path": str(backup_path),
        "completed_operations": [
            "update_properties:task:ALOVYA-1",
            "replace:landing_page",
        ],
        "output_path": str(output_path),
        "tracker_state_path": str(tracker_state_path),
        "task_count": 1,
        "repair_operation_count": 2,
        "task_graph_changes": [
            {
                "task_id": "ALOVYA-1",
                "fields": {
                    "configured_priority": {"before": "P1", "after": "P2"},
                    "title": {
                        "before": "Investigate baseline behaviour",
                        "after": "Investigate edited behaviour",
                    },
                },
            }
        ],
        "warnings": [{"kind": "manual_repair", "message": "Derived Notion views need repair"}],
    }


def test_repair_and_write_reconciled_tracker_state_skips_repairs_when_nothing_changed(
    tmp_path: Path,
):
    notion_client = _FakeNotionMcpClient()
    tracker_state_path = tmp_path / "tracker_state.json"
    output_path = tmp_path / "output.json"
    backup_path = tmp_path / "backup.json"
    tracker_state = {
        "landing_page": {
            "local_page_key": "landing_page",
            "title": LANDING_PAGE_TITLE,
            "notion_page_id": "11111111111111111111111111111111",
            "parent_page_key": None,
        },
        "completed_landing_page": {
            "local_page_key": "completed_landing_page",
            "title": COMPLETED_LANDING_PAGE_TITLE,
            "notion_page_id": None,
            "parent_page_key": None,
        },
        "tasks": {
            "ALOVYA-1": {
                "task_id": "ALOVYA-1",
                "title": "Stable task",
                "configured_priority": "P1",
                "displayed_priority": "P1",
                "status": "Active",
                "status_update": "",
                "parent_task_id": None,
                "child_task_ids": [],
                "timeline_entries": [],
                "links": [],
                "notion_page_id": "22222222222222222222222222222222",
            }
        },
    }
    tracker_state_path.write_text(json.dumps(tracker_state), encoding="utf-8")
    backup_path.write_text(json.dumps(tracker_state), encoding="utf-8")

    reconcile_summary = asyncio.run(
        _repair_and_write_reconciled_tracker_state(
            source_tracker_state_path=tracker_state_path,
            destination_output_path=output_path,
            destination_backup_path=backup_path,
            before_tracker_state=tracker_state,
            reconcile_result=CommandResult(
                tracker_state=tracker_state,
                warnings=[],
            ),
            notion_client=notion_client,
        ),
    )

    output = json.loads(output_path.read_text(encoding="utf-8"))
    assert output["completed_operations"] == []
    assert notion_client.calls == []
    assert reconcile_summary.to_json_summary()["task_graph_changes"] == []
    assert reconcile_summary.to_json_summary()["repair_operation_count"] == 0


def test_execute_command_result_writes_compiles_mcp_calls_downstream():
    notion_client = _FakeNotionMcpClient()
    command_result = CommandResult(
        tracker_state={},
        write_intents=[
            NotionWriteIntent(
                operation_key="replace:landing_page",
                operation_name="replace_page_children",
                target_page_key="landing_page",
                arguments={"blocks": [{"type": "paragraph", "text": "A"}]},
            ),
            NotionWriteIntent(
                operation_key="update_properties:task:ALOVYA-1",
                operation_name="update_page_properties",
                target_page_key="task:ALOVYA-1",
                arguments={"properties": {"Status": "Active"}},
            ),
        ],
        page_registry=NotionPageRegistry(
            pages={
                "landing_page": NotionPageReference(
                    local_page_key="landing_page",
                    title="Landing",
                    notion_page_id="11111111111111111111111111111111",
                ),
                "task:ALOVYA-1": NotionPageReference(
                    local_page_key="task:ALOVYA-1",
                    title="Task",
                    notion_page_id="22222222222222222222222222222222",
                ),
            }
        ),
    )

    _tracker_state, completed_operation_keys = asyncio.run(
        _execute_command_result_writes(command_result, notion_client)
    )

    assert [tool_call.operation_key for tool_call in notion_client.calls] == [
        "replace:landing_page",
        "update_properties:task:ALOVYA-1",
    ]
    assert completed_operation_keys == [
        "replace:landing_page",
        "update_properties:task:ALOVYA-1",
    ]


def test_reconcile_tracker_state_from_notion_pages_uses_database_view_when_configured():
    tracker_state = _tracker_state_with_root_task()
    tracker_state["task_database"] = default_task_database_tracker_state()
    notion_client = _FakeNotionMcpClient(
        database_rows=[
            {
                "Ticket page": "Root task edited in database",
                "Ticket ID": "1",
                "Priority": "P2",
                "Status": "Blocked",
                "Parent": "[]",
                "url": "https://www.notion.so/22222222222222222222222222222222",
            }
        ]
    )

    command_result = asyncio.run(_reconcile_tracker_state_from_notion_pages(tracker_state, notion_client))

    assert command_result.tracker_state["tasks"]["ALOVYA-1"]["title"] == "Root task edited in database"
    assert command_result.tracker_state["tasks"]["ALOVYA-1"]["configured_priority"] == "P2"
    assert command_result.tracker_state["tasks"]["ALOVYA-1"]["status"] == "Blocked"
    assert notion_client.view_queries == [
        "https://www.notion.so/wayve/36b03da5d69a80b4acacf711623b59e8?v=36b03da5d69a800c893f000cf2aefead"
    ]
    assert notion_client.queries == []
    assert notion_client.fetched_pages == []


def test_reconcile_tracker_state_from_notion_pages_uses_sql_when_view_is_not_configured():
    tracker_state = _tracker_state_with_root_task()
    tracker_state["task_database"] = default_task_database_tracker_state()
    tracker_state["task_database"].pop("view_url")
    notion_client = _FakeNotionMcpClient(
        database_rows=[
            {
                "Ticket page": "Root task edited in database",
                "Ticket ID": "1",
                "Priority": "P2",
                "Status": "Blocked",
                "Parent": "[]",
                "url": "https://www.notion.so/22222222222222222222222222222222",
            }
        ]
    )

    command_result = asyncio.run(_reconcile_tracker_state_from_notion_pages(tracker_state, notion_client))

    assert command_result.tracker_state["tasks"]["ALOVYA-1"]["configured_priority"] == "P2"
    assert notion_client.view_queries == []
    assert notion_client.queries == [
        {
            "data_source_url": "collection://36b03da5-d69a-8080-91d1-000b5d7c1c8d",
            "query": (
                'SELECT * FROM "collection://36b03da5-d69a-8080-91d1-000b5d7c1c8d" '
                'WHERE "Priority" IS NOT NULL AND "Status" IS NOT NULL'
            ),
        }
    ]


def test_reconcile_tracker_state_for_command_targets_fetches_only_relevant_pages():
    tracker_state = _tracker_state_with_root_and_child_task()
    notion_client = _FakeNotionMcpClient(
        fetched_page_content_by_id={
            "22222222222222222222222222222222": _fetched_task_page(
                ticket_id="1",
                title="Root task",
                priority="P1",
                status="Active",
                parent_urls=[],
            ),
            "33333333333333333333333333333333": _fetched_task_page(
                ticket_id="2",
                title="Child task edited in database",
                priority="P2",
                status="Blocked",
                parent_urls=["https://www.notion.so/22222222222222222222222222222222"],
            ),
        }
    )

    command_result = asyncio.run(
        _reconcile_tracker_state_for_command_targets(
            command={
                "command": "create_sibling_task",
                "sibling_task_id": "ALOVYA-2",
                "sibling_task": {
                    "title": "Sibling task",
                    "configured_priority": "P2",
                    "status": "Active",
                },
            },
            tracker_state=tracker_state,
            notion_client=notion_client,
        )
    )

    assert command_result.tracker_state["tasks"]["ALOVYA-2"]["title"] == "Child task edited in database"
    assert command_result.tracker_state["tasks"]["ALOVYA-2"]["configured_priority"] == "P2"
    assert command_result.tracker_state["tasks"]["ALOVYA-2"]["status"] == "Blocked"
    assert command_result.tracker_state["tasks"]["ALOVYA-2"]["parent_task_id"] == "ALOVYA-1"
    assert notion_client.fetched_pages == [
        "33333333333333333333333333333333",
        "22222222222222222222222222222222",
    ]
    assert notion_client.view_queries == []
    assert notion_client.queries == []


def test_reconcile_tracker_state_for_command_targets_requires_known_tasks():
    tracker_state = _tracker_state_with_root_task()
    notion_client = _FakeNotionMcpClient()

    with pytest.raises(ValueError, match="ALOVYA-99"):
        asyncio.run(
            _reconcile_tracker_state_for_command_targets(
                command={
                    "command": "complete_task",
                    "task_id": "ALOVYA-99",
                    "timeline_entry": {
                        "entry_date": "2026-05-26",
                        "heading": '<mention-date start="2026-05-26"/>',
                        "lines": ["Completed missing task."],
                    },
                },
                tracker_state=tracker_state,
                notion_client=notion_client,
            )
        )

    assert notion_client.fetched_pages == []
    assert notion_client.view_queries == []
    assert notion_client.queries == []


def test_execute_database_task_creation_command_creates_database_row_then_refreshes_landing():
    tracker_state = _tracker_state_with_root_task()
    tracker_state["task_database"] = default_task_database_tracker_state()
    notion_client = _FakeNotionMcpClient(
        results=[
            {"result": {"text": "https://www.notion.so/33333333333333333333333333333333"}},
            {"result": {"text": ""}},
            {"result": {"text": ""}},
            {"result": {"text": ""}},
        ],
        fetched_page_content_by_id={
            "33333333333333333333333333333333": "\n".join(
                [
                    "<page>",
                    "<properties>",
                    '{"Ticket ID":"72","Ticket page":"Child task"}',
                    "</properties>",
                    "</page>",
                ]
            )
        },
    )

    updated_tracker_state, completed_operation_keys = asyncio.run(
        _execute_database_task_creation_command(
            command={
                "command": "create_child_task",
                "parent_task_id": "ALOVYA-1",
                "child_task": {
                    "title": "Child task",
                    "configured_priority": "P2",
                    "status": "Active",
                },
                "parent_timeline_entry": {
                    "entry_date": "2026-05-25",
                    "heading": '<mention-date start="2026-05-25"/>',
                    "lines": ["Spawned child task."],
                },
            },
            tracker_state=tracker_state,
            notion_client=notion_client,
        )
    )

    assert updated_tracker_state["tasks"]["ALOVYA-72"]["parent_task_id"] == "ALOVYA-1"
    assert updated_tracker_state["tasks"]["ALOVYA-72"]["notion_page_id"] == "33333333333333333333333333333333"
    assert updated_tracker_state["tasks"]["ALOVYA-72"]["timeline_entries"] == [
            {
                "entry_date": "2026-05-25",
                "heading": '<mention-date start="2026-05-25"/>',
                "lines": [],
                "blocks": [],
            }
        ]
    assert completed_operation_keys == [
        "create_database_task:create_child_task",
        "update_properties:task:ALOVYA-72",
        "initialise_timeline_log:task:ALOVYA-1:2026-05-25",
        "update_timeline_log:task:ALOVYA-1:2026-05-25",
        "replace:landing_page",
    ]
    assert notion_client.calls[0].tool_name == "notion-create-pages"
    assert notion_client.calls[0].arguments["parent"] == {
        "type": "data_source_id",
        "data_source_id": "36b03da5-d69a-8080-91d1-000b5d7c1c8d",
    }
    assert notion_client.calls[0].arguments["pages"][0]["properties"] == {
        "Ticket page": "Child task",
        "Priority": "P2",
        "Status": "Active",
        "Parent": '["https://www.notion.so/22222222222222222222222222222222"]',
    }
    assert notion_client.calls[0].arguments["pages"][0]["content"] == "\n".join(
        [
            "## Timeline log",
            '### <mention-date start="2026-05-25"/>',
            '- Spawned from parent task: <mention-page url="https://www.notion.so/22222222222222222222222222222222"/>.',
        ]
    )
    assert notion_client.calls[1].arguments["properties"] == {
        "Ticket page": "Child task",
    }
    assert notion_client.calls[3].arguments["content_updates"][0]["new_str"] == "\n".join(
        [
            '### <mention-date start="2026-05-25"/>',
            '- Spawned child task: <mention-page url="https://www.notion.so/33333333333333333333333333333333"/>.',
        ]
    )
    assert notion_client.calls[-1].arguments["command"] == "replace_content"


def test_timeline_entries_from_fetched_task_page_content_reads_manual_date_headings():
    timeline_entries = _timeline_entries_from_fetched_task_page_content(
        "\n".join(
            [
                "<page>",
                "## Timeline log",
                '### <mention-date start="2026-05-26"/>',
                "- Human note.",
                "### 2026-05-25",
                "- Older human note.",
                "</page>",
            ]
        )
    )

    assert timeline_entries == [
        {
            "entry_date": "2026-05-26",
            "heading": '<mention-date start="2026-05-26"/>',
        },
        {
            "entry_date": "2026-05-25",
            "heading": "2026-05-25",
        },
    ]


def test_tracker_state_with_fetched_task_timeline_dates_remembers_manual_date_before_logging():
    tracker_state = _tracker_state_with_root_task()
    notion_client = _FakeNotionMcpClient(
        fetched_page_content_by_id={
            "22222222222222222222222222222222": "\n".join(
                [
                    "## Timeline log",
                    '### <mention-date start="2026-05-26"/>',
                    "- Human note.",
                ]
            )
        }
    )

    updated_tracker_state = asyncio.run(
        _tracker_state_with_fetched_task_timeline_dates(
            task_id="ALOVYA-1",
            tracker_state=tracker_state,
            notion_client=notion_client,
        )
    )

    assert updated_tracker_state["tasks"]["ALOVYA-1"]["timeline_entries"] == [
        {
            "entry_date": "2026-05-26",
            "heading": '<mention-date start="2026-05-26"/>',
            "lines": [],
        }
    ]
    assert notion_client.fetched_pages == ["22222222222222222222222222222222"]


def test_tracker_state_ready_for_task_timeline_write_initialises_missing_timeline_log():
    tracker_state = _tracker_state_with_root_task()
    notion_client = _FakeNotionMcpClient(
        fetched_page_content_by_id={
            "22222222222222222222222222222222": "\n".join(
                [
                    "<page>",
                    "<properties>",
                    '{"Ticket ID":"1","Ticket page":"Root task"}',
                    "</properties>",
                    "Loose notes written before the tracker touched the page.",
                    "</page>",
                ]
            )
        }
    )

    updated_tracker_state, operation_keys = asyncio.run(
        _tracker_state_ready_for_task_timeline_write(
            task_id="ALOVYA-1",
            entry_date="2026-05-26",
            tracker_state=tracker_state,
            notion_client=notion_client,
        )
    )

    assert operation_keys == ["initialise_timeline_log:task:ALOVYA-1:2026-05-26"]
    assert updated_tracker_state["tasks"]["ALOVYA-1"]["timeline_entries"] == [
        {
            "entry_date": "2026-05-26",
            "heading": '<mention-date start="2026-05-26"/>',
            "lines": [],
        }
    ]
    assert notion_client.calls[0].arguments == {
        "page_id": "22222222222222222222222222222222",
        "command": "replace_content",
        "new_str": "\n".join(
            [
                "## Timeline log",
                '### <mention-date start="2026-05-26"/>',
                "",
                "Loose notes written before the tracker touched the page.",
            ]
        ),
    }


def test_tracker_state_ready_for_task_timeline_write_initialises_timeline_log_without_dates():
    tracker_state = _tracker_state_with_root_task()
    notion_client = _FakeNotionMcpClient(
        fetched_page_content_by_id={
            "22222222222222222222222222222222": "\n".join(
                [
                    "## Timeline log",
                    "Loose notes already under the heading.",
                ]
            )
        }
    )

    updated_tracker_state, operation_keys = asyncio.run(
        _tracker_state_ready_for_task_timeline_write(
            task_id="ALOVYA-1",
            entry_date="2026-05-26",
            tracker_state=tracker_state,
            notion_client=notion_client,
        )
    )

    assert operation_keys == ["initialise_timeline_log:task:ALOVYA-1:2026-05-26"]
    assert updated_tracker_state["tasks"]["ALOVYA-1"]["timeline_entries"][0]["entry_date"] == "2026-05-26"
    assert notion_client.calls[0].arguments["new_str"] == "\n".join(
        [
            "## Timeline log",
            '### <mention-date start="2026-05-26"/>',
            "",
            "Loose notes already under the heading.",
        ]
    )


def test_tracker_state_ready_for_task_timeline_write_keeps_usable_timeline_log():
    tracker_state = _tracker_state_with_root_task()
    notion_client = _FakeNotionMcpClient(
        fetched_page_content_by_id={
            "22222222222222222222222222222222": "\n".join(
                [
                    "## Timeline log",
                    '### <mention-date start="2026-05-25"/>',
                    "- Existing log.",
                ]
            )
        }
    )

    updated_tracker_state, operation_keys = asyncio.run(
        _tracker_state_ready_for_task_timeline_write(
            task_id="ALOVYA-1",
            entry_date="2026-05-26",
            tracker_state=tracker_state,
            notion_client=notion_client,
        )
    )

    assert operation_keys == []
    assert notion_client.calls == []
    assert updated_tracker_state["tasks"]["ALOVYA-1"]["timeline_entries"] == [
        {
            "entry_date": "2026-05-25",
            "heading": '<mention-date start="2026-05-25"/>',
            "lines": [],
        }
    ]


def test_raise_if_call_plan_has_blocked_operations_rejects_plan_before_writes():
    call_plan = NotionMcpCallPlan.from_snapshot(
        {
            "calls": [],
            "blocked_operations": [
                {
                    "operation_key": "create_synthesis_page:synthesis:onnx_qdq",
                    "reason": "Capture page id for synthesis:onnx_qdq.",
                }
            ],
        }
    )

    with pytest.raises(ValueError, match="blocked_operations"):
        _raise_if_call_plan_has_blocked_operations(call_plan)


def test_repair_operation_keys_include_changed_tasks_ancestors_and_landing_page():
    tracker_state = {
        "tasks": {
            "ALOVYA-1": {
                "task_id": "ALOVYA-1",
                "parent_task_id": None,
            },
            "ALOVYA-2": {
                "task_id": "ALOVYA-2",
                "parent_task_id": "ALOVYA-1",
            },
            "ALOVYA-3": {
                "task_id": "ALOVYA-3",
                "parent_task_id": "ALOVYA-2",
            },
        }
    }

    operation_keys = _repair_operation_keys_for_reconciled_task_pages(
        tracker_state=tracker_state,
        task_graph_changes=[
            {
                "task_id": "ALOVYA-3",
                "fields": {
                    "configured_priority": {
                        "before": "P2",
                        "after": "P1",
                    }
                },
            }
        ],
    )

    assert operation_keys == [
        "replace:landing_page",
        "replace:completed_landing_page",
        "update_properties:task:ALOVYA-1",
        "update_properties:task:ALOVYA-2",
        "update_properties:task:ALOVYA-3",
    ]


class _FakeNotionMcpClient:
    def __init__(
        self,
        results: list[dict] | None = None,
        database_rows: list[dict] | None = None,
        fetched_page_content_by_id: dict[str, str] | None = None,
    ):
        self.calls = []
        self.database_rows = list(database_rows or [])
        self.fetched_page_content_by_id = fetched_page_content_by_id or {}
        self.fetched_pages = []
        self.queries = []
        self.view_queries = []
        self.results = list(results or [])

    async def fetch_task_page_content(self, page_id: str):
        self.fetched_pages.append(page_id)
        return self.fetched_page_content_by_id.get(page_id, "")

    async def query_data_source(self, data_source_url: str, query: str):
        self.queries.append({"data_source_url": data_source_url, "query": query})
        return list(self.database_rows)

    async def query_database_view(self, view_url: str):
        self.view_queries.append(view_url)
        return list(self.database_rows)

    async def send_call(self, tool_call: NotionMcpToolCall):
        self.calls.append(tool_call)
        if self.results:
            return self.results.pop(0)
        return {}


def _tracker_state_with_root_task() -> dict:
    work_graph = TaskDependencyGraph()
    work_graph.landing_page.notion_page_id = "11111111111111111111111111111111"
    work_graph.add_task(
        TaskPageMetadata(
            task_id="ALOVYA-1",
            title="Root task",
            configured_priority=Priority.P1,
            status=TaskStatus.ACTIVE,
            notion_page_id="22222222222222222222222222222222",
        )
    )
    return work_graph.to_snapshot()


def _tracker_state_with_root_and_child_task() -> dict:
    work_graph = TaskDependencyGraph()
    work_graph.landing_page.notion_page_id = "11111111111111111111111111111111"
    work_graph.add_task(
        TaskPageMetadata(
            task_id="ALOVYA-1",
            title="Root task",
            configured_priority=Priority.P1,
            status=TaskStatus.ACTIVE,
            notion_page_id="22222222222222222222222222222222",
        )
    )
    work_graph.add_task(
        TaskPageMetadata(
            task_id="ALOVYA-2",
            title="Child task",
            configured_priority=Priority.P1,
            status=TaskStatus.ACTIVE,
            notion_page_id="33333333333333333333333333333333",
        )
    )
    work_graph.link_parent_to_child(parent_task_id="ALOVYA-1", child_task_id="ALOVYA-2")
    return work_graph.to_snapshot()


def _fetched_task_page(
    ticket_id: str,
    title: str,
    priority: str,
    status: str,
    parent_urls: list[str],
) -> str:
    return "\n".join(
        [
            "<page>",
            "<properties>",
            json.dumps(
                {
                    "Ticket ID": ticket_id,
                    "Ticket page": title,
                    "Priority": priority,
                    "Status": status,
                    "Parent": json.dumps(parent_urls),
                }
            ),
            "</properties>",
            "<content>",
            "## Timeline log",
            "</content>",
            "</page>",
        ]
    )
