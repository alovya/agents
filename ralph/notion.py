from __future__ import annotations

import copy
import json
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

import yaml

from ralph.plan_selection import (
    TaskSelection,
    read_tasks_from_ledger,
    ticket_number_from_ntt_task_id,
)


def materialise_and_validate_notion_task_graph(job: Any, ledger: dict[str, Any]) -> dict[str, Any]:
    """Create the complete NTT graph before any worker receives a prompt."""
    materialisation_path = job.job_path / "notion-materialisation"
    materialisation_path.mkdir(parents=True, exist_ok=True)

    _require_parent_is_available_for_ralph_children(
        ntt_parent_task_id=ledger["ntt_parent_task_id"],
        ntt_ticket_prefix=ledger["ntt_ticket_prefix"],
        output_path=materialisation_path / "parent-read.json",
    )
    materialised_ledger = _create_missing_notion_children(
        job=job,
        ledger=ledger,
        materialisation_path=materialisation_path,
    )
    _replace_every_notion_dependency_set(
        ledger=materialised_ledger,
        materialisation_path=materialisation_path,
    )
    _require_notion_children_match_ledger(
        ledger=materialised_ledger,
        materialisation_path=materialisation_path,
    )
    return _reconcile_completed_notion_tasks(job=job, ledger=materialised_ledger)


def complete_notion_task_after_accepting_worker(
    selection: TaskSelection,
    task_path: Path,
    commit_hash: str,
) -> None:
    ntt_task_id = _require_materialised_notion_task_id(selection.task)
    content_path = _write_notion_content_file(
        task_path=task_path,
        log_name="complete",
        content={
            "title": "Ralph task accepted",
            "blocks": [
                {
                    "type": "paragraph",
                    "text": (
                        f"Accepted Ralph task {selection.task['ralph_task_id']} "
                        f"at commit {commit_hash}."
                    ),
                }
            ],
        },
    )
    output_path = task_path / "notion-complete-output.json"
    command = [
        _resolve_notion_tracker_command_path(),
        "--complete",
        "--ticket-number",
        ticket_number_from_ntt_task_id(
            ntt_task_id,
            selection.ntt_ticket_prefix,
        ),
        "--content-path",
        str(content_path),
        "--output-path",
        str(output_path),
    ]
    _run_notion_tracker_command(command)


def _require_parent_is_available_for_ralph_children(
    ntt_parent_task_id: str,
    ntt_ticket_prefix: str,
    output_path: Path,
) -> None:
    parent = _read_notion_task(
        ntt_parent_task_id,
        ntt_ticket_prefix,
        output_path,
    )
    if parent["parent_task_id"] is None:
        pass
    if parent["status"] not in {"Active", "Pending"}:
        raise RuntimeError(
            f"NTT parent {ntt_parent_task_id} must be active before Ralph materialises children."
        )
    if _read_relation_urls(parent, "Dependencies"):
        raise RuntimeError(f"NTT parent {ntt_parent_task_id} must have no dependencies.")
    if _read_relation_urls(parent, "Dependants"):
        raise RuntimeError(f"NTT parent {ntt_parent_task_id} must have no dependants.")


def _create_missing_notion_children(
    job: Any,
    ledger: dict[str, Any],
    materialisation_path: Path,
) -> dict[str, Any]:
    updated_ledger = copy.deepcopy(ledger)
    for task in read_tasks_from_ledger(updated_ledger):
        if task["ntt_task_id"] is not None:
            continue

        ralph_task_id = task["ralph_task_id"]
        output_path = materialisation_path / f"{ralph_task_id}-create.json"
        command = [
            _resolve_notion_tracker_command_path(),
            "--child",
            "--parent-ticket-number",
            ticket_number_from_ntt_task_id(
                updated_ledger["ntt_parent_task_id"],
                updated_ledger["ntt_ticket_prefix"],
            ),
            "--title",
            task["title"],
            "--output-path",
            str(output_path),
        ]
        completed_process = _run_notion_tracker_command(command)
        _write_text(
            materialisation_path / f"{ralph_task_id}-create-stdout.txt",
            completed_process.stdout,
        )
        task["ntt_task_id"] = _extract_created_notion_task_id(output_path)
        _write_yaml_file(job.ledger_path, updated_ledger)
    return updated_ledger


