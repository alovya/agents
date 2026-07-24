from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest
import yaml

from ralph.notion import (
    _extract_created_notion_task_id,
    _notion_page_id_from_url,
    _resolve_notion_tracker_command_path,
    complete_notion_task_after_accepting_worker,
    materialise_and_validate_notion_task_graph,
)
from ralph.tests.conftest import create_job_with_ledger, select_first_task


def _build_unmaterialised_ledger() -> dict:
    return {
        "version": 1,
        "job_name": "example",
        "ntt_ticket_prefix": "ALOVYA",
        "ntt_parent_task_id": "ALOVYA-89",
        "tasks": [
            {
                "ralph_task_id": "R1",
                "title": "Add parser",
                "status": "pending",
                "depends_on": [],
                "ntt_task_id": None,
            },
            {
                "ralph_task_id": "R2",
                "title": "Add command line entrypoint",
                "status": "pending",
                "depends_on": ["R1"],
                "ntt_task_id": None,
            },
        ],
    }


def test_materialises_every_child_and_dependency_before_returning(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ledger = _build_unmaterialised_ledger()
    job = create_job_with_ledger(tmp_path, ledger)
    observed_commands: list[list[str]] = []
    created_task_ids = iter(["ALOVYA-90", "ALOVYA-91"])

    def _run_notion_tracker_command_mock(
        command: list[str],
    ) -> subprocess.CompletedProcess[str]:
        observed_commands.append(command)
        if "--child" in command:
            output_path = Path(command[command.index("--output-path") + 1])
            created_task_id = next(created_task_ids)
            output_path.write_text(json.dumps({
                "notion_operations": [
                    f"update_properties:task:{created_task_id}",
                ]
            }))
        return subprocess.CompletedProcess(command, 0, "")

    monkeypatch.setattr(
        "ralph.notion._resolve_notion_tracker_command_path",
        lambda: "ntt",
    )
    monkeypatch.setattr(
        "ralph.notion._run_notion_tracker_command",
        _run_notion_tracker_command_mock,
    )
    monkeypatch.setattr(
        "ralph.notion._require_parent_is_available_for_ralph_children",
        lambda **_: None,
    )
    monkeypatch.setattr(
        "ralph.notion._require_notion_children_match_ledger",
        lambda **_: None,
    )
    monkeypatch.setattr(
        "ralph.notion._reconcile_completed_notion_tasks",
        lambda **arguments: arguments["ledger"],
    )

    materialised_ledger = materialise_and_validate_notion_task_graph(job, ledger)

    assert [
        task["ntt_task_id"] for task in materialised_ledger["tasks"]
    ] == ["ALOVYA-90", "ALOVYA-91"]
    assert [
        task["ntt_task_id"]
        for task in yaml.safe_load(job.ledger_path.read_text())["tasks"]
    ] == ["ALOVYA-90", "ALOVYA-91"]
    dependency_commands = [
        command for command in observed_commands if "--set-dependencies" in command
    ]
    assert len(dependency_commands) == 2
    assert "--dependency-ticket-number" not in dependency_commands[0]
    assert dependency_commands[1][-2:] == [
        "--dependency-ticket-number",
        "90",
    ]


def test_materialisation_resumes_without_recreating_recorded_children(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ledger = _build_unmaterialised_ledger()
    ledger["tasks"][0]["ntt_task_id"] = "ALOVYA-90"
    job = create_job_with_ledger(tmp_path, ledger)
    observed_commands: list[list[str]] = []

    def _run_notion_tracker_command_mock(
        command: list[str],
    ) -> subprocess.CompletedProcess[str]:
        observed_commands.append(command)
        if "--child" in command:
            output_path = Path(command[command.index("--output-path") + 1])
            output_path.write_text(json.dumps({
                "notion_operations": ["update_properties:task:ALOVYA-91"]
            }))
        return subprocess.CompletedProcess(command, 0, "")

    monkeypatch.setattr(
        "ralph.notion._resolve_notion_tracker_command_path",
        lambda: "ntt",
    )
    monkeypatch.setattr(
        "ralph.notion._run_notion_tracker_command",
        _run_notion_tracker_command_mock,
    )
    monkeypatch.setattr(
        "ralph.notion._require_parent_is_available_for_ralph_children",
        lambda **_: None,
    )
    monkeypatch.setattr(
        "ralph.notion._require_notion_children_match_ledger",
        lambda **_: None,
    )
    monkeypatch.setattr(
        "ralph.notion._reconcile_completed_notion_tasks",
        lambda **arguments: arguments["ledger"],
    )

    materialise_and_validate_notion_task_graph(job, ledger)

    child_commands = [
        command for command in observed_commands if "--child" in command
    ]
    assert len(child_commands) == 1
    assert "Add command line entrypoint" in child_commands[0]


def test_complete_uses_only_accepted_identity_and_commit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ledger = _build_unmaterialised_ledger()
    ledger["tasks"][0]["ntt_task_id"] = "ALOVYA-90"
    selection = select_first_task(ledger)
    observed_commands: list[list[str]] = []

    monkeypatch.setattr(
        "ralph.notion._resolve_notion_tracker_command_path",
        lambda: "ntt",
    )
    monkeypatch.setattr(
        "ralph.notion._run_notion_tracker_command",
        lambda command: (
            observed_commands.append(command)
            or subprocess.CompletedProcess(command, 0, "")
        ),
    )

    complete_notion_task_after_accepting_worker(
        selection=selection,
        task_path=tmp_path,
        commit_hash="a" * 40,
    )

    assert observed_commands[0][:4] == [
        "ntt",
        "--complete",
        "--ticket-number",
        "90",
    ]
    content_path = Path(
        observed_commands[0][observed_commands[0].index("--content-path") + 1]
    )
    content = json.loads(content_path.read_text())
    assert content["blocks"] == [{
        "type": "paragraph",
        "text": f"Accepted Ralph task R1 at commit {'a' * 40}.",
    }]


def test_extract_created_task_identity_uses_update_operation(
    tmp_path: Path,
) -> None:
    output_path = tmp_path / "output.json"
    output_path.write_text(json.dumps({
        "notion_operations": ["update_properties:task:ALOVYA-90"]
    }))

    assert _extract_created_notion_task_id(output_path) == "ALOVYA-90"


def test_notion_page_identity_is_independent_of_url_shape() -> None:
    page_id = "3a703da5d69a81c48cacc9576cd0773c"

    assert _notion_page_id_from_url(f"https://www.notion.so/{page_id}") == page_id
    assert _notion_page_id_from_url(
        "https://app.notion.com/p/task-"
        "3a703da5-d69a-81c4-8cac-c9576cd0773c"
    ) == page_id


def test_notion_command_resolves_only_from_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("ralph.notion.shutil.which", lambda command: None)

    with pytest.raises(RuntimeError, match="not available on PATH"):
        _resolve_notion_tracker_command_path()
