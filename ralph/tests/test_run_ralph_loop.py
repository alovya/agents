from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from ralph.agent_backends import AgentBackend, AgentResult
from ralph.tests.conftest import (
    build_example_ledger,
    build_example_plan,
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
    _pause_for_human_review_after_accepting_worker_completed_task,
    _refuse_unsafe_starting_state,
    _run_agent,
    _run_agent_command,
    _save_worker_prompt_before_launch,
    _finish_when_iteration_limit_reaches_complete_job,
    _write_yaml_file,
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
    assert "validate" in completed_process.stdout
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
    assert "validate" in completed_process.stdout
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


def test_parse_args_can_pause_for_review_between_tasks() -> None:
    arguments = _parse_arguments([
        "run",
        "--repo-path",
        "/tmp/repo",
        "--job-name",
        "example",
        "--ask-for-review",
    ])

    assert arguments.ask_for_review is True


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


def test_parse_args_accepts_validate_command() -> None:
    arguments = _parse_arguments([
        "validate",
        "--job-name",
        "example",
        "--repo-path",
        "/tmp/repo",
    ])

    assert arguments.command == "validate"
    assert arguments.job_name == "example"
    assert arguments.repo_path == "/tmp/repo"


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


def test_claude_runtime_error_points_at_readable_transcript_then_raw_stream(
    tmp_path: Path,
) -> None:
    output_path = tmp_path / "agent-output.txt"
    agent_backend = AgentBackend(
        backend_name="claude",
        command_name="/workspace/venv/bin/python",
        agent_config_dir=tmp_path / "claude-config",
        agent_home_environment_variable="CLAUDE_CONFIG_DIR",
    )

    with pytest.raises(RuntimeError) as error:
        _run_agent_command(
            command=[
                "/workspace/venv/bin/python",
                "-c",
                "import sys; sys.stdout.write('{}\\n'); sys.exit(7)",
            ],
            prompt="prompt ignored by failing agent\n",
            output_path=output_path,
            tee_output=False,
            agent_backend=agent_backend,
        )

    assert str(error.value).splitlines() == [
        f"Agent failed with exit code 7. See readable transcript: {output_path}",
        f"Raw Claude stream: {tmp_path / 'agent-output.raw.jsonl'}",
    ]


def test_run_agent_uses_prepared_codex_worker_home(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    master_codex_home_path = tmp_path / "master-codex-home"
    repo_path = tmp_path / "target-repo"
    task_path = tmp_path / "task"
    output_path = tmp_path / "agent-output.txt"
    master_codex_home_path.mkdir()
    repo_path.mkdir()
    task_path.mkdir()
    monkeypatch.setenv("CODEX_HOME", str(master_codex_home_path))

    observed_worker_agent_backend: dict[str, AgentBackend] = {}
    observed_worker_rules_existed: list[bool] = []

    def build_bwrap_agent_command_mock(
        repo_path: Path,
        agent_backend: AgentBackend,
        python_venv_path: Path | None,
        allowed_bash_commands: list[str] | None = None,
    ) -> list[str]:
        observed_worker_agent_backend["bwrap"] = agent_backend
        return ["fake-bwrap-command"]

    def _run_agent_command_mock(
        command: list[str],
        prompt: str,
        output_path: Path,
        tee_output: bool,
        agent_backend: AgentBackend,
    ) -> AgentResult:
        observed_worker_agent_backend["agent"] = agent_backend
        observed_worker_rules_existed.append(
            agent_backend.agent_config_dir.joinpath("rules", "default.rules").is_file()
        )
        return AgentResult(promise="DONE", output="<promise>DONE</promise>")

    monkeypatch.setattr(
        "ralph.run_ralph_loop.build_bwrap_agent_command",
        build_bwrap_agent_command_mock,
    )
    monkeypatch.setattr("ralph.run_ralph_loop._run_agent_command", _run_agent_command_mock)

    agent_result = _run_agent(
        repo_path=repo_path,
        task={"allowed_bash_commands": ["rg *"]},
        prompt="Worker prompt",
        agent_backend_name="codex",
        agent_command="codex",
        python_venv_path=None,
        output_path=output_path,
        tee_output=False,
        task_path=task_path,
    )

    worker_codex_home_path = observed_worker_agent_backend["agent"].agent_config_dir
    assert agent_result.promise == "DONE"
    assert observed_worker_agent_backend["bwrap"] == observed_worker_agent_backend["agent"]
    assert worker_codex_home_path != master_codex_home_path
    assert observed_worker_rules_existed == [True]
    assert not master_codex_home_path.joinpath("rules", "default.rules").exists()
    assert not worker_codex_home_path.exists()


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


def test_validate_accepts_example_job(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    ralph_home_path = _create_ralph_home_with_example_job(tmp_path, monkeypatch)

    main(["validate", "--job-name", "example"])

    output = capsys.readouterr().out

    assert "Ralph job example is valid" in output
    assert "Next runnable task: R1" in output
    assert not ralph_home_path.joinpath("jobs", "example", "tasks").exists()


def test_iteration_limit_finishes_when_last_allowed_worker_completed_the_job(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _create_ralph_home_with_example_job(tmp_path, monkeypatch)
    job = _find_ralph_job("example")
    ledger = yaml.safe_load(job.ledger_path.read_text())
    for task in ledger["tasks"]:
        task["status"] = "done"
    _write_yaml_file(job.ledger_path, ledger)

    _finish_when_iteration_limit_reaches_complete_job(job=job, max_iterations=2)

    assert capsys.readouterr().out == "No runnable Ralph tasks remain.\n"


def test_iteration_limit_still_fails_when_runnable_work_remains(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _create_ralph_home_with_example_job(tmp_path, monkeypatch)
    job = _find_ralph_job("example")

    with pytest.raises(SystemExit, match="Reached max iterations: 1"):
        _finish_when_iteration_limit_reaches_complete_job(job=job, max_iterations=1)


def test_validate_with_repo_path_runs_starting_state_checks(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ralph_home_path = _create_ralph_home_with_example_job(tmp_path, monkeypatch)
    repo_path = initialise_git_repo(tmp_path / "target-repo")

    main(["validate", "--job-name", "example", "--repo-path", str(repo_path)])

    assert not ralph_home_path.joinpath("jobs", "example", "tasks").exists()


@pytest.mark.parametrize(
    ("missing_filename", "expected_message"),
    [
        ("PLAN.md", "Missing Ralph plan"),
        ("ledger.yaml", "Missing Ralph ledger"),
    ],
)
def test_validate_rejects_missing_job_files(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    missing_filename: str,
    expected_message: str,
) -> None:
    _create_ralph_home_with_example_job(tmp_path, monkeypatch)
    job_path = tmp_path / "ralph-home" / "jobs" / "example"
    job_path.joinpath(missing_filename).unlink()

    with pytest.raises(FileNotFoundError, match=expected_message):
        main(["validate", "--job-name", "example"])


@pytest.mark.parametrize(
    ("plan_text", "expected_message"),
    [
        (
            "<!-- ralph-task:start R1 -->\n"
            "Task context.\n"
            "<!-- ralph-allowed-bash:start -->\n"
            "- rg *\n"
            "<!-- ralph-allowed-bash:end -->\n"
            "<!-- ralph-verification:start -->\n"
            "- test -f src/parser.py\n"
            "<!-- ralph-verification:end -->\n"
            "<!-- ralph-task:end R1 -->\n",
            "ralph-shared block",
        ),
        (
            "<!-- ralph-shared:start -->\n"
            "Shared context.\n"
            "<!-- ralph-shared:end -->\n",
            "missing Ralph task blocks",
        ),
        (
            "<!-- ralph-shared:start -->\n"
            "Shared context.\n"
            "<!-- ralph-shared:end -->\n\n"
            "<!-- ralph-task:start R1 -->\n"
            "Task context.\n"
            "<!-- ralph-verification:start -->\n"
            "- test -f src/parser.py\n"
            "<!-- ralph-verification:end -->\n"
            "<!-- ralph-task:end R1 -->\n",
            "ralph-allowed-bash block",
        ),
        (
            "<!-- ralph-shared:start -->\n"
            "Shared context.\n"
            "<!-- ralph-shared:end -->\n\n"
            "<!-- ralph-task:start R1 -->\n"
            "Task context.\n"
            "<!-- ralph-allowed-bash:start -->\n"
            "- rg *\n"
            "<!-- ralph-allowed-bash:end -->\n"
            "<!-- ralph-task:end R1 -->\n",
            "ralph-verification block",
        ),
    ],
)
def test_validate_rejects_malformed_plan(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    plan_text: str,
    expected_message: str,
) -> None:
    _create_ralph_home_with_job(
        tmp_path=tmp_path,
        monkeypatch=monkeypatch,
        plan_text=plan_text,
        ledger=build_example_ledger(),
    )

    with pytest.raises(ValueError, match=expected_message):
        main(["validate", "--job-name", "example"])


@pytest.mark.parametrize("command_policy_key", ["allowed_bash_commands", "verification_commands"])
def test_validate_rejects_command_policy_copied_into_ledger(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    command_policy_key: str,
) -> None:
    ledger = build_example_ledger()
    ledger["tasks"][0][command_policy_key] = ["rg *"]
    _create_ralph_home_with_job(
        tmp_path=tmp_path,
        monkeypatch=monkeypatch,
        plan_text=build_example_plan(),
        ledger=ledger,
    )

    with pytest.raises(ValueError, match=f"must keep {command_policy_key} in PLAN.md"):
        main(["validate", "--job-name", "example"])


def test_validate_rejects_unknown_task_dependencies(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ledger = build_example_ledger()
    ledger["tasks"][1]["depends_on"] = ["R404"]
    _create_ralph_home_with_job(
        tmp_path=tmp_path,
        monkeypatch=monkeypatch,
        plan_text=build_example_plan(),
        ledger=ledger,
    )

    with pytest.raises(ValueError, match="depends on unknown Ralph tasks"):
        main(["validate", "--job-name", "example"])


def test_validate_rejects_invalid_notion_task_relationships(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ledger = build_example_ledger()
    ledger["tasks"][1]["notion_task"] = {
        "planned": True,
        "relationship": "child",
        "related_to": "R1",
        "title": "Add command line entrypoint",
        "materialized_task_id": None,
    }
    ledger["tasks"][1]["depends_on"] = []
    _create_ralph_home_with_job(
        tmp_path=tmp_path,
        monkeypatch=monkeypatch,
        plan_text=build_example_plan(),
        ledger=ledger,
    )

    with pytest.raises(ValueError, match="must depend on related Ralph task"):
        main(["validate", "--job-name", "example"])


def test_smoke_test_resolves_repo_path_before_running_sandbox_check(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    repo_path = tmp_path / "target-repo"
    repo_path.mkdir()
    observed_repo_paths: list[Path] = []

    def run_agent_visibility_smoke_test_mock(
        repo_path: Path,
        agent_backend_name: str,
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
    assert capsys.readouterr().out == "Ralph codex smoke test passed.\n"


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


def test_refuse_unsafe_starting_state_accepts_ordinary_repo_plan_docs(tmp_path: Path) -> None:
    repo_path = initialise_git_repo(tmp_path / "target-repo")
    job = create_job_with_ledger(tmp_path, build_example_ledger())
    plan_doc_path = repo_path / "product" / "PLAN.md"
    plan_doc_path.parent.mkdir(parents=True)
    plan_doc_path.write_text("Public product plan.")
    run_git(repo_path, "add", ".")
    run_git(repo_path, "commit", "-m", "Add public plan doc")

    _refuse_unsafe_starting_state(repo_path, job)


def test_refuse_unsafe_starting_state_still_rejects_private_ralph_ledgers(tmp_path: Path) -> None:
    repo_path = initialise_git_repo(tmp_path / "target-repo")
    job = create_job_with_ledger(tmp_path, build_example_ledger())
    private_job_path = repo_path / "private-job"
    private_job_path.mkdir()
    private_job_path.joinpath("PLAN.md").write_text("Private Ralph plan.")
    private_job_path.joinpath("ledger.yaml").write_text("tasks: []")
    run_git(repo_path, "add", ".")
    run_git(repo_path, "commit", "-m", "Add private Ralph files")

    with pytest.raises(RuntimeError, match="ledger.yaml exists under the target repo"):
        _refuse_unsafe_starting_state(repo_path, job)


def test_marks_task_done_without_mutating_input() -> None:
    ledger = build_example_ledger()

    updated_ledger = _mark_task_done(ledger, "R1")

    assert ledger["tasks"][0]["status"] == "pending"
    assert updated_ledger["tasks"][0]["status"] == "done"
    assert "completed_at" in updated_ledger["tasks"][0]


def test_save_worker_prompt_before_launch_writes_sliced_prompt_as_markdown(
    tmp_path: Path,
) -> None:
    task_path = tmp_path / "task"

    _save_worker_prompt_before_launch(
        task_path=task_path,
        prompt="# Worker prompt\n\nSliced task context.",
    )

    assert task_path.joinpath("PROMPT.md").read_text() == "# Worker prompt\n\nSliced task context."


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


def test_review_pause_exposes_accepted_worker_commit_as_uncommitted_diff(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
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
    observed_review_status: list[str] = []

    def input_mock(prompt: str) -> str:
        observed_review_status.append(run_git(repo_path, "status", "--short"))
        parser_path.write_text("def parse_value(value):\n    return value.strip()\n")
        return ""

    monkeypatch.setattr("builtins.input", input_mock)

    reviewed_commit_hash = _pause_for_human_review_after_accepting_worker_completed_task(
        repo_path=repo_path,
        task=select_first_task(ledger).task,
        task_path=task_path,
        accepted_commit_hash=accepted_commit_hash,
    )

    assert observed_review_status == ["?? src/\n"]
    assert reviewed_commit_hash != worker_commit_hash
    assert run_git(repo_path, "status", "--short") == ""
    assert run_git(repo_path, "log", "--format=%s", "-1").strip() == "Ralph: R1 Add parser"
    assert parser_path.read_text() == "def parse_value(value):\n    return value.strip()\n"
    assert task_path.joinpath("commit.txt").read_text() == reviewed_commit_hash


def test_accepts_worker_completed_task_after_prompt_examples_and_final_worker_markers(
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
            "Prompt example:",
            "RALPH_VERIFICATION_BEGIN",
            "$ <verification command>",
            "<command output>",
            "RALPH_VERIFICATION_END",
            "RALPH_COMMIT 0000000000000000000000000000000000000000",
            "Worker final answer:",
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

    assert accepted_commit_hash == worker_commit_hash
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
    worklog_path.write_text('{"title": "Task done", "blocks": [{"type": "paragraph", "text": "Work summary"}]}')
    observed_content = capture_notion_log_content(monkeypatch)

    worklog = _validate_and_log_worker_worklog(
        repo_path=repo_path,
        selection=select_first_task(ledger),
        task_path=task_path,
    )

    assert worklog is not None
    assert worklog["title"] == "Task done"
    assert observed_content["title"] == "Task done"
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
    worklog_path.write_text('{"title": "Task done"}')
    monkeypatch.setattr("ralph.notion._resolve_notion_tracker_command_path", lambda: "ntt")

    with pytest.raises(WorklogValidationError, match="missing required field: blocks"):
        _validate_and_log_worker_worklog(
            repo_path=repo_path,
            selection=select_first_task(ledger),
            task_path=task_path,
        )


def _create_ralph_home_with_example_job(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> Path:
    examples_path = Path(__file__).resolve().parents[1] / "examples"
    ledger = yaml.safe_load(examples_path.joinpath("ledger.yaml").read_text())
    return _create_ralph_home_with_job(
        tmp_path=tmp_path,
        monkeypatch=monkeypatch,
        plan_text=examples_path.joinpath("PLAN.md").read_text(),
        ledger=ledger,
    )


def _create_ralph_home_with_job(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    plan_text: str,
    ledger: dict[str, object],
) -> Path:
    ralph_home_path = tmp_path / "ralph-home"
    job_path = ralph_home_path / "jobs" / "example"
    job_path.mkdir(parents=True)
    job_path.joinpath("PLAN.md").write_text(plan_text)
    job_path.joinpath("ledger.yaml").write_text(yaml.safe_dump(ledger, sort_keys=False))
    monkeypatch.setenv("RALPH_HOME", str(ralph_home_path))
    return ralph_home_path
