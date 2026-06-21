from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from ralph.tests.conftest import (
    build_example_ledger,
    create_job_with_ledger,
    initialise_git_repo,
    run_git,
    select_first_task,
)
from ralph.run_ralph_loop import (
    _accept_worker_completed_task,
    _create_task_directory,
    _extract_worker_worklog_json,
    _find_ralph_job,
    main,
    _mark_task_done,
    _parse_arguments,
    _parse_agent_promise,
    _refuse_unsafe_starting_state,
    extract_worker_worklog,
    DEFAULT_WORKLOG_FALLBACK,
    DEFAULT_WORKLOG_JSON_FALLBACK,
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
    import json

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
            "RALPH_WORKLOG_JSON_BEGIN",
            json.dumps({"commands_run": ["test"], "relevant_outputs_or_errors": "", "files_changed": {}, "decisions_made": [], "unresolved_risks": [], "notion_log_command": None, "notion_log_result": None}),
            "RALPH_WORKLOG_JSON_END",
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
    assert task_path.joinpath("worker-worklog.json").is_file()


def test_accept_worker_completed_task_rejects_uncommitted_worker_changes(
    tmp_path: Path,
) -> None:
    import json

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
            "RALPH_WORKLOG_JSON_BEGIN",
            json.dumps({"commands_run": [], "relevant_outputs_or_errors": "", "files_changed": {}, "decisions_made": [], "unresolved_risks": [], "notion_log_command": None, "notion_log_result": None}),
            "RALPH_WORKLOG_JSON_END",
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
    import json as json_module

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
                    "RALPH_WORKLOG_JSON_BEGIN",
                    json_module.dumps({"commands_run": [], "relevant_outputs_or_errors": "", "files_changed": {}, "decisions_made": [], "unresolved_risks": [], "notion_log_command": None, "notion_log_result": None}),
                    "RALPH_WORKLOG_JSON_END",
                    "RALPH_VERIFICATION_BEGIN",
                    "$ python -m pytest",
                    "RALPH_VERIFICATION_END",
                    f"RALPH_COMMIT {run_git(repo_path, 'rev-parse', 'HEAD').strip()}",
                    "<promise>DONE</promise>",
                ]
            ),
        )

    assert yaml.safe_load(job.ledger_path.read_text())["tasks"][0]["status"] == "pending"


def test_extract_worker_worklog_returns_block_content() -> None:
    agent_output = "\n".join([
        "Working on the task...",
        "RALPH_WORKLOG_BEGIN",
        "Ran pytest: all tests pass.",
        "Changed src/parser.py to add validation.",
        "RALPH_WORKLOG_END",
        "Done.",
    ])

    worklog = extract_worker_worklog(agent_output)

    assert worklog == "Ran pytest: all tests pass.\nChanged src/parser.py to add validation."


def test_extract_worker_worklog_returns_fallback_when_no_block() -> None:
    agent_output = "No worklog block here.\n<promise>BLOCKED</promise>"

    worklog = extract_worker_worklog(agent_output)

    assert worklog == DEFAULT_WORKLOG_FALLBACK


def test_extract_worker_worklog_rejects_multiple_blocks_for_done() -> None:
    agent_output = "\n".join([
        "RALPH_WORKLOG_BEGIN",
        "First worklog.",
        "RALPH_WORKLOG_END",
        "RALPH_WORKLOG_BEGIN",
        "Second worklog.",
        "RALPH_WORKLOG_END",
    ])

    with pytest.raises(RuntimeError, match="at most one RALPH_WORKLOG block"):
        extract_worker_worklog(agent_output, require_unique_for_done=True)


def test_extract_worker_worklog_uses_first_block_when_multiple_and_not_done() -> None:
    agent_output = "\n".join([
        "RALPH_WORKLOG_BEGIN",
        "First worklog.",
        "RALPH_WORKLOG_END",
        "RALPH_WORKLOG_BEGIN",
        "Second worklog.",
        "RALPH_WORKLOG_END",
    ])

    worklog = extract_worker_worklog(agent_output, require_unique_for_done=False)

    assert worklog == "First worklog."


