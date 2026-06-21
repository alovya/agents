from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from ralph.tests.conftest import (
    build_example_ledger,
    build_ledger_with_materialised_notion_task,
    capture_notion_log_content,
    create_job_with_ledger,
    initialise_git_repo,
    run_git,
    select_first_task,
)
from ralph.notion import WorklogValidationError
from ralph.prompt import WORKER_NOTION_WORKLOG_FILENAME
from ralph.run_ralph_loop import (
    _accept_worker_completed_task,
    _create_task_directory,
    _find_ralph_job,
    main,
    _mark_task_done,
    _parse_arguments,
    _parse_agent_promise,
    _refuse_unsafe_starting_state,
)
from ralph.sandbox import run_agent_visibility_smoke_test


def test_direct_script_help_remains_runnable_from_repo_root() -> None:
    import subprocess

    repo_path = Path(__file__).resolve().parents[2]

    completed_process = subprocess.run(
        ["/workspace/venv/bin/python", "ralph/run_ralph_loop.py", "--help"],
        cwd=repo_path,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )

    assert completed_process.returncode == 0
    assert "Run Ralph task loops with sliced plan context." in completed_process.stdout
    assert "run" in completed_process.stdout
    assert "smoke-test" in completed_process.stdout


def test_package_invocation_help_remains_runnable() -> None:
    import subprocess

    repo_path = Path(__file__).resolve().parents[2]

    completed_process = subprocess.run(
        ["/workspace/venv/bin/python", "-m", "ralph.run_ralph_loop", "--help"],
        cwd=repo_path,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )

    assert completed_process.returncode == 0
    assert "Run Ralph task loops with sliced plan context." in completed_process.stdout
    assert "run" in completed_process.stdout
    assert "smoke-test" in completed_process.stdout


