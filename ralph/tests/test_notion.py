from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from ralph.notion import (
    DEFAULT_NOTION_TRACKER_STATE_PATH,
    WorklogValidationError,
    build_notion_task_creation_command,
    delete_worker_worklog_file,
    extract_created_notion_task_id,
    log_completed_worker_to_notion,
    log_failed_verification_to_notion,
    log_slice_start_to_notion,
    log_validated_worker_worklog_to_notion,
    log_worker_promise_to_notion,
    materialise_planned_notion_task_before_worker_launch,
    prepare_notion_task_before_worker_runs_task,
    validate_worker_worklog,
)
from ralph.prompt import WORKER_NOTION_WORKLOG_FILENAME
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
    )

    assert observed_content["subheading"] == "Worker returned BLOCKED"
    assert "stopped before verification" in observed_content["blocks"][0]["text"]
    assert "Transcript path:" in observed_content["blocks"][1]["text"]


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
    assert "DONE, then verification failed" in observed_content["blocks"][0]["text"]
    assert observed_content["blocks"][1]["text"] == "$ pytest\nfailed\n"
    assert "Transcript path:" in observed_content["blocks"][2]["text"]


def test_controller_logs_successful_verification_and_commit_to_notion(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    selection = select_first_task(build_ledger_with_materialised_notion_task())
    (tmp_path / "verification-output.txt").write_text("$ pytest\npassed\n")
    observed_content = capture_notion_log_content(monkeypatch)

    log_completed_worker_to_notion(
        selection=selection,
        task_path=tmp_path,
        changed_files=["M src/parser.py"],
        commit_hash="abc123",
    )

    assert observed_content["subheading"] == "Ralph R1 completed"
    assert observed_content["blocks"][0]["text"] == "M src/parser.py"
    assert observed_content["blocks"][1]["text"] == "$ pytest\npassed\n"
    assert observed_content["blocks"][2]["text"] == "Commit hash: abc123"
    assert "Transcript path:" in observed_content["blocks"][3]["text"]


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


def test_validate_worker_worklog_accepts_valid_worklog(tmp_path: Path) -> None:
    worklog_path = tmp_path / WORKER_NOTION_WORKLOG_FILENAME
    worklog_path.write_text(json.dumps({
        "subheading": "Task completed",
        "blocks": [
            {"type": "paragraph", "text": "Summary of work done."},
            {"type": "code", "language": "text", "text": "$ pytest\npassed"},
        ],
    }))

    worklog = validate_worker_worklog(tmp_path)

    assert worklog["subheading"] == "Task completed"
    assert len(worklog["blocks"]) == 2


def test_validate_worker_worklog_rejects_missing_file(tmp_path: Path) -> None:
    with pytest.raises(WorklogValidationError, match="Worker worklog file not found"):
        validate_worker_worklog(tmp_path)


def test_validate_worker_worklog_rejects_invalid_json(tmp_path: Path) -> None:
    worklog_path = tmp_path / WORKER_NOTION_WORKLOG_FILENAME
    worklog_path.write_text("not valid json {")

    with pytest.raises(WorklogValidationError, match="not valid JSON"):
        validate_worker_worklog(tmp_path)


def test_validate_worker_worklog_rejects_missing_subheading(tmp_path: Path) -> None:
    worklog_path = tmp_path / WORKER_NOTION_WORKLOG_FILENAME
    worklog_path.write_text(json.dumps({
        "blocks": [{"type": "paragraph", "text": "Summary"}],
    }))

    with pytest.raises(WorklogValidationError, match="missing required field: subheading"):
        validate_worker_worklog(tmp_path)


def test_validate_worker_worklog_rejects_empty_subheading(tmp_path: Path) -> None:
    worklog_path = tmp_path / WORKER_NOTION_WORKLOG_FILENAME
    worklog_path.write_text(json.dumps({
        "subheading": "   ",
        "blocks": [{"type": "paragraph", "text": "Summary"}],
    }))

    with pytest.raises(WorklogValidationError, match="subheading.*non-empty string"):
        validate_worker_worklog(tmp_path)


def test_validate_worker_worklog_rejects_missing_blocks(tmp_path: Path) -> None:
    worklog_path = tmp_path / WORKER_NOTION_WORKLOG_FILENAME
    worklog_path.write_text(json.dumps({
        "subheading": "Task done",
    }))

    with pytest.raises(WorklogValidationError, match="missing required field: blocks"):
        validate_worker_worklog(tmp_path)


def test_validate_worker_worklog_rejects_empty_blocks(tmp_path: Path) -> None:
    worklog_path = tmp_path / WORKER_NOTION_WORKLOG_FILENAME
    worklog_path.write_text(json.dumps({
        "subheading": "Task done",
        "blocks": [],
    }))

    with pytest.raises(WorklogValidationError, match="blocks.*non-empty list"):
        validate_worker_worklog(tmp_path)


def test_validate_worker_worklog_rejects_block_missing_type(tmp_path: Path) -> None:
    worklog_path = tmp_path / WORKER_NOTION_WORKLOG_FILENAME
    worklog_path.write_text(json.dumps({
        "subheading": "Task done",
        "blocks": [{"text": "Summary"}],
    }))

    with pytest.raises(WorklogValidationError, match="blocks\\[0\\] missing required field: type"):
        validate_worker_worklog(tmp_path)


def test_validate_worker_worklog_rejects_invalid_block_type(tmp_path: Path) -> None:
    worklog_path = tmp_path / WORKER_NOTION_WORKLOG_FILENAME
    worklog_path.write_text(json.dumps({
        "subheading": "Task done",
        "blocks": [{"type": "heading", "text": "Summary"}],
    }))

    with pytest.raises(WorklogValidationError, match="type.*must be 'paragraph' or 'code'"):
        validate_worker_worklog(tmp_path)


def test_validate_worker_worklog_rejects_code_block_missing_language(tmp_path: Path) -> None:
    worklog_path = tmp_path / WORKER_NOTION_WORKLOG_FILENAME
    worklog_path.write_text(json.dumps({
        "subheading": "Task done",
        "blocks": [{"type": "code", "text": "$ pytest"}],
    }))

    with pytest.raises(WorklogValidationError, match="code block but missing required field: language"):
        validate_worker_worklog(tmp_path)


def test_log_validated_worker_worklog_to_notion_sends_worklog_content(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    selection = select_first_task(build_ledger_with_materialised_notion_task())
    observed_content = capture_notion_log_content(monkeypatch)
    worklog = {
        "subheading": "Worker worklog",
        "blocks": [{"type": "paragraph", "text": "Summary of work"}],
    }

    log_validated_worker_worklog_to_notion(
        selection=selection,
        task_path=tmp_path,
        worklog=worklog,
    )

    assert observed_content["subheading"] == "Worker worklog"
    assert observed_content["blocks"][0]["text"] == "Summary of work"


def test_delete_worker_worklog_file_removes_file(tmp_path: Path) -> None:
    worklog_path = tmp_path / WORKER_NOTION_WORKLOG_FILENAME
    worklog_path.write_text("{}")

    delete_worker_worklog_file(tmp_path)

    assert not worklog_path.exists()


def test_delete_worker_worklog_file_does_nothing_when_file_missing(tmp_path: Path) -> None:
    delete_worker_worklog_file(tmp_path)


def test_controller_completion_log_does_not_include_worker_worklog_block(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    selection = select_first_task(build_ledger_with_materialised_notion_task())
    (tmp_path / "verification-output.txt").write_text("$ pytest\npassed\n")
    observed_content = capture_notion_log_content(monkeypatch)

    log_completed_worker_to_notion(
        selection=selection,
        task_path=tmp_path,
        changed_files=["M src/parser.py"],
        commit_hash="abc123",
    )

    all_block_texts = [block.get("text", "") for block in observed_content.get("blocks", [])]
    combined_text = "\n".join(all_block_texts)
    assert "Worker worklog:" not in combined_text
    assert "worklog" not in combined_text.lower()


def test_controller_blocked_log_does_not_include_worker_worklog_block(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    selection = select_first_task(build_ledger_with_materialised_notion_task())
    observed_content = capture_notion_log_content(monkeypatch)

    log_worker_promise_to_notion(
        selection=selection,
        task_path=tmp_path,
        promise="BLOCKED",
    )

    all_block_texts = [block.get("text", "") for block in observed_content.get("blocks", [])]
    combined_text = "\n".join(all_block_texts)
    assert "Worker worklog:" not in combined_text
    assert "worklog" not in combined_text.lower()


def test_controller_failed_verification_log_does_not_include_worker_worklog_block(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    selection = select_first_task(build_ledger_with_materialised_notion_task())
    (tmp_path / "verification-output.txt").write_text("$ pytest\nfailed\n")
    observed_content = capture_notion_log_content(monkeypatch)

    log_failed_verification_to_notion(selection=selection, task_path=tmp_path)

    all_block_texts = [block.get("text", "") for block in observed_content.get("blocks", [])]
    combined_text = "\n".join(all_block_texts)
    assert "Worker worklog:" not in combined_text
    assert "worklog" not in combined_text.lower()
