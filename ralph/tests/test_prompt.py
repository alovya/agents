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
        selection=selection,
        python_venv_path=None,
    )

    assert "First task context." in prompt
    assert "Second task context." not in prompt
    assert "/.ralph" not in prompt
    assert "Codex" not in prompt


def test_render_agent_prompt_keeps_plan_instructions_without_rendering_ledger_state(tmp_path: Path) -> None:
    ledger = build_example_ledger()
    ledger["tasks"][0]["context"] = "Duplicated task prose from ledger YAML."
    selection = TaskSelection(
        task=ledger["tasks"][0],
        shared_plan_context="Shared context.",
        active_task_plan_context="Task instructions kept from PLAN.md.",
    )

    prompt = render_agent_prompt(
        repo_path=tmp_path,
        selection=selection,
        python_venv_path=None,
    )

    assert "Task instructions kept from PLAN.md." in prompt
    assert "Duplicated task prose from ledger YAML." not in prompt
    assert "Full visible ledger" not in prompt
    assert "status: pending" not in prompt
    assert "depends_on" not in prompt
    assert "Add command line entrypoint" not in prompt


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
        selection=selection,
        python_venv_path=python_venv_path,
    )

    assert f"Python venv: {python_venv_path}" in prompt
    assert "already first on PATH" in prompt
    assert "ntt --log --ticket-number" not in prompt


def test_render_agent_prompt_does_not_require_json_worklog_block(tmp_path: Path) -> None:
    ledger = build_example_ledger()
    selection = TaskSelection(
        task=ledger["tasks"][0],
        shared_plan_context="Shared context.",
        active_task_plan_context="First task context.",
    )

    prompt = render_agent_prompt(
        repo_path=tmp_path,
        selection=selection,
        python_venv_path=None,
    )

    assert "RALPH_WORKLOG_JSON_BEGIN" not in prompt
    assert "RALPH_WORKLOG_JSON_END" not in prompt
    assert "RALPH_VERIFICATION_BEGIN" not in prompt


def test_render_agent_prompt_includes_worklog_instructions_when_materialised(tmp_path: Path) -> None:
    from ralph.tests.conftest import build_ledger_with_materialised_notion_task

    ledger = build_ledger_with_materialised_notion_task()
    selection = TaskSelection(
        task=ledger["tasks"][0],
        shared_plan_context="Shared context.",
        active_task_plan_context="First task context.",
    )

    prompt = render_agent_prompt(
        repo_path=tmp_path,
        selection=selection,
        python_venv_path=None,
    )

    assert ".ralph-worklog.json" in prompt
    assert "title" in prompt
    assert "blocks" in prompt
    assert "commands run" in prompt
    assert "files changed" in prompt
    assert "decisions made" in prompt
    assert "unresolved risks" in prompt
    assert "BLOCKED or ABORT" in prompt
    assert "Do not run `ntt` or contact Notion" in prompt
    assert "Never stage or commit `.ralph-worklog.json`" in prompt
    assert "Do NOT put the worklog JSON in your final answer" in prompt
    assert "Do NOT delete the worklog file" in prompt


def test_render_agent_prompt_notion_log_not_applicable_without_task(tmp_path: Path) -> None:
    ledger = build_example_ledger()
    selection = TaskSelection(
        task=ledger["tasks"][0],
        shared_plan_context="Shared context.",
        active_task_plan_context="First task context.",
    )

    prompt = render_agent_prompt(
        repo_path=tmp_path,
        selection=selection,
        python_venv_path=None,
    )

    assert "not applicable for this task" in prompt
    assert "ntt --log" not in prompt