def test_parses_exactly_one_promise() -> None:
    assert _parse_agent_promise("done\n<promise>DONE</promise>") == "DONE"
    assert _parse_agent_promise(
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
        _parse_agent_promise("No promise here.")


def test_parse_args_streams_agent_output_by_default() -> None:
    arguments = _parse_arguments([
        "run",
        "--repo-path",
        "/tmp/repo",
        "--job-name",
        "example",
    ])

    assert arguments.tee_agent_output is True


def test_parse_args_can_disable_agent_output_teeing() -> None:
    arguments = _parse_arguments([
        "run",
        "--repo-path",
        "/tmp/repo",
        "--job-name",
        "example",
        "--no-tee-agent-output",
    ])

    assert arguments.tee_agent_output is False


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


def test_parse_args_defaults_to_codex_backend_without_eager_command_resolution(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("RALPH_AGENT_COMMAND", "custom-agent")
    monkeypatch.setenv("RALPH_CODEX_COMMAND", "custom-codex")

    arguments = _parse_arguments([
        "run",
        "--repo-path",
        "/tmp/repo",
        "--job-name",
        "example",
    ])

    assert arguments.agent_backend == "codex"
    assert arguments.agent_command is None


def test_parse_args_accepts_agent_backend_for_run_and_smoke_test() -> None:
    run_arguments = _parse_arguments([
        "run",
        "--repo-path",
        "/tmp/repo",
        "--job-name",
        "example",
        "--agent-backend",
        "claude",
    ])
    smoke_arguments = _parse_arguments([
        "smoke-test",
        "--repo-path",
        "/tmp/repo",
        "--agent-backend",
        "claude",
    ])

    assert run_arguments.agent_backend == "claude"
    assert smoke_arguments.agent_backend == "claude"


def test_find_ralph_job_uses_workspace_home_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("RALPH_HOME", raising=False)

    job = _find_ralph_job("example")

    assert job.job_path == Path("/workspace/.ralph/jobs/example")
    assert job.plan_path == Path("/workspace/.ralph/jobs/example/PLAN.md")


def test_find_ralph_job_uses_explicit_ralph_home(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ralph_home_path = tmp_path / "ralph-home"
    monkeypatch.setenv("RALPH_HOME", str(ralph_home_path))

    job = _find_ralph_job("example")

    assert job.job_path == ralph_home_path / "jobs" / "example"


def test_smoke_test_resolves_repo_path_before_running_sandbox_check(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo_path = tmp_path / "target-repo"
    repo_path.mkdir()
    observed_repo_paths: list[Path] = []

    def run_agent_visibility_smoke_test_mock(
        repo_path: Path,
        agent_backend: str,
        agent_command: str | None,
        python_venv_path: Path | None,
    ) -> None:
        observed_repo_paths.append(repo_path)

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        "ralph.run_ralph_loop.run_agent_visibility_smoke_test",
        run_agent_visibility_smoke_test_mock,
    )

    main([
        "smoke-test",
        "--repo-path",
        "target-repo",
        "--agent-command",
        "agent-cli",
    ])

    assert observed_repo_paths == [repo_path]


def test_create_task_directory_prefixes_task_id(tmp_path: Path) -> None:
    task_path = _create_task_directory(tmp_path, "R1")

    assert task_path.name.startswith("R1_")
    assert task_path.is_dir()


def test_create_task_directory_sanitizes_task_id(tmp_path: Path) -> None:
    task_path = _create_task_directory(tmp_path, "R 1/cleanup")

    assert task_path.name.startswith("R-1-cleanup_")
    assert task_path.is_dir()


def test_refuse_unsafe_starting_state_rejects_sensitive_repo_mount(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo_path = initialise_git_repo(tmp_path / "target-repo")
    job = create_job_with_ledger(tmp_path, build_example_ledger())
    sensitive_state_path = repo_path / ".aws"
    sensitive_state_path.mkdir()
    monkeypatch.setattr(
        "ralph.sandbox.build_sensitive_paths_that_workers_must_not_see",
        lambda: [sensitive_state_path],
    )

    with pytest.raises(ValueError, match="Target repo must not overlap"):
        _refuse_unsafe_starting_state(repo_path, job)


def test_refuse_unsafe_starting_state_accepts_public_ralph_examples(tmp_path: Path) -> None:
    repo_path = initialise_git_repo(tmp_path / "target-repo")
    job = create_job_with_ledger(tmp_path, build_example_ledger())
    example_plan_path = repo_path / "ralph" / "examples" / "PLAN.md"
    example_plan_path.parent.mkdir(parents=True)
    example_plan_path.write_text("Example Ralph plan.")
    run_git(repo_path, "add", ".")
    run_git(repo_path, "commit", "-m", "Add example Ralph plan")

    _refuse_unsafe_starting_state(repo_path, job)


def test_marks_task_done_without_mutating_input() -> None:
    ledger = build_example_ledger()

    updated_ledger = _mark_task_done(ledger, "R1")

    assert ledger["tasks"][0]["status"] == "pending"
    assert updated_ledger["tasks"][0]["status"] == "done"
    assert "completed_at" in updated_ledger["tasks"][0]


def test_accepts_worker_completed_task_after_worker_verifies_and_commits(
    tmp_path: Path,
) -> None:
    repo_path = initialise_git_repo(tmp_path / "target-repo")
    ledger = build_example_ledger()
    job = create_job_with_ledger(tmp_path, ledger)
    task_path = tmp_path / "task"
    parser_path = repo_path / "src" / "parser.py"
    parser_path.parent.mkdir()
    parser_path.write_text("def parse_value(value):\n    return value\n")
    run_git(repo_path, "add", ".")
    run_git(repo_path, "commit", "--no-verify", "-m", "Ralph: R1 Add parser")
    worker_commit_hash = run_git(repo_path, "rev-parse", "HEAD").strip()
    agent_output = "\n".join(
        [
            "RALPH_VERIFICATION_BEGIN",
            "$ test -f src/parser.py",
            "RALPH_VERIFICATION_END",
            f"RALPH_COMMIT {worker_commit_hash}",
            "<promise>DONE</promise>",
        ]
    )

    accepted_commit_hash = _accept_worker_completed_task(
        repo_path=repo_path,
        job=job,
        ledger=ledger,
        selection=select_first_task(ledger),
        task_path=task_path,
        agent_output=agent_output,
    )

    committed_subject = run_git(repo_path, "log", "--format=%s", "-1").strip()

    assert accepted_commit_hash == worker_commit_hash
    assert committed_subject == "Ralph: R1 Add parser"
    assert yaml.safe_load(job.ledger_path.read_text())["tasks"][0]["status"] == "done"
    assert "$ test -f src/parser.py" in task_path.joinpath("verification-output.txt").read_text()
    assert task_path.joinpath("commit.txt").read_text() == worker_commit_hash


def test_accept_worker_completed_task_rejects_uncommitted_worker_changes(
    tmp_path: Path,
) -> None:
    repo_path = initialise_git_repo(tmp_path / "target-repo")
    ledger = build_example_ledger()
    job = create_job_with_ledger(tmp_path, ledger)
    task_path = tmp_path / "task"
    parser_path = repo_path / "src" / "parser.py"
    parser_path.parent.mkdir()
    parser_path.write_text("def parse_value(value):\n    return value\n")
    run_git(repo_path, "add", ".")
    run_git(repo_path, "commit", "--no-verify", "-m", "Ralph: R1 Add parser")
    worker_commit_hash = run_git(repo_path, "rev-parse", "HEAD").strip()
    parser_path.write_text("def parse_value(value):\n    return value.strip()\n")
    agent_output = "\n".join(
        [
            "RALPH_VERIFICATION_BEGIN",
            "$ test -f src/parser.py",
            "RALPH_VERIFICATION_END",
            f"RALPH_COMMIT {worker_commit_hash}",
            "<promise>DONE</promise>",
        ]
    )

    with pytest.raises(RuntimeError, match="uncommitted target repo changes"):
        _accept_worker_completed_task(
            repo_path=repo_path,
            job=job,
            ledger=ledger,
            selection=select_first_task(ledger),
            task_path=task_path,
            agent_output=agent_output,
        )

    assert yaml.safe_load(job.ledger_path.read_text())["tasks"][0]["status"] == "pending"
    assert "$ test -f src/parser.py" in task_path.joinpath("verification-output.txt").read_text()
    assert task_path.joinpath("commit.txt").read_text() == worker_commit_hash


def test_accept_worker_completed_task_rejects_missing_verification_transcript(
    tmp_path: Path,
) -> None:
    repo_path = initialise_git_repo(tmp_path / "target-repo")
    ledger = build_example_ledger()
    job = create_job_with_ledger(tmp_path, ledger)

    with pytest.raises(RuntimeError, match="verification transcript entries"):
        _accept_worker_completed_task(
            repo_path=repo_path,
            job=job,
            ledger=ledger,
            selection=select_first_task(ledger),
            task_path=tmp_path / "task",
            agent_output="\n".join(
                [
                    "RALPH_VERIFICATION_BEGIN",
                    "$ python -m pytest",
                    "RALPH_VERIFICATION_END",
                    f"RALPH_COMMIT {run_git(repo_path, 'rev-parse', 'HEAD').strip()}",
                    "<promise>DONE</promise>",
                ]
            ),
        )

    assert yaml.safe_load(job.ledger_path.read_text())["tasks"][0]["status"] == "pending"


def test_validate_and_log_worker_worklog_sends_worklog_to_notion(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from ralph.run_ralph_loop import _validate_and_log_worker_worklog

    repo_path = initialise_git_repo(tmp_path / "target-repo")
    ledger = build_ledger_with_materialised_notion_task()
    task_path = tmp_path / "task"
    task_path.mkdir()
    worklog_path = repo_path / WORKER_NOTION_WORKLOG_FILENAME
    worklog_path.write_text('{"subheading": "Task done", "blocks": [{"type": "paragraph", "text": "Work summary"}]}')
    observed_content = capture_notion_log_content(monkeypatch)

    worklog = _validate_and_log_worker_worklog(
        repo_path=repo_path,
        selection=select_first_task(ledger),
        task_path=task_path,
    )

    assert worklog is not None
    assert worklog["subheading"] == "Task done"
    assert observed_content["subheading"] == "Task done"
    assert observed_content["blocks"][0]["text"] == "Work summary"
    assert not worklog_path.exists()


def test_validate_and_log_worker_worklog_skips_when_no_notion_task(
    tmp_path: Path,
) -> None:
    from ralph.run_ralph_loop import _validate_and_log_worker_worklog

    repo_path = initialise_git_repo(tmp_path / "target-repo")
    ledger = build_example_ledger()
    task_path = tmp_path / "task"
    task_path.mkdir()

    worklog = _validate_and_log_worker_worklog(
        repo_path=repo_path,
        selection=select_first_task(ledger),
        task_path=task_path,
    )

    assert worklog is None


def test_validate_and_log_worker_worklog_raises_on_missing_worklog(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from ralph.run_ralph_loop import _validate_and_log_worker_worklog

    repo_path = initialise_git_repo(tmp_path / "target-repo")
    ledger = build_ledger_with_materialised_notion_task()
    task_path = tmp_path / "task"
    task_path.mkdir()
    monkeypatch.setattr("ralph.notion._resolve_notion_tracker_command_path", lambda: "ntt")

    with pytest.raises(WorklogValidationError, match="Worker worklog file not found"):
        _validate_and_log_worker_worklog(
            repo_path=repo_path,
            selection=select_first_task(ledger),
            task_path=task_path,
        )


def test_validate_and_log_worker_worklog_raises_on_malformed_worklog(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from ralph.run_ralph_loop import _validate_and_log_worker_worklog

    repo_path = initialise_git_repo(tmp_path / "target-repo")
    ledger = build_ledger_with_materialised_notion_task()
    task_path = tmp_path / "task"
    task_path.mkdir()
    worklog_path = repo_path / WORKER_NOTION_WORKLOG_FILENAME
    worklog_path.write_text('{"subheading": "Task done"}')
    monkeypatch.setattr("ralph.notion._resolve_notion_tracker_command_path", lambda: "ntt")

    with pytest.raises(WorklogValidationError, match="missing required field: blocks"):
        _validate_and_log_worker_worklog(
            repo_path=repo_path,
            selection=select_first_task(ledger),
            task_path=task_path,
        )

