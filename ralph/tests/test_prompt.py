from __future__ import annotations

from pathlib import Path

from ralph.plan_selection import TaskSelection
from ralph.prompt import render_agent_prompt
from ralph.tests.conftest import build_example_ledger


def test_render_agent_prompt_excludes_unrelated_task_slice(tmp_path: Path) -> None:
    ledger = build_example_ledger()
    selection = TaskSelection(
        task=ledger["tasks"][0],
        ntt_ticket_prefix=ledger["ntt_ticket_prefix"],
        shared_plan_context="Shared context.",
        active_task_plan_context="First task context.",
    )

    prompt = render_agent_prompt(
        repo_path=tmp_path,
        selection=selection,
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
        ntt_ticket_prefix=ledger["ntt_ticket_prefix"],
        shared_plan_context="Shared context.",
        active_task_plan_context="Task instructions kept from PLAN.md.",
    )

    prompt = render_agent_prompt(
        repo_path=tmp_path,
        selection=selection,
    )

    assert "Task instructions kept from PLAN.md." in prompt
    assert "Duplicated task prose from ledger YAML." not in prompt
    assert "Full visible ledger" not in prompt
    assert "status: pending" not in prompt
    assert "depends_on" not in prompt
    assert "Add command line entrypoint" not in prompt


def test_render_agent_prompt_does_not_explain_tool_environment(tmp_path: Path) -> None:
    ledger = build_example_ledger()
    selection = TaskSelection(
        task=ledger["tasks"][0],
        ntt_ticket_prefix=ledger["ntt_ticket_prefix"],
        shared_plan_context="Shared context.",
        active_task_plan_context="First task context.",
    )
    prompt = render_agent_prompt(
        repo_path=tmp_path,
        selection=selection,
    )

    assert "Agent tool environment" not in prompt
    assert "Python venv" not in prompt
    assert "VIRTUAL_ENV" not in prompt
    assert "BASH_ENV" not in prompt
    assert "ntt --log --ticket-number 90" in prompt
    assert "--content-path <json-path>" in prompt
    assert '{"title": "Short summary", "blocks":' in prompt
    assert 'git commit --no-verify -m "Ralph: R1 Add parser"' in prompt


def test_render_agent_prompt_does_not_require_json_worklog_block(tmp_path: Path) -> None:
    ledger = build_example_ledger()
    selection = TaskSelection(
        task=ledger["tasks"][0],
        ntt_ticket_prefix=ledger["ntt_ticket_prefix"],
        shared_plan_context="Shared context.",
        active_task_plan_context="First task context.",
    )

    prompt = render_agent_prompt(
        repo_path=tmp_path,
        selection=selection,
    )

    assert "RALPH_WORKLOG_JSON_BEGIN" not in prompt
    assert "RALPH_WORKLOG_JSON_END" not in prompt
    assert "RALPH_VERIFICATION_BEGIN" not in prompt


def test_render_agent_prompt_includes_direct_ntt_logging_contract(tmp_path: Path) -> None:
    ledger = build_example_ledger()
    selection = TaskSelection(
        task=ledger["tasks"][0],
        ntt_ticket_prefix=ledger["ntt_ticket_prefix"],
        shared_plan_context="Shared context.",
        active_task_plan_context="First task context.",
    )

    prompt = render_agent_prompt(
        repo_path=tmp_path,
        selection=selection,
    )

    assert "Ralph task identity: R1" in prompt
    assert "NTT task identity: ALOVYA-90" in prompt
    assert "ntt --log --ticket-number 90" in prompt
    assert "commands" in prompt
    assert "decisions" in prompt
    assert "unresolved risks" in prompt
    assert "wrap inline technical names" in prompt
    assert "in backticks" in prompt
    assert "Use code blocks for standalone commands" in prompt
    assert "Do not read, create, restructure, complete, cancel" in prompt
    assert ".ralph-worklog.json" not in prompt


def test_render_agent_prompt_contains_no_context_read_from_ntt(tmp_path: Path) -> None:
    ledger = build_example_ledger()
    selection = TaskSelection(
        task=ledger["tasks"][0],
        ntt_ticket_prefix=ledger["ntt_ticket_prefix"],
        shared_plan_context="Shared context.",
        active_task_plan_context="First task context.",
    )

    prompt = render_agent_prompt(
        repo_path=tmp_path,
        selection=selection,
    )

    assert "Notion summary" not in prompt
    assert "previous NTT log" not in prompt
