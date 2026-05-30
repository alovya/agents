"""Build deterministic tracker commands from explicit CLI actions."""

from __future__ import annotations

import json
from argparse import Namespace
from datetime import date
from pathlib import Path
from typing import Any


WRITE_ACTIONS = {
    "log",
    "complete",
    "cancel",
    "parent",
    "child",
    "sibling",
    "misc",
    "synth",
}

READ_ACTIONS = {
    "read",
    "work",
}

MAINTENANCE_ACTIONS = {
    "reconcile_from_notion",
}


def selected_cli_action_from_arguments(arguments: Namespace) -> str | None:
    for action_name in [*sorted(MAINTENANCE_ACTIONS), *sorted(READ_ACTIONS), *sorted(WRITE_ACTIONS)]:
        if getattr(arguments, action_name, False):
            return action_name

    return None


def build_tracker_command_from_cli_action(arguments: Namespace) -> dict[str, Any]:
    action_name = selected_cli_action_from_arguments(arguments)
    if action_name is None:
        raise ValueError("Choose --reconcile-from-notion or one tracker action")
    if action_name == "reconcile_from_notion":
        return {"command": "reconcile_from_notion"}
    if action_name == "read":
        return _build_read_command(arguments)
    if action_name == "work":
        return _build_work_command(arguments)
    if action_name == "log":
        return _build_log_command(arguments)
    if action_name == "complete":
        return _build_complete_command(arguments)
    if action_name == "cancel":
        return _build_cancel_command(arguments)
    if action_name == "parent":
        return _build_parent_command(arguments)
    if action_name == "child":
        return _build_child_command(arguments)
    if action_name == "sibling":
        return _build_sibling_command(arguments)
    if action_name == "misc":
        return _build_miscellaneous_command(arguments)
    if action_name == "synth":
        return _build_synthesis_command(arguments)

    raise ValueError(f"CLI action {action_name!r} does not produce a tracker command")


def ticket_id_from_number(ticket_number: int) -> str:
    if ticket_number < 1:
        raise ValueError("Ticket numbers must be positive")

    return f"ALOVYA-{ticket_number}"


def ticket_ids_from_numbers(ticket_numbers: list[int]) -> list[str]:
    return [ticket_id_from_number(ticket_number) for ticket_number in ticket_numbers]


def _build_read_command(arguments: Namespace) -> dict[str, Any]:
    if not arguments.ticket_number:
        raise ValueError("--read requires at least one --ticket-number")

    return {
        "command": "read_tasks",
        "task_ids": ticket_ids_from_numbers(arguments.ticket_number),
    }


def _build_work_command(arguments: Namespace) -> dict[str, Any]:
    return {
        "command": "work_task",
        "task_ids": [_single_task_id_from_ticket_numbers(arguments.ticket_number)],
    }


def _build_log_command(arguments: Namespace) -> dict[str, Any]:
    return {
        "command": "append_task_timeline_log",
        "task_id": _single_task_id_from_ticket_numbers(arguments.ticket_number),
        "timeline_entry": _timeline_entry_from_content_path(arguments.content_path, arguments.entry_date),
    }


def _build_complete_command(arguments: Namespace) -> dict[str, Any]:
    return {
        "command": "complete_task",
        "task_id": _single_task_id_from_ticket_numbers(arguments.ticket_number),
        "timeline_entry": _timeline_entry_from_content_path(arguments.content_path, arguments.entry_date),
    }


def _build_cancel_command(arguments: Namespace) -> dict[str, Any]:
    return {
        "command": "cancel_task",
        "task_id": _single_task_id_from_ticket_numbers(arguments.ticket_number),
        "timeline_entry": _timeline_entry_from_content_path(arguments.content_path, arguments.entry_date),
    }


def _build_parent_command(arguments: Namespace) -> dict[str, Any]:
    command = {
        "command": "create_top_level_task",
        "task": _new_task_command(arguments.title, arguments.priority),
    }
    if arguments.content_path is not None:
        command["timeline_entry"] = _timeline_entry_from_content_path(arguments.content_path, arguments.entry_date)
    return command


