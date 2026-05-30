import json
from argparse import Namespace

import pytest

from notion_task_tracker.build_tracker_command import build_tracker_command_from_cli_action, ticket_ids_from_numbers


def test_reconcile_action_builds_refresh_command():
    command = build_tracker_command_from_cli_action(_arguments(reconcile_from_notion=True))

    assert command == {"command": "reconcile_from_notion"}


def test_read_action_builds_read_command_for_all_ticket_numbers():
    command = build_tracker_command_from_cli_action(_arguments(read=True, ticket_number=[67, 68]))

    assert command == {
        "command": "read_tasks",
        "task_ids": ["ALOVYA-67", "ALOVYA-68"],
    }


def test_work_action_builds_work_command_for_one_ticket_number():
    command = build_tracker_command_from_cli_action(_arguments(work=True, ticket_number=[67]))

    assert command == {
        "command": "work_task",
        "task_ids": ["ALOVYA-67"],
    }


def test_log_action_builds_timeline_command_from_content_path(tmp_path):
    content_path = tmp_path / "content.json"
    content_path.write_text(
        json.dumps({
            "subheading": "Implementation notes",
            "blocks": [
                {
                    "type": "paragraph",
                    "text": "Added explicit CLI actions.",
                }
            ],
        }),
        encoding="utf-8",
    )

    command = build_tracker_command_from_cli_action(
        _arguments(
            log=True,
            ticket_number=[67],
            content_path=str(content_path),
            entry_date="2026-05-30",
        )
    )

    assert command == {
        "command": "append_task_timeline_log",
        "task_id": "ALOVYA-67",
        "timeline_entry": {
            "entry_date": "2026-05-30",
            "heading": '<mention-date start="2026-05-30"/>',
            "subheading": "Implementation notes",
            "blocks": [
                {
                    "type": "paragraph",
                    "text": "Added explicit CLI actions.",
                }
            ],
        },
    }


def test_child_action_builds_task_creation_command_from_scalar_flags(tmp_path):
    content_path = tmp_path / "content.json"
    content_path.write_text(
        json.dumps({
            "blocks": [
                {
                    "type": "paragraph",
                    "text": "Spawned a child task for the CLI parser.",
                }
            ],
        }),
        encoding="utf-8",
    )

    command = build_tracker_command_from_cli_action(
        _arguments(
            child=True,
            parent_ticket_number=67,
            title="Add explicit CLI actions",
            priority="P2",
            content_path=str(content_path),
            entry_date="2026-05-30",
        )
    )

    assert command == {
        "command": "create_child_task",
        "parent_task_id": "ALOVYA-67",
        "child_task": {
            "title": "Add explicit CLI actions",
            "configured_priority": "P2",
            "status": "Active",
        },
        "parent_timeline_entry": {
            "entry_date": "2026-05-30",
            "heading": '<mention-date start="2026-05-30"/>',
            "blocks": [
                {
                    "type": "paragraph",
                    "text": "Spawned a child task for the CLI parser.",
                }
            ],
        },
    }


def test_synthesis_action_keeps_rich_sources_inside_content_payload(tmp_path):
    content_path = tmp_path / "content.json"
    content_path.write_text(
        json.dumps({
            "summary": "Reusable tracker CLI design.",
            "sources": [
                {
                    "source_type": "Notion page",
                    "label": "ALOVYA-67",
                    "page_key": "task:ALOVYA-67",
                }
            ],
            "lines": ["Actions freeze schemas; content remains free-form."],
        }),
        encoding="utf-8",
    )

    command = build_tracker_command_from_cli_action(
        _arguments(
            synth=True,
            synthesis_key="explicit_tracker_cli",
            title="Explicit tracker CLI",
            content_path=str(content_path),
        )
    )

    assert command == {
        "command": "create_synthesis_page",
        "synthesis_key": "explicit_tracker_cli",
        "title": "Explicit tracker CLI",
        "summary": "Reusable tracker CLI design.",
        "sources": [
            {
                "source_type": "Notion page",
                "label": "ALOVYA-67",
                "page_key": "task:ALOVYA-67",
            }
        ],
        "lines": ["Actions freeze schemas; content remains free-form."],
    }


def test_ticket_ids_from_numbers_rejects_invalid_ticket_numbers():
    with pytest.raises(ValueError) as error:
        ticket_ids_from_numbers([0])

    assert str(error.value) == "Ticket numbers must be positive"


def _arguments(**overrides):
    values = {
        "reconcile_from_notion": False,
        "read": False,
        "work": False,
        "log": False,
        "complete": False,
        "cancel": False,
        "parent": False,
        "child": False,
        "sibling": False,
        "misc": False,
        "synth": False,
        "ticket_number": [],
        "parent_ticket_number": None,
        "sibling_ticket_number": None,
        "title": None,
        "priority": "P1",
        "content_path": None,
        "synthesis_key": None,
        "entry_date": "2026-05-30",
    }
    values.update(overrides)
    return Namespace(**values)
