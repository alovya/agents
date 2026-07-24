from __future__ import annotations

import re
from typing import Any

from dataclasses import dataclass


OBSOLETE_TASK_CONTROL_FIELDS = frozenset({
    "allowed_bash_commands",
    "touchable_paths",
    "verification_commands",
})
OBSOLETE_PLAN_CONTROL_MARKERS = (
    "ralph-allowed-bash",
    "ralph-verification",
)
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
    ntt_ticket_prefix: str
    shared_plan_context: str
    active_task_plan_context: str


def select_next_task_from_plan_and_ledger(
    ledger: dict[str, Any],
    plan_text: str,
) -> TaskSelection | None:
    tasks = read_tasks_from_ledger(ledger)
    shared_plan_context = _extract_shared_plan_context(plan_text)
    task_plan_contexts = _extract_task_plan_contexts(plan_text)
    _reject_obsolete_plan_control_markers(task_plan_contexts)
    _validate_plan_and_ledger_match(tasks, task_plan_contexts)

    completed_task_ids = {task["ralph_task_id"] for task in tasks if task.get("status") == "done"}
    for task in tasks:
        if task.get("status") != "pending":
            continue
        depends_on = task.get("depends_on") or []
        if all(task_id in completed_task_ids for task_id in depends_on):
            return TaskSelection(
                task=task,
                ntt_ticket_prefix=ledger["ntt_ticket_prefix"],
                shared_plan_context=shared_plan_context,
                active_task_plan_context=task_plan_contexts[task["ralph_task_id"]],
            )
    return None


def read_tasks_from_ledger(ledger: dict[str, Any]) -> list[dict[str, Any]]:
    ntt_ticket_prefix = ledger.get("ntt_ticket_prefix")
    if not isinstance(ntt_ticket_prefix, str) or not ntt_ticket_prefix:
        raise ValueError("ledger.yaml must contain a non-empty ntt_ticket_prefix.")
    ntt_parent_task_id = ledger.get("ntt_parent_task_id")
    if not isinstance(ntt_parent_task_id, str) or not is_ntt_task_id(
        ntt_parent_task_id,
        ntt_ticket_prefix,
    ):
        raise ValueError(
            "ledger.yaml must contain ntt_parent_task_id using its ntt_ticket_prefix."
        )
    tasks = ledger.get("tasks")
    if not isinstance(tasks, list):
        raise ValueError("ledger.yaml must contain a tasks list.")
    for task in tasks:
        _validate_task_shape(task, ntt_ticket_prefix)
    _validate_task_ids_are_unique(tasks)
    _validate_ntt_task_ids_are_unique(tasks)
    _validate_task_dependencies(tasks)
    _validate_dependency_graph_has_no_cycles(tasks)
    return tasks


def refresh_task_selection_from_ledger(
    ledger: dict[str, Any],
    selection: TaskSelection,
) -> TaskSelection:
    refreshed_task = find_task_by_id(read_tasks_from_ledger(ledger), selection.task["ralph_task_id"])
    return TaskSelection(
        task=refreshed_task,
        ntt_ticket_prefix=ledger["ntt_ticket_prefix"],
        shared_plan_context=selection.shared_plan_context,
        active_task_plan_context=selection.active_task_plan_context,
    )


def find_task_by_id(tasks: list[dict[str, Any]], task_id: str) -> dict[str, Any]:
    for task in tasks:
        if task["ralph_task_id"] == task_id:
            return task
    raise ValueError(f"Unknown Ralph task id: {task_id}")


def is_ntt_task_id(value: str, ntt_ticket_prefix: str) -> bool:
    return _build_ntt_task_id_pattern(ntt_ticket_prefix).match(value) is not None


def ticket_number_from_ntt_task_id(task_id: str, ntt_ticket_prefix: str) -> str:
    match = _build_ntt_task_id_pattern(ntt_ticket_prefix).match(task_id)
    if match is None:
        raise ValueError(
            f"Expected NTT task id with prefix {ntt_ticket_prefix}, got: {task_id}"
        )
    return match.group("ticket_number")


def _build_ntt_task_id_pattern(ntt_ticket_prefix: str) -> re.Pattern[str]:
    return re.compile(
        rf"^{re.escape(ntt_ticket_prefix)}-(?P<ticket_number>\d+)$"
    )