def _replace_every_notion_dependency_set(
    ledger: dict[str, Any],
    materialisation_path: Path,
) -> None:
    ntt_task_id_by_ralph_task_id = {
        task["ralph_task_id"]: _require_materialised_notion_task_id(task)
        for task in read_tasks_from_ledger(ledger)
    }
    for task in read_tasks_from_ledger(ledger):
        ralph_task_id = task["ralph_task_id"]
        command = [
            _resolve_notion_tracker_command_path(),
            "--set-dependencies",
            "--ticket-number",
            ticket_number_from_ntt_task_id(
                ntt_task_id_by_ralph_task_id[ralph_task_id],
                ledger["ntt_ticket_prefix"],
            ),
            "--output-path",
            str(materialisation_path / f"{ralph_task_id}-dependencies.json"),
        ]
        for dependency_task_id in task.get("depends_on") or []:
            command.extend([
                "--dependency-ticket-number",
                ticket_number_from_ntt_task_id(
                    ntt_task_id_by_ralph_task_id[dependency_task_id],
                    ledger["ntt_ticket_prefix"],
                ),
            ])
        _run_notion_tracker_command(command)


def _require_notion_children_match_ledger(
    ledger: dict[str, Any],
    materialisation_path: Path,
) -> None:
    parent_task_id = ledger["ntt_parent_task_id"]
    expected_task_ids = {
        _require_materialised_notion_task_id(task)
        for task in read_tasks_from_ledger(ledger)
    }
    observed_parent = _read_notion_task(
        parent_task_id,
        ledger["ntt_ticket_prefix"],
        materialisation_path / "parent-validated.json",
    )
    if set(observed_parent["child_task_ids"]) != expected_task_ids:
        raise RuntimeError(
            f"NTT children for {parent_task_id} do not match the Ralph ledger."
        )

    observed_tasks_by_ntt_task_id: dict[str, dict[str, Any]] = {}
    for task in read_tasks_from_ledger(ledger):
        ntt_task_id = _require_materialised_notion_task_id(task)
        observed_task = _read_notion_task(
            ntt_task_id,
            ledger["ntt_ticket_prefix"],
            materialisation_path / f"{task['ralph_task_id']}-validated.json",
        )
        if observed_task["parent_task_id"] != parent_task_id:
            raise RuntimeError(
                f"NTT task {ntt_task_id} is not an immediate child of {parent_task_id}."
            )
        observed_tasks_by_ntt_task_id[ntt_task_id] = observed_task

    notion_url_by_ntt_task_id = {
        ntt_task_id: observed_task["notion_url"]
        for ntt_task_id, observed_task in observed_tasks_by_ntt_task_id.items()
    }
    for task in read_tasks_from_ledger(ledger):
        ntt_task_id = _require_materialised_notion_task_id(task)
        expected_dependency_page_ids = {
            _notion_page_id_from_url(notion_url_by_ntt_task_id[
                _require_materialised_notion_task_id(
                    _find_task(ledger, dependency_task_id)
                )
            ])
            for dependency_task_id in task.get("depends_on") or []
        }
        observed_dependency_page_ids = {
            _notion_page_id_from_url(notion_url)
            for notion_url in _read_relation_urls(
                observed_tasks_by_ntt_task_id[ntt_task_id], "Dependencies"
            )
        }
        if observed_dependency_page_ids != expected_dependency_page_ids:
            raise RuntimeError(
                f"NTT dependencies for {ntt_task_id} do not match the Ralph ledger."
            )


def _read_relation_urls(task: dict[str, Any], property_name: str) -> list[str]:
    full_page_content = task["full_page_content"]
    properties_match = re.search(
        r"<properties>\s*(?P<properties>\{.*?\})\s*</properties>",
        full_page_content,
        re.DOTALL,
    )
    if properties_match is None:
        raise RuntimeError(
            f"NTT read for {task['task_id']} has no readable properties."
        )
    properties = json.loads(properties_match.group("properties"))
    relation_urls = json.loads(properties[property_name])
    if not isinstance(relation_urls, list):
        raise RuntimeError(
            f"NTT property {property_name} for {task['task_id']} is not a list."
        )
    return relation_urls