def test_extract_worker_worklog_json_returns_parsed_json() -> None:
    import json as json_module

    worklog_data = {
        "commands_run": ["pytest"],
        "relevant_outputs_or_errors": "all pass",
        "files_changed": {"src/a.py": "added"},
        "decisions_made": ["choice A"],
        "unresolved_risks": [],
        "notion_log_command": None,
        "notion_log_result": None,
    }
    agent_output = "\n".join([
        "RALPH_WORKLOG_JSON_BEGIN",
        json_module.dumps(worklog_data),
        "RALPH_WORKLOG_JSON_END",
    ])

    result = _extract_worker_worklog_json(agent_output, require_valid_for_done=True)

    assert result["commands_run"] == ["pytest"]
    assert result["files_changed"] == {"src/a.py": "added"}


def test_extract_worker_worklog_json_returns_fallback_when_missing_and_not_required() -> None:
    agent_output = "No worklog JSON here."

    result = _extract_worker_worklog_json(agent_output, require_valid_for_done=False)

    assert "error" in result


def test_extract_worker_worklog_json_raises_when_missing_and_required() -> None:
    agent_output = "No worklog JSON here."

    with pytest.raises(RuntimeError, match="exactly one RALPH_WORKLOG_JSON"):
        _extract_worker_worklog_json(agent_output, require_valid_for_done=True)


def test_extract_worker_worklog_json_rejects_non_object_for_done() -> None:
    agent_output = "\n".join([
        "RALPH_WORKLOG_JSON_BEGIN",
        '["this", "is", "an", "array"]',
        "RALPH_WORKLOG_JSON_END",
    ])

    with pytest.raises(RuntimeError, match="must be a top-level object"):
        _extract_worker_worklog_json(agent_output, require_valid_for_done=True)


def test_extract_worker_worklog_json_tolerates_malformed_when_not_required() -> None:
    agent_output = "\n".join([
        "RALPH_WORKLOG_JSON_BEGIN",
        "{invalid json",
        "RALPH_WORKLOG_JSON_END",
    ])

    result = _extract_worker_worklog_json(agent_output, require_valid_for_done=False)

    assert "error" in result
    assert "raw_text" in result


def test_accept_worker_completed_task_writes_worklog_json_file(tmp_path: Path) -> None:
    import json as json_module

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
    worklog_json = {
        "commands_run": ["test -f src/parser.py"],
        "relevant_outputs_or_errors": "Ran verification: test passed.",
        "files_changed": {"src/parser.py": "Created with parse_value function."},
        "decisions_made": [],
        "unresolved_risks": [],
        "notion_log_command": None,
        "notion_log_result": None,
    }
    agent_output = "\n".join([
        "RALPH_WORKLOG_JSON_BEGIN",
        json_module.dumps(worklog_json),
        "RALPH_WORKLOG_JSON_END",
        "RALPH_VERIFICATION_BEGIN",
        "$ test -f src/parser.py",
        "RALPH_VERIFICATION_END",
        f"RALPH_COMMIT {worker_commit_hash}",
        "<promise>DONE</promise>",
    ])

    _accept_worker_completed_task(
        repo_path=repo_path,
        job=job,
        ledger=ledger,
        selection=select_first_task(ledger),
        task_path=task_path,
        agent_output=agent_output,
    )

    worklog_path = task_path / "worker-worklog.json"
    assert worklog_path.is_file()
    written_worklog = json_module.loads(worklog_path.read_text())
    assert "src/parser.py" in written_worklog["files_changed"]


