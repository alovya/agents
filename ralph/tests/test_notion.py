from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from ralph.notion import (
    DEFAULT_NOTION_TRACKER_STATE_PATH,
    build_notion_task_creation_command,
    extract_created_notion_task_id,
    log_completed_worker_to_notion,
    log_failed_verification_to_notion,
    log_slice_start_to_notion,
    log_worker_promise_to_notion,
    materialise_planned_notion_task_before_worker_launch,
    prepare_notion_task_before_worker_runs_task,
)
from ralph.tests.conftest import (
    build_ledger_with_materialised_notion_task,
    build_ledger_with_planned_notion_task,
    capture_notion_log_content,
    create_job_with_ledger,
    select_first_task,
)


def test_materialises_planned_notion_task_under_existing_alovya_parent(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import subprocess

    ledger = build_ledger_with_planned_notion_task(related_to="ALOVYA-89")
    job = create_job_with_ledger(tmp_path, ledger)
    task_path = tmp_path / "task"
    task_path.mkdir()
    observed_commands: list[list[str]] = []

    def run_notion_tracker_command_mock(command: list[str]) -> subprocess.CompletedProcess[str]:
        observed_commands.append(command)
        return subprocess.CompletedProcess(
            args=command,
            returncode=0,
            stdout=json.dumps({"completed_operations": ["update_properties:task:ALOVYA-90"]}),
        )

    monkeypatch.setattr("ralph.notion._resolve_notion_tracker_command_path", lambda: "ntt")
    monkeypatch.setattr("ralph.notion._run_notion_tracker_command", run_notion_tracker_command_mock)

    updated_ledger = materialise_planned_notion_task_before_worker_launch(
        job=job,
        ledger=ledger,
        task=ledger["tasks"][0],
        task_path=task_path,
    )

    assert updated_ledger["tasks"][0]["notion_task"]["materialized_task_id"] == "ALOVYA-90"
    assert yaml.safe_load(job.ledger_path.read_text())["tasks"][0]["notion_task"]["materialized_task_id"] == "ALOVYA-90"
    assert observed_commands == [[
        "ntt",
        "--child",
        "--parent-ticket-number",
        "89",
        "--title",
        "Add parser",
        "--content-path",
        str(task_path / "notion-create-content.json"),
        "--tracker-state-path",
        str(DEFAULT_NOTION_TRACKER_STATE_PATH),
        "--output-path",
        str(task_path / "notion-create-output.json"),
    ]]


def test_materialises_planned_notion_task_after_related_ralph_task_exists(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import subprocess

    ledger = build_ledger_with_planned_notion_task(related_to="R1", task_id="R2")
    ledger["tasks"].insert(0, {
        "id": "R1",
        "title": "Prepare parent",
        "status": "done",
        "depends_on": [],
        "notion_task": {
            "planned": True,
            "relationship": "child",
            "related_to": "ALOVYA-89",
            "title": "Prepare parent",
            "materialized_task_id": "ALOVYA-90",
        },
    })
    ledger["tasks"][1]["depends_on"] = ["R1"]
    job = create_job_with_ledger(tmp_path, ledger)
    task_path = tmp_path / "task"
    task_path.mkdir()
    observed_commands: list[list[str]] = []

    def run_notion_tracker_command_mock(command: list[str]) -> subprocess.CompletedProcess[str]:
        observed_commands.append(command)
        return subprocess.CompletedProcess(
            args=command,
            returncode=0,
            stdout=json.dumps({"completed_operations": ["update_properties:task:ALOVYA-91"]}),
        )

    monkeypatch.setattr("ralph.notion._resolve_notion_tracker_command_path", lambda: "ntt")
    monkeypatch.setattr("ralph.notion._run_notion_tracker_command", run_notion_tracker_command_mock)

    updated_ledger = materialise_planned_notion_task_before_worker_launch(
        job=job,
        ledger=ledger,
        task=ledger["tasks"][1],
        task_path=task_path,
    )

    assert updated_ledger["tasks"][1]["notion_task"]["materialized_task_id"] == "ALOVYA-91"
    assert "--parent-ticket-number" in observed_commands[0]
    assert observed_commands[0][observed_commands[0].index("--parent-ticket-number") + 1] == "90"
    assert observed_commands[0][observed_commands[0].index("--tracker-state-path") + 1] == str(DEFAULT_NOTION_TRACKER_STATE_PATH)


def test_materialising_planned_notion_task_blocks_when_related_ralph_task_is_not_materialised(
    tmp_path: Path,
) -> None:
    ledger = build_ledger_with_planned_notion_task(related_to="R1", task_id="R2")
    ledger["tasks"].insert(0, {
        "id": "R1",
        "title": "Prepare parent",
        "status": "done",
        "depends_on": [],
        "notion_task": {
            "planned": True,
            "relationship": "child",
            "related_to": "ALOVYA-89",
            "title": "Prepare parent",
            "materialized_task_id": None,
        },
    })
    ledger["tasks"][1]["depends_on"] = ["R1"]
    job = create_job_with_ledger(tmp_path, ledger)
    task_path = tmp_path / "task"
    task_path.mkdir()

    with pytest.raises(RuntimeError, match="must materialise its Notion task"):
        materialise_planned_notion_task_before_worker_launch(
            job=job,
            ledger=ledger,
            task=ledger["tasks"][1],
            task_path=task_path,
        )


def test_prepare_notion_task_blocks_worker_launch_when_notion_tracker_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ledger = build_ledger_with_planned_notion_task(related_to="ALOVYA-89")
    job = create_job_with_ledger(tmp_path, ledger)
    task_path = tmp_path / "task"
    task_path.mkdir()

    def run_notion_tracker_command_mock(command: list[str]) -> None:
        raise RuntimeError("Notion task tracker command failed")

    monkeypatch.setattr("ralph.notion._resolve_notion_tracker_command_path", lambda: "ntt")
    monkeypatch.setattr("ralph.notion._run_notion_tracker_command", run_notion_tracker_command_mock)

    with pytest.raises(RuntimeError, match="Notion task tracker command failed"):
        prepare_notion_task_before_worker_runs_task(
            job=job,
            ledger=ledger,
            selection=select_first_task(ledger),
            task_path=task_path,
        )

    assert yaml.safe_load(job.ledger_path.read_text())["tasks"][0]["notion_task"]["materialized_task_id"] is None


def test_controller_logs_slice_start_to_notion(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    selection = select_first_task(build_ledger_with_materialised_notion_task())
    observed_content = capture_notion_log_content(monkeypatch)

    log_slice_start_to_notion(selection=selection, task_path=tmp_path)

    assert observed_content["subheading"] == "Ralph R1 started"
    assert "Goal: Add parser" in observed_content["blocks"][0]["text"]
    assert "verification_commands" in observed_content["blocks"][1]["text"]
    assert observed_content["command"][observed_content["command"].index("--tracker-state-path") + 1] == str(
        DEFAULT_NOTION_TRACKER_STATE_PATH
    )


def test_controller_logs_blocked_worker_promise_to_notion(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    selection = select_first_task(build_ledger_with_materialised_notion_task())
    observed_content = capture_notion_log_content(monkeypatch)

    log_worker_promise_to_notion(
        selection=selection,
        task_path=tmp_path,
        promise="BLOCKED",
        agent_output="Missing dependency",
    )

    assert observed_content["subheading"] == "Worker returned BLOCKED"
    assert observed_content["blocks"][1]["text"] == "Missing dependency"


def test_controller_logs_failed_verification_to_notion(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    selection = select_first_task(build_ledger_with_materialised_notion_task())
    verification_output_path = tmp_path / "verification-output.txt"
    verification_output_path.write_text("$ pytest\nfailed\n")
    observed_content = capture_notion_log_content(monkeypatch)

    log_failed_verification_to_notion(selection=selection, task_path=tmp_path)

    assert observed_content["subheading"] == "Verification failed"
    assert observed_content["blocks"][1]["text"] == "$ pytest\nfailed\n"


def test_controller_logs_successful_verification_and_commit_to_notion(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    selection = select_first_task(build_ledger_with_materialised_notion_task())
    (tmp_path / "promise.txt").write_text("DONE")
    (tmp_path / "verification-output.txt").write_text("$ pytest\npassed\n")
    observed_content = capture_notion_log_content(monkeypatch)

    log_completed_worker_to_notion(
        selection=selection,
        task_path=tmp_path,
        changed_files=["M src/parser.py"],
        commit_hash="abc123",
    )

    assert observed_content["subheading"] == "Ralph R1 completed"
    assert observed_content["blocks"][0]["text"] == "Worker promise: DONE"
    assert observed_content["blocks"][1]["text"] == "M src/parser.py"
    assert observed_content["blocks"][2]["text"] == "$ pytest\npassed\n"
    assert observed_content["blocks"][3]["text"] == "Commit hash: abc123"


def test_extract_created_notion_task_id_uses_output_file_and_excludes_related_task(
    tmp_path: Path,
) -> None:
    output_path = tmp_path / "ntt-output.json"
    output_path.write_text(json.dumps({
        "completed_operations": [
            "update_timeline_log:task:ALOVYA-89:2026-06-18",
            "update_properties:task:ALOVYA-90",
        ]
    }))

    assert extract_created_notion_task_id("", output_path, "ALOVYA-89") == "ALOVYA-90"


def test_build_notion_task_creation_command_builds_sibling_command(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("ralph.notion._resolve_notion_tracker_command_path", lambda: "ntt")

    command = build_notion_task_creation_command(
        relationship="sibling",
        related_notion_task_id="ALOVYA-89",
        title="Add parser",
        content_path=tmp_path / "content.json",
        output_path=tmp_path / "output.json",
    )

    assert command == [
        "ntt",
        "--sibling",
        "--sibling-ticket-number",
        "89",
        "--title",
        "Add parser",
        "--content-path",
        str(tmp_path / "content.json"),
        "--tracker-state-path",
        str(DEFAULT_NOTION_TRACKER_STATE_PATH),
        "--output-path",
        str(tmp_path / "output.json"),
    ]
