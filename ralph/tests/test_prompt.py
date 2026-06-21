from __future__ import annotations

from pathlib import Path

from ralph.plan_selection import TaskSelection
from ralph.prompt import render_agent_prompt
from ralph.tests.conftest import build_example_ledger


def test_render_agent_prompt_excludes_unrelated_task_slice(tmp_path: Path) -> None:
    ledger = build_example_ledger()
    selection = TaskSelection(
        task=ledger["tasks"][0],
        shared_plan_context="Shared context.",
        active_task_plan_context="First task context.",
    )

    prompt = render_agent_prompt(
        repo_path=tmp_path,
        ledger=ledger,
        selection=selection,
        python_venv_path=None,
    )

    assert "First task context." in prompt
    assert "Second task context." not in prompt
    assert "/.ralph" not in prompt
    assert "Codex" not in prompt


def test_render_agent_prompt_keeps_plan_instructions_without_duplicating_ledger_prose(tmp_path: Path) -> None:
    ledger = build_example_ledger()
    ledger["tasks"][0]["context"] = "Duplicated task prose from ledger YAML."
    selection = TaskSelection(
        task=ledger["tasks"][0],
        shared_plan_context="Shared context.",
        active_task_plan_context="Task instructions kept from PLAN.md.",
    )

    prompt = render_agent_prompt(
        repo_path=tmp_path,
        ledger=ledger,
        selection=selection,
        python_venv_path=None,
    )

    assert "Task instructions kept from PLAN.md." in prompt
    assert "Duplicated task prose from ledger YAML." not in prompt


def test_render_agent_prompt_documents_python_venv(tmp_path: Path) -> None:
    ledger = build_example_ledger()
    selection = TaskSelection(
        task=ledger["tasks"][0],
        shared_plan_context="Shared context.",
        active_task_plan_context="First task context.",
    )
    python_venv_path = tmp_path / "venv"

    prompt = render_agent_prompt(
        repo_path=tmp_path,
        ledger=ledger,
        selection=selection,
        python_venv_path=python_venv_path,
    )

    assert f"Python venv: {python_venv_path}" in prompt
    assert "already first on PATH" in prompt
    assert "ntt --log --ticket-number" not in prompt


def test_render_agent_prompt_tells_workers_to_emit_json_worklog_block(tmp_path: Path) -> None:
    ledger = build_example_ledger()
    selection = TaskSelection(
        task=ledger["tasks"][0],
        shared_plan_context="Shared context.",
        active_task_plan_context="First task context.",
    )

    prompt = render_agent_prompt(
        repo_path=tmp_path,
        ledger=ledger,
        selection=selection,
        python_venv_path=None,
    )

    assert "RALPH_WORKLOG_JSON_BEGIN" in prompt
    assert "RALPH_WORKLOG_JSON_END" in prompt
    assert "worklog is required for DONE" in prompt
    assert "reject DONE if the JSON is malformed" in prompt
    assert "commands_run" in prompt
    assert "files_changed" in prompt
    assert "decisions_made" in prompt
    assert "unresolved_risks" in prompt
    assert "notion_log_command" in prompt
    assert "notion_log_result" in prompt


def test_render_agent_prompt_includes_notion_log_command_when_materialised(tmp_path: Path) -> None:
    from ralph.tests.conftest import build_ledger_with_materialised_notion_task

    ledger = build_ledger_with_materialised_notion_task()
    selection = TaskSelection(
        task=ledger["tasks"][0],
        shared_plan_context="Shared context.",
        active_task_plan_context="First task context.",
    )

    prompt = render_agent_prompt(
        repo_path=tmp_path,
        ledger=ledger,
        selection=selection,
        python_venv_path=None,
    )

    assert "ntt --log --ticket-number 90" in prompt
    assert ".ralph-worklog.json" in prompt


def test_render_agent_prompt_notion_log_not_applicable_without_task(tmp_path: Path) -> None:
    ledger = build_example_ledger()
    selection = TaskSelection(
        task=ledger["tasks"][0],
        shared_plan_context="Shared context.",
        active_task_plan_context="First task context.",
    )

    prompt = render_agent_prompt(
        repo_path=tmp_path,
        ledger=ledger,
        selection=selection,
        python_venv_path=None,
    )

    assert "not applicable for this task" in prompt
    assert "ntt --log" not in prompt
