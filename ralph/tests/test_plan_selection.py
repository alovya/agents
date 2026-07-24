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
    build_three_task_plan,
)


def test_extracts_only_active_plan_slice() -> None:
    ledger = build_example_ledger()
    plan_text = build_example_plan()

    selection = select_next_task_from_plan_and_ledger(ledger, plan_text)

    assert selection.task["ralph_task_id"] == "R1"
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

    assert selection.task["ralph_task_id"] == "R1"


def test_selects_dependency_ready_task() -> None:
    ledger = build_example_ledger()
    ledger["tasks"][0]["status"] = "done"

    selection = select_next_task_from_plan_and_ledger(ledger, build_example_plan())

    assert selection.task["ralph_task_id"] == "R2"


def test_selects_first_pending_task_after_skipping_pending_task_with_unfinished_dependencies() -> None:
    ledger = build_ledger_where_first_pending_task_waits_and_second_pending_task_is_ready()

    selection = select_next_task_from_plan_and_ledger(ledger, build_three_task_plan())

    assert selection.task["ralph_task_id"] == "R2"
    assert selection.active_task_plan_context.strip().startswith("Second task context.")


def test_read_tasks_requires_ntt_parent_identity() -> None:
    ledger = build_example_ledger()
    del ledger["ntt_parent_task_id"]

    with pytest.raises(ValueError, match="ntt_parent_task_id"):
        read_tasks_from_ledger(ledger)


def test_read_tasks_accepts_configured_ntt_ticket_prefix() -> None:
    ledger = build_example_ledger()
    ledger["ntt_ticket_prefix"] = "PROJECT"
    ledger["ntt_parent_task_id"] = "PROJECT-89"
    ledger["tasks"][0]["ntt_task_id"] = "PROJECT-90"
    ledger["tasks"][1]["ntt_task_id"] = "PROJECT-91"

    assert read_tasks_from_ledger(ledger)


def test_read_tasks_requires_ntt_ticket_prefix() -> None:
    ledger = build_example_ledger()
    del ledger["ntt_ticket_prefix"]

    with pytest.raises(ValueError, match="ntt_ticket_prefix"):
        read_tasks_from_ledger(ledger)


def test_read_tasks_rejects_obsolete_notion_task_shape() -> None:
    ledger = build_example_ledger()
    ledger["tasks"][0]["notion_task"] = {"planned": True}

    with pytest.raises(ValueError, match="obsolete task identity fields"):
        read_tasks_from_ledger(ledger)


def test_read_tasks_rejects_dependency_cycles() -> None:
    ledger = build_example_ledger()
    ledger["tasks"][0]["depends_on"] = ["R2"]

    with pytest.raises(ValueError, match="contains a cycle"):
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
