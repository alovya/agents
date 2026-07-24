from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from ralph.plan_selection import (
    read_tasks_from_ledger,
    select_next_task_from_plan_and_ledger,
)
from ralph.tests.conftest import (
    build_example_ledger,
    build_example_plan,
    build_ledger_where_first_pending_task_waits_and_second_pending_task_is_ready,
    build_ledger_with_planned_notion_task,
    build_three_task_plan,
)


def test_extracts_only_active_plan_slice() -> None:
    ledger = build_example_ledger()
    plan_text = build_example_plan()

    selection = select_next_task_from_plan_and_ledger(ledger, plan_text)

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
        select_next_task_from_plan_and_ledger(build_example_ledger(), plan_text)


def test_accepts_task_plan_that_only_specifies_behaviour() -> None:
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

    selection = select_next_task_from_plan_and_ledger(build_example_ledger(), plan_text)

    assert selection.task["id"] == "R1"


def test_selects_dependency_ready_task() -> None:
    ledger = build_example_ledger()
    ledger["tasks"][0]["status"] = "done"

    selection = select_next_task_from_plan_and_ledger(ledger, build_example_plan())

    assert selection.task["id"] == "R2"


def test_selects_first_pending_task_after_skipping_pending_task_with_unfinished_dependencies() -> None:
    ledger = build_ledger_where_first_pending_task_waits_and_second_pending_task_is_ready()

    selection = select_next_task_from_plan_and_ledger(ledger, build_three_task_plan())

    assert selection.task["id"] == "R2"
    assert selection.active_task_plan_context.strip().startswith("Second task context.")


@pytest.mark.parametrize(
    ("mutate_ledger", "expected_message"),
    [
        (lambda ledger: ledger["tasks"][1]["notion_task"].__setitem__("planned", "yes"), "planned"),
        (lambda ledger: ledger["tasks"][1]["notion_task"].__setitem__("relationship", "parent"), "relationship"),
        (lambda ledger: ledger["tasks"][1]["notion_task"].__setitem__("related_to", ""), "related_to"),
        (lambda ledger: ledger["tasks"][1]["notion_task"].__setitem__("title", ""), "title"),
        (lambda ledger: ledger["tasks"][1]["notion_task"].__setitem__("materialized_task_id", "R1"), "materialized_task_id"),
        (lambda ledger: ledger["tasks"][1]["notion_task"].__setitem__("related_to", "R3"), "unknown Ralph task"),
        (lambda ledger: ledger["tasks"][1]["notion_task"].__setitem__("related_to", "R1"), "must depend on related Ralph task"),
    ],
)
def test_read_tasks_rejects_malformed_notion_task_entries(mutate_ledger, expected_message: str) -> None:
    ledger = build_ledger_with_planned_notion_task(related_to="ALOVYA-89", task_id="R2")
    ledger["tasks"].insert(0, {
        "id": "R1",
        "title": "Prepare parent",
        "status": "pending",
        "depends_on": [],
    })
    mutate_ledger(ledger)

    with pytest.raises(ValueError, match=expected_message):
        read_tasks_from_ledger(ledger)


def test_accepts_example_ledger() -> None:
    example_ledger_path = Path(__file__).resolve().parents[1] / "examples" / "ledger.yaml"
    ledger = yaml.safe_load(example_ledger_path.read_text())

    assert read_tasks_from_ledger(ledger)


@pytest.mark.parametrize(
    "obsolete_field",
    ["allowed_bash_commands", "touchable_paths", "verification_commands"],
)
def test_read_tasks_rejects_obsolete_control_fields(obsolete_field: str) -> None:
    ledger = build_example_ledger()
    ledger["tasks"][0][obsolete_field] = ["obsolete"]

    with pytest.raises(ValueError, match="obsolete control fields"):
        read_tasks_from_ledger(ledger)


@pytest.mark.parametrize("obsolete_marker", ["ralph-allowed-bash", "ralph-verification"])
def test_select_task_rejects_obsolete_plan_control_markers(obsolete_marker: str) -> None:
    plan_text = build_example_plan().replace(
        "First task context.",
        f"First task context.\n<!-- {obsolete_marker}:start -->\n<!-- {obsolete_marker}:end -->",
    )

    with pytest.raises(ValueError, match="obsolete control markers"):
        select_next_task_from_plan_and_ledger(build_example_ledger(), plan_text)