def test_accept_worker_completed_task_rejects_done_with_multiple_worklog_json_blocks(
    tmp_path: Path,
) -> None:
    import json as json_module

    repo_path = initialise_git_repo(tmp_path / "target-repo")
    ledger = build_example_ledger()
    job = create_job_with_ledger(tmp_path, ledger)
    task_path = tmp_path / "task"
    worker_commit_hash = run_git(repo_path, "rev-parse", "HEAD").strip()
    agent_output = "\n".join([
        "RALPH_WORKLOG_JSON_BEGIN",
        json_module.dumps({"commands_run": [], "relevant_outputs_or_errors": "first", "files_changed": {}, "decisions_made": [], "unresolved_risks": [], "notion_log_command": None, "notion_log_result": None}),
        "RALPH_WORKLOG_JSON_END",
        "RALPH_WORKLOG_JSON_BEGIN",
        json_module.dumps({"commands_run": [], "relevant_outputs_or_errors": "second", "files_changed": {}, "decisions_made": [], "unresolved_risks": [], "notion_log_command": None, "notion_log_result": None}),
        "RALPH_WORKLOG_JSON_END",
        "RALPH_VERIFICATION_BEGIN",
        "$ test -f src/parser.py",
        "RALPH_VERIFICATION_END",
        f"RALPH_COMMIT {worker_commit_hash}",
        "<promise>DONE</promise>",
    ])

    with pytest.raises(RuntimeError, match="exactly one RALPH_WORKLOG_JSON"):
        _accept_worker_completed_task(
            repo_path=repo_path,
            job=job,
            ledger=ledger,
            selection=select_first_task(ledger),
            task_path=task_path,
            agent_output=agent_output,
        )

    assert yaml.safe_load(job.ledger_path.read_text())["tasks"][0]["status"] == "pending"


def test_accept_worker_completed_task_rejects_done_with_missing_worklog_json(
    tmp_path: Path,
) -> None:
    repo_path = initialise_git_repo(tmp_path / "target-repo")
    ledger = build_example_ledger()
    job = create_job_with_ledger(tmp_path, ledger)
    task_path = tmp_path / "task"
    worker_commit_hash = run_git(repo_path, "rev-parse", "HEAD").strip()
    agent_output = "\n".join([
        "RALPH_VERIFICATION_BEGIN",
        "$ test -f src/parser.py",
        "RALPH_VERIFICATION_END",
        f"RALPH_COMMIT {worker_commit_hash}",
        "<promise>DONE</promise>",
    ])

    with pytest.raises(RuntimeError, match="exactly one RALPH_WORKLOG_JSON"):
        _accept_worker_completed_task(
            repo_path=repo_path,
            job=job,
            ledger=ledger,
            selection=select_first_task(ledger),
            task_path=task_path,
            agent_output=agent_output,
        )

    assert yaml.safe_load(job.ledger_path.read_text())["tasks"][0]["status"] == "pending"


def test_accept_worker_completed_task_rejects_done_with_malformed_json(
    tmp_path: Path,
) -> None:
    repo_path = initialise_git_repo(tmp_path / "target-repo")
    ledger = build_example_ledger()
    job = create_job_with_ledger(tmp_path, ledger)
    task_path = tmp_path / "task"
    worker_commit_hash = run_git(repo_path, "rev-parse", "HEAD").strip()
    agent_output = "\n".join([
        "RALPH_WORKLOG_JSON_BEGIN",
        "{invalid json here",
        "RALPH_WORKLOG_JSON_END",
        "RALPH_VERIFICATION_BEGIN",
        "$ test -f src/parser.py",
        "RALPH_VERIFICATION_END",
        f"RALPH_COMMIT {worker_commit_hash}",
        "<promise>DONE</promise>",
    ])

    with pytest.raises(RuntimeError, match="worklog JSON is malformed"):
        _accept_worker_completed_task(
            repo_path=repo_path,
            job=job,
            ledger=ledger,
            selection=select_first_task(ledger),
            task_path=task_path,
            agent_output=agent_output,
        )

    assert yaml.safe_load(job.ledger_path.read_text())["tasks"][0]["status"] == "pending"
