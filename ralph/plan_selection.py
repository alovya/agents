from __future__ import annotations

import re
from typing import Any

from dataclasses import dataclass


ALOVYA_TASK_ID_PATTERN = re.compile(r"^ALOVYA-(?P<ticket_number>\d+)$")
PLAN_COMMAND_ITEM_PATTERN = re.compile(r"^\s*-\s+(?P<command>.+?)\s*$")
TASK_BLOCK_PATTERN = re.compile(
    r"<!--\s*ralph-task:start\s+(?P<task_id>[A-Za-z0-9_.-]+)\s*-->\n"
    r"(?P<body>.*?)"
    r"<!--\s*ralph-task:end\s+(?P=task_id)\s*-->",
    re.DOTALL,
)
SHARED_BLOCK_PATTERN = re.compile(
    r"<!--\s*ralph-shared:start\s*-->\n"
    r"(?P<body>.*?)"
    r"<!--\s*ralph-shared:end\s*-->",
    re.DOTALL,
)


@dataclass(frozen=True)
class TaskSelection:
    task: dict[str, Any]
    shared_plan_context: str
    active_task_plan_context: str


def select_next_task_from_plan_and_ledger(
    ledger: dict[str, Any],
    plan_text: str,
) -> TaskSelection | None:
    tasks = read_tasks_from_ledger(ledger)
    shared_plan_context = _extract_shared_plan_context(plan_text)
    task_plan_contexts = _extract_task_plan_contexts(plan_text)
    task_command_contracts = _derive_task_command_contracts_from_plan(task_plan_contexts)
    _validate_plan_and_ledger_match(tasks, task_plan_contexts)

    completed_task_ids = {task["id"] for task in tasks if task.get("status") == "done"}
    for task in tasks:
        if task.get("status") != "pending":
            continue
        depends_on = task.get("depends_on") or []
        if all(task_id in completed_task_ids for task_id in depends_on):
            task_with_plan_commands = _attach_plan_command_contract_to_task(
                task=task,
                allowed_bash_commands=task_command_contracts[task["id"]]["allowed_bash_commands"],
                verification_commands=task_command_contracts[task["id"]]["verification_commands"],
            )
            return TaskSelection(
                task=task_with_plan_commands,
                shared_plan_context=shared_plan_context,
                active_task_plan_context=task_plan_contexts[task["id"]],
            )
    return None


def read_tasks_from_ledger(ledger: dict[str, Any]) -> list[dict[str, Any]]:
    tasks = ledger.get("tasks")
    if not isinstance(tasks, list):
        raise ValueError("ledger.yaml must contain a tasks list.")
    for task in tasks:
        _validate_task_shape(task)
    _validate_planned_notion_task_relationships(tasks)
    return tasks


def refresh_task_selection_from_ledger(
    ledger: dict[str, Any],
    selection: TaskSelection,
) -> TaskSelection:
    refreshed_task = find_task_by_id(read_tasks_from_ledger(ledger), selection.task["id"])
    refreshed_task_with_plan_commands = _attach_plan_command_contract_to_task(
        task=refreshed_task,
        allowed_bash_commands=selection.task.get("allowed_bash_commands") or [],
        verification_commands=selection.task.get("verification_commands") or [],
    )
    return TaskSelection(
        task=refreshed_task_with_plan_commands,
        shared_plan_context=selection.shared_plan_context,
        active_task_plan_context=selection.active_task_plan_context,
    )


def find_task_by_id(tasks: list[dict[str, Any]], task_id: str) -> dict[str, Any]:
    for task in tasks:
        if task["id"] == task_id:
            return task
    raise ValueError(f"Unknown Ralph task id: {task_id}")


def is_alovya_task_id(value: str) -> bool:
    return ALOVYA_TASK_ID_PATTERN.match(value) is not None


def ticket_number_from_alovya_task_id(task_id: str) -> str:
    match = ALOVYA_TASK_ID_PATTERN.match(task_id)
    if match is None:
        raise ValueError(f"Expected ALOVYA task id, got: {task_id}")
    return match.group("ticket_number")


def _validate_task_shape(task: Any) -> None:
    if not isinstance(task, dict):
        raise ValueError("Every ledger task must be a mapping.")
    for required_key in ["id", "title", "status"]:
        if not task.get(required_key):
            raise ValueError(f"Every ledger task must have {required_key}.")
    for plan_command_key in ["allowed_bash_commands", "verification_commands"]:
        if plan_command_key in task:
            raise ValueError(f"Ledger task {task['id']} must keep {plan_command_key} in PLAN.md.")
    if task["status"] not in {"pending", "done", "blocked", "aborted"}:
        raise ValueError(f"Invalid task status for {task['id']}: {task['status']}")
    if _contains_forbidden_plan_field(task):
        raise ValueError(f"Ledger task {task['id']} contains plan-like prose fields.")
    _validate_notion_task_shape(task)