def _build_child_command(arguments: Namespace) -> dict[str, Any]:
    command = {
        "command": "create_child_task",
        "parent_task_id": ticket_id_from_number(arguments.parent_ticket_number),
        "child_task": _new_task_command(arguments.title, arguments.priority),
    }
    if arguments.content_path is not None:
        command["parent_timeline_entry"] = _timeline_entry_from_content_path(arguments.content_path, arguments.entry_date)
    return command


def _build_sibling_command(arguments: Namespace) -> dict[str, Any]:
    command = {
        "command": "create_sibling_task",
        "sibling_task_id": ticket_id_from_number(arguments.sibling_ticket_number),
        "sibling_task": _new_task_command(arguments.title, arguments.priority),
    }
    if arguments.content_path is not None:
        command["timeline_entry"] = _timeline_entry_from_content_path(arguments.content_path, arguments.entry_date)
    return command


def _build_miscellaneous_command(arguments: Namespace) -> dict[str, Any]:
    content = _read_json_object(arguments.content_path)
    return {
        "command": "append_miscellaneous_note",
        "note_date": _entry_date_from_arguments(arguments.entry_date),
        "lines": _lines_from_content(content),
    }


def _build_synthesis_command(arguments: Namespace) -> dict[str, Any]:
    content = _read_json_object(arguments.content_path)
    return {
        "command": "create_synthesis_page",
        "synthesis_key": arguments.synthesis_key,
        "title": arguments.title,
        "summary": content.get("summary", ""),
        "sources": list(content.get("sources", [])),
        "lines": _lines_from_content(content),
    }


def _single_task_id_from_ticket_numbers(ticket_numbers: list[int]) -> str:
    if len(ticket_numbers) != 1:
        raise ValueError("This action requires exactly one --ticket-number")

    return ticket_id_from_number(ticket_numbers[0])


def _new_task_command(title: str | None, priority: str) -> dict[str, str]:
    if not title:
        raise ValueError("Task creation requires --title")

    return {
        "title": title,
        "configured_priority": priority,
        "status": "Active",
    }


def _timeline_entry_from_content_path(content_path: str | None, entry_date: str | None) -> dict[str, Any]:
    if content_path is None:
        raise ValueError("This action requires --content-path")

    content = _read_json_object(content_path)
    resolved_entry_date = _entry_date_from_arguments(entry_date)
    timeline_entry = {
        "entry_date": resolved_entry_date,
        "heading": f'<mention-date start="{resolved_entry_date}"/>',
    }
    if content.get("subheading") is not None:
        timeline_entry["subheading"] = content["subheading"]
    if content.get("blocks") is not None:
        timeline_entry["blocks"] = list(content["blocks"])
    if content.get("lines") is not None:
        timeline_entry["lines"] = list(content["lines"])
    if "blocks" not in timeline_entry and "lines" not in timeline_entry:
        raise ValueError("Timeline content must include blocks or lines")
    return timeline_entry


def _lines_from_content(content: dict[str, Any]) -> list[str]:
    if content.get("lines") is not None:
        return list(content["lines"])

    if content.get("blocks") is not None:
        return [_line_from_content_block(block) for block in content["blocks"]]

    raise ValueError("Content must include lines or blocks")


def _line_from_content_block(block: Any) -> str:
    if not isinstance(block, dict):
        raise ValueError("Each content block must be an object")
    if not isinstance(block.get("text"), str):
        raise ValueError("Each content block must include string text")

    return block["text"]


def _entry_date_from_arguments(entry_date: str | None) -> str:
    return entry_date or date.today().isoformat()


def _read_json_object(source_path: str | Path | None) -> dict[str, Any]:
    if source_path is None:
        raise ValueError("This action requires --content-path")

    content = json.loads(Path(source_path).read_text(encoding="utf-8"))
    if not isinstance(content, dict):
        raise ValueError("Content path must contain a JSON object")

    return content
