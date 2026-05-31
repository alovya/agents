from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest
import yaml


RALPH_MODULE_PATH = Path(__file__).resolve().parents[1] / "run_ralph_loop.py"
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
    assert ralph._parse_worker_promise(
        "\n".join(
            [
                "<promise>DONE</promise>",
                "<promise>BLOCKED</promise>",
                "<promise>ABORT</promise>",
                "final answer",
                "<promise>DONE</promise>",
            ]
        )
    ) == "DONE"
    with pytest.raises(RuntimeError, match="Expected one final"):
        ralph._parse_worker_promise("No promise here.")


def test_parse_args_streams_worker_output_by_default() -> None:
    arguments = ralph._parse_arguments([
        "run",
        "--repo-path",
        "/tmp/repo",
        "--project-name",
        "example",
    ])

    assert arguments.tee_worker_output is True


def test_parse_args_can_disable_worker_output_teeing() -> None:
    arguments = ralph._parse_arguments([
        "run",
        "--repo-path",
        "/tmp/repo",
        "--project-name",
        "example",
        "--no-tee-worker-output",
    ])

    assert arguments.tee_worker_output is False


def test_parse_args_accepts_python_venv() -> None:
    arguments = ralph._parse_arguments([
        "run",
        "--repo-path",
        "/tmp/repo",
        "--project-name",
        "example",
        "--python-venv",
        "/tmp/tooling-venv",
    ])

    assert arguments.python_venv == "/tmp/tooling-venv"


def test_run_command_and_tee_output_writes_to_terminal_and_file(
    tmp_path: Path,
    capsys,
) -> None:
    output_path = tmp_path / "worker-output.txt"

    completed_process = ralph._run_command_and_tee_output(
        command=["bash", "-lc", "printf 'before\\n'; cat; printf 'after\\n'"],
        input_text="middle\n",
        output_path=output_path,
    )

    assert completed_process.returncode == 0
    assert completed_process.stdout == "before\nmiddle\nafter\n"
    assert output_path.read_text(encoding="utf-8") == "before\nmiddle\nafter\n"
    assert capsys.readouterr().out == "before\nmiddle\nafter\n"


def test_write_run_status_appends_status_lines(tmp_path: Path) -> None:
    ralph._write_run_status(tmp_path, "selected R1")
    ralph._write_run_status(tmp_path, "worker returned DONE")

    status_text = tmp_path.joinpath("status.txt").read_text(encoding="utf-8")

    assert "selected R1" in status_text
    assert "worker returned DONE" in status_text
    assert len(status_text.splitlines()) == 2


def test_create_run_directory_prefixes_task_id(tmp_path: Path) -> None:
    run_path = ralph._create_run_directory(tmp_path, "R1")

    assert run_path.name.startswith("R1_")
    assert run_path.is_dir()


def test_create_run_directory_sanitizes_task_id(tmp_path: Path) -> None:
    run_path = ralph._create_run_directory(tmp_path, "R 1/cleanup")

    assert run_path.name.startswith("R-1-cleanup_")
    assert run_path.is_dir()


def test_rendered_prompt_excludes_unrelated_task_slice(tmp_path: Path) -> None:
    ledger = _ledger()
    selection = ralph.TaskSelection(
        task=ledger["tasks"][0],
        shared_plan_context="Shared context.",
        active_task_plan_context="First task context.",
    )

    prompt = ralph._render_worker_prompt(
        repo_path=tmp_path,
        ledger=ledger,
        selection=selection,
        python_venv_path=None,
    )

    assert "First task context." in prompt
    assert "Second task context." not in prompt
    assert "/.ralph" not in prompt


def test_rendered_prompt_documents_python_venv(tmp_path: Path) -> None:
    ledger = _ledger()
    selection = ralph.TaskSelection(
        task=ledger["tasks"][0],
        shared_plan_context="Shared context.",
        active_task_plan_context="First task context.",
    )
    python_venv_path = tmp_path / "venv"

    prompt = ralph._render_worker_prompt(
        repo_path=tmp_path,
        ledger=ledger,
        selection=selection,
        python_venv_path=python_venv_path,
    )

    assert f"Python venv: {python_venv_path}" in prompt
    assert "already first on PATH" in prompt


def test_build_bwrap_command_mounts_python_venv(tmp_path: Path, monkeypatch) -> None:
    python_venv_path = tmp_path / "venv"
    python_venv_path.mkdir()
    monkeypatch.setattr(ralph.shutil, "which", lambda command: f"/usr/bin/{command}")

    command = ralph._build_bwrap_codex_command(
        repo_path=tmp_path,
        codex_command="codex",
        python_venv_path=python_venv_path,
    )

    assert _contains_subsequence(command, ["--ro-bind", str(python_venv_path), str(python_venv_path)])
    assert _contains_subsequence(command, ["--setenv", "VIRTUAL_ENV", str(python_venv_path)])
    assert str(python_venv_path / "bin") in command[command.index("PATH") + 1].split(":")[0]


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


def _contains_subsequence(command: list[str], expected: list[str]) -> bool:
    return any(
        command[index:index + len(expected)] == expected
        for index in range(len(command) - len(expected) + 1)
    )
