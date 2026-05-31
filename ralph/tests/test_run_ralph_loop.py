from __future__ import annotations

import shlex
import subprocess
from pathlib import Path

import pytest
import yaml

from ralph.run_ralph_loop import (
    RalphJob,
    TaskSelection,
    _build_bwrap_codex_command,
    _create_run_directory,
    _finish_task_after_worker_done,
    _mark_task_done,
    _parse_arguments,
    _parse_worker_promise,
    _read_tasks_from_ledger,
    _render_worker_prompt,
    _run_command_and_tee_output,
    _select_next_task_from_plan_and_ledger,
    _write_yaml_file,
)


def test_extracts_only_active_plan_slice() -> None:
    ledger = _build_example_ledger()
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

    selection = _select_next_task_from_plan_and_ledger(ledger, plan_text)

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
        _select_next_task_from_plan_and_ledger(_build_example_ledger(), plan_text)


def test_selects_dependency_ready_task() -> None:
    ledger = _build_example_ledger()
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

    selection = _select_next_task_from_plan_and_ledger(ledger, plan_text)

    assert selection.task["id"] == "R2"


def test_parses_exactly_one_promise() -> None:
    assert _parse_worker_promise("done\n<promise>DONE</promise>") == "DONE"
    assert _parse_worker_promise(
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
        _parse_worker_promise("No promise here.")


def test_parse_args_streams_worker_output_by_default() -> None:
    arguments = _parse_arguments([
        "run",
        "--repo-path",
        "/tmp/repo",
        "--job-name",
        "example",
    ])

    assert arguments.tee_worker_output is True


def test_parse_args_can_disable_worker_output_teeing() -> None:
    arguments = _parse_arguments([
        "run",
        "--repo-path",
        "/tmp/repo",
        "--job-name",
        "example",
        "--no-tee-worker-output",
    ])

    assert arguments.tee_worker_output is False


def test_parse_args_accepts_python_venv() -> None:
    arguments = _parse_arguments([
        "run",
        "--repo-path",
        "/tmp/repo",
        "--job-name",
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

    completed_process = _run_command_and_tee_output(
        command=["bash", "-lc", "printf 'before\\n'; cat; printf 'after\\n'"],
        input_text="middle\n",
        output_path=output_path,
    )

    assert completed_process.returncode == 0
    assert completed_process.stdout == "before\nmiddle\nafter\n"
    assert output_path.read_text(encoding="utf-8") == "before\nmiddle\nafter\n"
    assert capsys.readouterr().out == "before\nmiddle\nafter\n"


def test_create_run_directory_prefixes_task_id(tmp_path: Path) -> None:
    run_path = _create_run_directory(tmp_path, "R1")

    assert run_path.name.startswith("R1_")
    assert run_path.is_dir()


def test_create_run_directory_sanitizes_task_id(tmp_path: Path) -> None:
    run_path = _create_run_directory(tmp_path, "R 1/cleanup")

    assert run_path.name.startswith("R-1-cleanup_")
    assert run_path.is_dir()


def test_render_worker_prompt_excludes_unrelated_task_slice(tmp_path: Path) -> None:
    ledger = _build_example_ledger()
    selection = TaskSelection(
        task=ledger["tasks"][0],
        shared_plan_context="Shared context.",
        active_task_plan_context="First task context.",
    )

    prompt = _render_worker_prompt(
        repo_path=tmp_path,
        ledger=ledger,
        selection=selection,
        python_venv_path=None,
    )

    assert "First task context." in prompt
    assert "Second task context." not in prompt
    assert "/.ralph" not in prompt


def test_render_worker_prompt_documents_python_venv(tmp_path: Path) -> None:
    ledger = _build_example_ledger()
    selection = TaskSelection(
        task=ledger["tasks"][0],
        shared_plan_context="Shared context.",
        active_task_plan_context="First task context.",
    )
    python_venv_path = tmp_path / "venv"

    prompt = _render_worker_prompt(
        repo_path=tmp_path,
        ledger=ledger,
        selection=selection,
        python_venv_path=python_venv_path,
    )

    assert f"Python venv: {python_venv_path}" in prompt
    assert "already first on PATH" in prompt


def test_build_bwrap_command_mounts_python_venv_from_path(tmp_path: Path, monkeypatch) -> None:
    bin_path = tmp_path / "bin"
    bwrap_path = bin_path / "bwrap"
    codex_path = bin_path / "codex"
    python_venv_path = tmp_path / "venv"
    bin_path.mkdir()
    python_venv_path.mkdir()
    _write_executable_shim(bwrap_path)
    _write_executable_shim(codex_path)
    monkeypatch.setenv("PATH", str(bin_path))

    command = _build_bwrap_codex_command(
        repo_path=tmp_path,
        codex_command="codex",
        python_venv_path=python_venv_path,
    )

    assert command[0] == str(bwrap_path)
    assert str(codex_path) in command
    assert _contains_subsequence(command, ["--ro-bind", str(python_venv_path), str(python_venv_path)])
    assert _contains_subsequence(command, ["--setenv", "VIRTUAL_ENV", str(python_venv_path)])
    assert _contains_subsequence(command, ["--setenv", "BASH_ENV", str(python_venv_path / "bin" / "activate")])
    assert str(python_venv_path / "bin") in command[command.index("PATH") + 1].split(":")[0]


def test_marks_task_done_without_mutating_input() -> None:
    ledger = _build_example_ledger()

    updated_ledger = _mark_task_done(ledger, "R1")

    assert ledger["tasks"][0]["status"] == "pending"
    assert updated_ledger["tasks"][0]["status"] == "done"
    assert "completed_at" in updated_ledger["tasks"][0]


def test_finishes_worker_done_task_by_committing_before_advancing_ledger(
    tmp_path: Path,
) -> None:
    repo_path = _initialise_git_repo(tmp_path / "target-repo")
    ledger = _build_example_ledger()
    job = _create_job_with_ledger(tmp_path, ledger)
    run_path = tmp_path / "run"
    observed_ledger_at_commit_path = tmp_path / "ledger-at-commit.yaml"
    parser_path = repo_path / "src" / "parser.py"
    parser_path.parent.mkdir()
    parser_path.write_text("def parse_value(value):\n    return value\n")
    _install_pre_commit_hook_that_requires_pending_ledger(
        repo_path=repo_path,
        ledger_path=job.ledger_path,
        observed_ledger_path=observed_ledger_at_commit_path,
    )

    commit_hash = _finish_task_after_worker_done(
        repo_path=repo_path,
        job=job,
        ledger=ledger,
        selection=_select_first_task(ledger),
        run_path=run_path,
    )

    committed_subject = _run_git(repo_path, "log", "--format=%s", "-1").strip()

    assert commit_hash == _run_git(repo_path, "rev-parse", "HEAD").strip()
    assert committed_subject == "Ralph: R1 Add parser"
    assert yaml.safe_load(observed_ledger_at_commit_path.read_text())["tasks"][0]["status"] == "pending"
    assert yaml.safe_load(job.ledger_path.read_text())["tasks"][0]["status"] == "done"
    assert "$ test -f src/parser.py" in run_path.joinpath("verification-output.txt").read_text()
    assert run_path.joinpath("commit.txt").read_text() == commit_hash


def test_finish_worker_done_task_keeps_ledger_pending_when_commit_fails(
    tmp_path: Path,
) -> None:
    repo_path = _initialise_git_repo(tmp_path / "target-repo")
    ledger = _build_example_ledger()
    job = _create_job_with_ledger(tmp_path, ledger)
    run_path = tmp_path / "run"
    parser_path = repo_path / "src" / "parser.py"
    parser_path.parent.mkdir()
    parser_path.write_text("def parse_value(value):\n    return value\n")
    _install_failing_pre_commit_hook(repo_path)

    with pytest.raises(RuntimeError, match="pre-commit refused commit"):
        _finish_task_after_worker_done(
            repo_path=repo_path,
            job=job,
            ledger=ledger,
            selection=_select_first_task(ledger),
            run_path=run_path,
        )

    assert yaml.safe_load(job.ledger_path.read_text())["tasks"][0]["status"] == "pending"
    assert "$ test -f src/parser.py" in run_path.joinpath("verification-output.txt").read_text()
    assert not run_path.joinpath("commit.txt").exists()


def test_accepts_example_ledger() -> None:
    example_ledger_path = Path(__file__).resolve().parents[1] / "examples" / "ledger.yaml"
    ledger = yaml.safe_load(example_ledger_path.read_text())

    assert _read_tasks_from_ledger(ledger)


def _build_example_ledger() -> dict[str, object]:
    return {
        "version": 1,
        "job_name": "example",
        "tasks": [
            {
                "id": "R1",
                "title": "Add parser",
                "status": "pending",
                "depends_on": [],
                "touchable_paths": ["src/parser.py"],
                "verification_commands": ["test -f src/parser.py"],
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


def _select_first_task(ledger: dict[str, object]) -> TaskSelection:
    return TaskSelection(
        task=ledger["tasks"][0],
        shared_plan_context="Shared context.",
        active_task_plan_context="First task context.",
    )


def _create_job_with_ledger(tmp_path: Path, ledger: dict[str, object]) -> RalphJob:
    job_path = tmp_path / "job"
    job = RalphJob(
        job_name="example",
        job_path=job_path,
        plan_path=job_path / "PLAN.md",
        ledger_path=job_path / "ledger.yaml",
        tasks_path=job_path / "tasks",
    )
    job_path.mkdir()
    _write_yaml_file(job.ledger_path, ledger)
    return job


def _initialise_git_repo(repo_path: Path) -> Path:
    repo_path.mkdir()
    _run_git(repo_path, "init")
    _run_git(repo_path, "config", "user.email", "ralph-test@example.com")
    _run_git(repo_path, "config", "user.name", "Ralph Test")
    readme_path = repo_path / "README.md"
    readme_path.write_text("Ralph test repository\n")
    _run_git(repo_path, "add", ".")
    _run_git(repo_path, "commit", "-m", "Initial commit")
    return repo_path


def _install_pre_commit_hook_that_requires_pending_ledger(
    repo_path: Path,
    ledger_path: Path,
    observed_ledger_path: Path,
) -> None:
    hook_path = repo_path / ".git" / "hooks" / "pre-commit"
    hook_path.write_text(
        "\n".join(
            [
                "#!/bin/sh",
                f"cat {_quote_shell_path(ledger_path)} > {_quote_shell_path(observed_ledger_path)}",
                f"grep -q 'status: pending' {_quote_shell_path(ledger_path)}",
            ]
        )
    )
    hook_path.chmod(0o755)


def _install_failing_pre_commit_hook(repo_path: Path) -> None:
    hook_path = repo_path / ".git" / "hooks" / "pre-commit"
    hook_path.write_text(
        "\n".join(
            [
                "#!/bin/sh",
                "echo 'pre-commit refused commit' >&2",
                "exit 1",
            ]
        )
    )
    hook_path.chmod(0o755)


def _write_executable_shim(shim_path: Path) -> None:
    shim_path.write_text("#!/bin/sh\nexit 0\n")
    shim_path.chmod(0o755)


def _run_git(repo_path: Path, *arguments: str) -> str:
    completed_process = subprocess.run(
        ["git", *arguments],
        cwd=repo_path,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )
    if completed_process.returncode != 0:
        raise RuntimeError(f"git {' '.join(arguments)} failed:\n{completed_process.stdout}")
    return completed_process.stdout


def _quote_shell_path(path: Path) -> str:
    return shlex.quote(str(path))