def _validate_notion_task_shape(task: dict[str, Any]) -> None:
    notion_task = task.get("notion_task")
    if notion_task is None:
        return
    if not isinstance(notion_task, dict):
        raise ValueError(f"notion_task for {task['id']} must be a mapping.")
    if not isinstance(notion_task.get("planned"), bool):
        raise ValueError(f"notion_task.planned for {task['id']} must be boolean.")
    if notion_task["planned"] is False:
        return
    if notion_task.get("relationship") not in {"child", "sibling"}:
        raise ValueError(f"notion_task.relationship for {task['id']} must be child or sibling.")
    for required_key in ["related_to", "title"]:
        if not isinstance(notion_task.get(required_key), str) or not notion_task[required_key].strip():
            raise ValueError(f"notion_task.{required_key} for {task['id']} must be a non-empty string.")
    materialised_task_id = notion_task.get("materialized_task_id")
    if materialised_task_id is not None and (
        not isinstance(materialised_task_id, str) or not is_alovya_task_id(materialised_task_id)
    ):
        raise ValueError(f"notion_task.materialized_task_id for {task['id']} must be null or an ALOVYA id.")


def _validate_planned_notion_task_relationships(tasks: list[dict[str, Any]]) -> None:
    task_ids = {task["id"] for task in tasks}
    for task in tasks:
        notion_task = task.get("notion_task")
        if not isinstance(notion_task, dict) or notion_task.get("planned") is not True:
            continue

        related_to = notion_task["related_to"]
        if is_alovya_task_id(related_to):
            continue
        if related_to not in task_ids:
            raise ValueError(f"notion_task.related_to for {task['id']} references unknown Ralph task {related_to}.")
        if related_to not in (task.get("depends_on") or []):
            raise ValueError(f"Task {task['id']} must depend on related Ralph task {related_to}.")


def _contains_forbidden_plan_field(value: Any) -> bool:
    if isinstance(value, dict):
        return any(key in {"plan", "context", "notes", "description", "implementation"} for key in value)
    return False


def _extract_shared_plan_context(plan_text: str) -> str:
    matches = list(SHARED_BLOCK_PATTERN.finditer(plan_text))
    if len(matches) != 1:
        raise ValueError("PLAN.md must contain exactly one ralph-shared block.")
    return matches[0].group("body")


def _extract_task_plan_contexts(plan_text: str) -> dict[str, str]:
    task_plan_contexts: dict[str, str] = {}
    duplicate_task_ids: set[str] = set()
    for match in TASK_BLOCK_PATTERN.finditer(plan_text):
        task_id = match.group("task_id")
        if task_id in task_plan_contexts:
            duplicate_task_ids.add(task_id)
        task_plan_contexts[task_id] = match.group("body")
    if duplicate_task_ids:
        raise ValueError(f"Duplicate Ralph task blocks: {sorted(duplicate_task_ids)}")
    return task_plan_contexts


def _derive_task_command_contracts_from_plan(
    task_plan_contexts: dict[str, str],
) -> dict[str, dict[str, list[str]]]:
    return {
        task_id: {
            "allowed_bash_commands": _extract_plan_command_list(
                task_id=task_id,
                task_plan_context=task_plan_context,
                block_name="ralph-allowed-bash",
            ),
            "verification_commands": _extract_plan_command_list(
                task_id=task_id,
                task_plan_context=task_plan_context,
                block_name="ralph-verification",
            ),
        }
        for task_id, task_plan_context in task_plan_contexts.items()
    }


def _attach_plan_command_contract_to_task(
    task: dict[str, Any],
    allowed_bash_commands: list[str],
    verification_commands: list[str],
) -> dict[str, Any]:
    task_with_plan_commands = dict(task)
    task_with_plan_commands["allowed_bash_commands"] = allowed_bash_commands
    task_with_plan_commands["verification_commands"] = verification_commands
    return task_with_plan_commands


def _extract_plan_command_list(
    task_id: str,
    task_plan_context: str,
    block_name: str,
) -> list[str]:
    block_body = _extract_single_plan_command_block(
        task_id=task_id,
        task_plan_context=task_plan_context,
        block_name=block_name,
    )
    commands: list[str] = []
    malformed_lines: list[str] = []
    for line in block_body.splitlines():
        if not line.strip():
            continue
        match = PLAN_COMMAND_ITEM_PATTERN.match(line)
        if match is None:
            malformed_lines.append(line)
            continue
        commands.append(match.group("command"))
    if malformed_lines:
        raise ValueError(
            f"Task {task_id} {block_name} block must contain only '- <command>' lines: {malformed_lines}"
        )
    if not commands:
        raise ValueError(f"Task {task_id} {block_name} block must contain at least one command.")
    return commands


def _extract_single_plan_command_block(
    task_id: str,
    task_plan_context: str,
    block_name: str,
) -> str:
    command_block_pattern = re.compile(
        rf"<!--\s*{re.escape(block_name)}:start\s*-->\n"
        rf"(?P<body>.*?)"
        rf"<!--\s*{re.escape(block_name)}:end\s*-->",
        re.DOTALL,
    )
    matches = list(command_block_pattern.finditer(task_plan_context))
    if len(matches) != 1:
        raise ValueError(f"Task {task_id} must contain exactly one {block_name} block.")
    return matches[0].group("body")


def _validate_plan_and_ledger_match(
    tasks: list[dict[str, Any]],
    task_plan_contexts: dict[str, str],
) -> None:
    ledger_task_ids = {task["id"] for task in tasks}
    plan_task_ids = set(task_plan_contexts)
    missing_task_ids = sorted(ledger_task_ids - plan_task_ids)
    unknown_task_ids = sorted(plan_task_ids - ledger_task_ids)
    if missing_task_ids:
        raise ValueError(f"PLAN.md is missing Ralph task blocks: {missing_task_ids}")
    if unknown_task_ids:
        raise ValueError(f"PLAN.md contains task blocks absent from ledger.yaml: {unknown_task_ids}")