def _notion_page_id_from_url(notion_url: str) -> str:
    match = re.search(r"(?P<page_id>[0-9a-f]{32})$", notion_url.replace("-", ""))
    if match is None:
        raise RuntimeError(f"Could not identify a Notion page id in {notion_url}.")
    return match.group("page_id")


def _reconcile_completed_notion_tasks(job: Any, ledger: dict[str, Any]) -> dict[str, Any]:
    updated_ledger = copy.deepcopy(ledger)
    changed = False
    for task in read_tasks_from_ledger(updated_ledger):
        tracker_task = _read_notion_task(
            _require_materialised_notion_task_id(task),
            ledger["ntt_ticket_prefix"],
            job.job_path / "notion-materialisation" / f"{task['ralph_task_id']}-reconcile.json",
        )
        if task["status"] == "done" and tracker_task["status"] != "Completed":
            raise RuntimeError(
                f"Ralph task {task['ralph_task_id']} is done but its NTT task is "
                f"{tracker_task['status']}."
            )
        if task["status"] == "pending" and tracker_task["status"] == "Completed":
            task["status"] = "done"
            changed = True
    if changed:
        _write_yaml_file(job.ledger_path, updated_ledger)
    return updated_ledger


def _read_notion_task(
    ntt_task_id: str,
    ntt_ticket_prefix: str,
    output_path: Path,
) -> dict[str, Any]:
    command = [
        _resolve_notion_tracker_command_path(),
        "--read-all",
        "--ticket-number",
        ticket_number_from_ntt_task_id(ntt_task_id, ntt_ticket_prefix),
        "--output-path",
        str(output_path),
    ]
    _run_notion_tracker_command(command)
    summary = json.loads(output_path.read_text(encoding="utf-8"))
    tasks = summary.get("tasks")
    if not isinstance(tasks, list) or len(tasks) != 1:
        raise RuntimeError(f"NTT read for {ntt_task_id} did not return exactly one task.")
    return tasks[0]


def _find_task(ledger: dict[str, Any], ralph_task_id: str) -> dict[str, Any]:
    for task in read_tasks_from_ledger(ledger):
        if task["ralph_task_id"] == ralph_task_id:
            return task
    raise ValueError(f"Unknown Ralph task id: {ralph_task_id}")


def _require_materialised_notion_task_id(task: dict[str, Any]) -> str:
    ntt_task_id = task["ntt_task_id"]
    if ntt_task_id is None:
        raise RuntimeError(
            f"Ralph task {task['ralph_task_id']} has no materialised NTT task."
        )
    return ntt_task_id


def _extract_created_notion_task_id(output_path: Path) -> str:
    summary = json.loads(output_path.read_text(encoding="utf-8"))
    notion_operations = summary.get("notion_operations")
    if not isinstance(notion_operations, list):
        raise RuntimeError("NTT task creation summary has no notion_operations list.")
    for operation in notion_operations:
        if isinstance(operation, str) and operation.startswith("update_properties:task:"):
            return operation.removeprefix("update_properties:task:")
    raise RuntimeError("NTT task creation summary does not identify the created task.")


def _write_notion_content_file(
    task_path: Path,
    log_name: str,
    content: dict[str, Any],
) -> Path:
    content_path = task_path / f"notion-{log_name}-content.json"
    content_path.write_text(
        json.dumps(content, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    return content_path


def _run_notion_tracker_command(
    command: list[str],
) -> subprocess.CompletedProcess[str]:
    completed_process = subprocess.run(
        command,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )
    if completed_process.returncode != 0:
        raise RuntimeError(
            f"Notion task tracker command failed:\n{completed_process.stdout}"
        )
    return completed_process


def _resolve_notion_tracker_command_path() -> str:
    command_path = shutil.which("ntt")
    if command_path is not None:
        return command_path
    raise RuntimeError("Notion task tracker command is not available on PATH: ntt")


def _write_text(text_path: Path, text: str) -> None:
    text_path.parent.mkdir(parents=True, exist_ok=True)
    text_path.write_text(text)


def _write_yaml_file(yaml_path: Path, value: dict[str, Any]) -> None:
    yaml_path.write_text(yaml.safe_dump(value, sort_keys=False))