def _validate_task_shape(task: Any, ntt_ticket_prefix: str) -> None:
    if not isinstance(task, dict):
        raise ValueError("Every ledger task must be a mapping.")
    for required_key in ["ralph_task_id", "title", "status", "ntt_task_id"]:
        if not task.get(required_key):
            if required_key == "ntt_task_id" and task.get(required_key) is None:
                continue
            raise ValueError(f"Every ledger task must have {required_key}.")
    obsolete_fields = sorted(OBSOLETE_TASK_CONTROL_FIELDS.intersection(task))
    if obsolete_fields:
        raise ValueError(f"Ledger task {task['ralph_task_id']} contains obsolete control fields: {obsolete_fields}")
    if task["status"] not in {"pending", "done", "blocked", "aborted"}:
        raise ValueError(f"Invalid task status for {task['ralph_task_id']}: {task['status']}")
    if _contains_forbidden_plan_field(task):
        raise ValueError(f"Ledger task {task['ralph_task_id']} contains plan-like prose fields.")
    ntt_task_id = task["ntt_task_id"]
    if ntt_task_id is not None and (
        not isinstance(ntt_task_id, str)
        or not is_ntt_task_id(ntt_task_id, ntt_ticket_prefix)
    ):
        raise ValueError(
            f"ntt_task_id for {task['ralph_task_id']} must be null or use "
            f"the {ntt_ticket_prefix} prefix."
        )
    if "id" in task or "notion_task" in task:
        raise ValueError(
            f"Ledger task {task['ralph_task_id']} contains obsolete task identity fields."
        )


def _validate_task_ids_are_unique(tasks: list[dict[str, Any]]) -> None:
    task_ids = [task["ralph_task_id"] for task in tasks]
    duplicate_task_ids = sorted({task_id for task_id in task_ids if task_ids.count(task_id) > 1})
    if duplicate_task_ids:
        raise ValueError(f"ledger.yaml contains duplicate Ralph task ids: {duplicate_task_ids}")


def _validate_ntt_task_ids_are_unique(tasks: list[dict[str, Any]]) -> None:
    ntt_task_ids = [
        task["ntt_task_id"]
        for task in tasks
        if task["ntt_task_id"] is not None
    ]
    duplicate_ntt_task_ids = sorted({
        ntt_task_id
        for ntt_task_id in ntt_task_ids
        if ntt_task_ids.count(ntt_task_id) > 1
    })
    if duplicate_ntt_task_ids:
        raise ValueError(
            f"ledger.yaml contains duplicate NTT task ids: {duplicate_ntt_task_ids}"
        )


def _validate_task_dependencies(tasks: list[dict[str, Any]]) -> None:
    task_ids = {task["ralph_task_id"] for task in tasks}
    for task in tasks:
        depends_on = task.get("depends_on") or []
        if not isinstance(depends_on, list) or not all(isinstance(task_id, str) for task_id in depends_on):
            raise ValueError(f"depends_on for {task['ralph_task_id']} must be a list of Ralph task ids.")
        unknown_dependency_ids = sorted(set(depends_on) - task_ids)
        if unknown_dependency_ids:
            raise ValueError(f"Task {task['ralph_task_id']} depends on unknown Ralph tasks: {unknown_dependency_ids}")


def _validate_dependency_graph_has_no_cycles(tasks: list[dict[str, Any]]) -> None:
    dependencies_by_task_id = {
        task["ralph_task_id"]: task.get("depends_on") or []
        for task in tasks
    }
    visiting: set[str] = set()
    visited: set[str] = set()

    def _visit_task(task_id: str) -> None:
        if task_id in visiting:
            raise ValueError(f"Ralph dependency graph contains a cycle at {task_id}.")
        if task_id in visited:
            return
        visiting.add(task_id)
        for dependency_task_id in dependencies_by_task_id[task_id]:
            _visit_task(dependency_task_id)
        visiting.remove(task_id)
        visited.add(task_id)

    for task_id in dependencies_by_task_id:
        _visit_task(task_id)


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


def _reject_obsolete_plan_control_markers(task_plan_contexts: dict[str, str]) -> None:
    for task_id, task_plan_context in task_plan_contexts.items():
        found_markers = [
            marker
            for marker in OBSOLETE_PLAN_CONTROL_MARKERS
            if marker in task_plan_context
        ]
        if found_markers:
            raise ValueError(f"PLAN.md task {task_id} contains obsolete control markers: {found_markers}")


def _validate_plan_and_ledger_match(
    tasks: list[dict[str, Any]],
    task_plan_contexts: dict[str, str],
) -> None:
    ledger_task_ids = {task["ralph_task_id"] for task in tasks}
    plan_task_ids = set(task_plan_contexts)
    missing_task_ids = sorted(ledger_task_ids - plan_task_ids)
    unknown_task_ids = sorted(plan_task_ids - ledger_task_ids)
    if missing_task_ids:
        raise ValueError(f"PLAN.md is missing Ralph task blocks: {missing_task_ids}")
    if unknown_task_ids:
        raise ValueError(f"PLAN.md contains task blocks absent from ledger.yaml: {unknown_task_ids}")
