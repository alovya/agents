from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest
import yaml


RALPH_MODULE_PATH = Path(__file__).resolve().parents[1] / "ralph.py"
spec = importlib.util.spec_from_file_location("ralph", RALPH_MODULE_PATH)
ralph = importlib.util.module_from_spec(spec)
sys.modules["ralph"] = ralph
assert spec.loader is not None
spec.loader.exec_module(ralph)


def test_extracts_only_active_plan_slice() -> None:
    ledger = _ledger()
    plan_text = """
<!-- ralph-shared:start -->
Shared context.
<!-- ralph-shared:end -->

<!-- ralph-task:start R1 -->
First task context.
<!-- ralph-task:end R1 -->

<!-- ralph-task:start R2 -->
Second task context.
<!-- ralph-task:end R2 -->
"""

    selection = ralph._select_next_task_from_plan_and_ledger(ledger, plan_text)

    assert selection.task["id"] == "R1"
    assert "First task context." in selection.active_task_plan_context
    assert "Second task context." not in selection.active_task_plan_context


def test_rejects_missing_plan_slice() -> None:
    plan_text = """
<!-- ralph-shared:start -->
Shared context.
<!-- ralph-shared:end -->
"""

    with pytest.raises(ValueError, match="missing Ralph task blocks"):
        ralph._select_next_task_from_plan_and_ledger(_ledger(), plan_text)


def test_selects_dependency_ready_task() -> None:
    ledger = _ledger()
    ledger["tasks"][0]["status"] = "done"

    plan_text = """
<!-- ralph-shared:start -->
Shared context.
<!-- ralph-shared:end -->

<!-- ralph-task:start R1 -->
First task context.
<!-- ralph-task:end R1 -->

<!-- ralph-task:start R2 -->
Second task context.
<!-- ralph-task:end R2 -->
"""

    selection = ralph._select_next_task_from_plan_and_ledger(ledger, plan_text)

    assert selection.task["id"] == "R2"


def test_parses_exactly_one_promise() -> None:
    assert ralph._parse_worker_promise("done\n<promise>DONE</promise>") == "DONE"
    with pytest.raises(RuntimeError, match="Expected exactly one"):
        ralph._parse_worker_promise("<promise>DONE</promise>\n<promise>DONE</promise>")


def test_rendered_prompt_excludes_unrelated_task_slice(tmp_path: Path) -> None:
    ledger = _ledger()
    selection = ralph.TaskSelection(
        task=ledger["tasks"][0],
        shared_plan_context="Shared context.",
        active_task_plan_context="First task context.",
    )

    prompt = ralph._render_worker_prompt(repo_path=tmp_path, ledger=ledger, selection=selection)

    assert "First task context." in prompt
    assert "Second task context." not in prompt
    assert "/.ralph" not in prompt


def test_marks_task_done_without_mutating_input() -> None:
    ledger = _ledger()

    updated_ledger = ralph._mark_task_done(ledger, "R1")

    assert ledger["tasks"][0]["status"] == "pending"
    assert updated_ledger["tasks"][0]["status"] == "done"
    assert "completed_at" in updated_ledger["tasks"][0]


def test_examples_ledger_is_valid() -> None:
    example_ledger_path = Path(__file__).resolve().parents[1] / "examples" / "ledger.yaml"
    ledger = yaml.safe_load(example_ledger_path.read_text())

    assert ralph._read_tasks_from_ledger(ledger)


def _ledger() -> dict[str, object]:
    return {
        "version": 1,
        "project_name": "example",
        "tasks": [
            {
                "id": "R1",
                "title": "Add parser",
                "status": "pending",
                "depends_on": [],
                "touchable_paths": ["src/parser.py"],
                "verification_commands": ["python -m pytest tests/test_parser.py"],
            },
            {
                "id": "R2",
                "title": "Add command line entrypoint",
                "status": "pending",
                "depends_on": ["R1"],
                "touchable_paths": ["src/cli.py"],
                "verification_commands": ["python -m pytest tests/test_cli.py"],
            },
        ],
    }
