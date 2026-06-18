from __future__ import annotations

import shlex
import subprocess
from pathlib import Path

import pytest
import yaml

from ralph.run_ralph_loop import (
    RalphJob,
    TaskSelection,
    WORKER_HOME_PATH,
    WORKER_TEMP_PATH,
    _build_agent_visibility_smoke_test_prompt,
    _build_bwrap_codex_command,
    _create_task_directory,
    _commit_verified_task,
    main,
    _verify_task_result,
    _mark_task_done,
    _parse_arguments,
    _parse_agent_promise,
    _read_tasks_from_ledger,
    _refuse_unsafe_starting_state,
    _render_agent_prompt,
    _resolve_python_venv_path,
    _require_codex_home_path,
    _run_agent_visibility_smoke_test,
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


def test_smoke_test_resolves_repo_path_before_running_sandbox_check(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo_path = tmp_path / "target-repo"
    repo_path.mkdir()
    observed_repo_paths: list[Path] = []

    def run_agent_visibility_smoke_test_mock(
        repo_path: Path,
        agent_command: str,
        python_venv_path: Path | None,
    ) -> None:
        observed_repo_paths.append(repo_path)

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        "ralph.run_ralph_loop._run_agent_visibility_smoke_test",
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


def test_run_command_and_tee_output_writes_to_terminal_and_file(
    tmp_path: Path,
    capsys,
) -> None:
    output_path = tmp_path / "agent-output.txt"

    completed_process = _run_command_and_tee_output(
        command=["bash", "-lc", "printf 'before\\n'; cat; printf 'after\\n'"],
        input_text="middle\n",
        output_path=output_path,
    )

    assert completed_process.returncode == 0
    assert completed_process.stdout == "before\nmiddle\nafter\n"
    assert output_path.read_text(encoding="utf-8") == "before\nmiddle\nafter\n"
    assert capsys.readouterr().out == "before\nmiddle\nafter\n"


def test_create_task_directory_prefixes_task_id(tmp_path: Path) -> None:
    task_path = _create_task_directory(tmp_path, "R1")

    assert task_path.name.startswith("R1_")
    assert task_path.is_dir()


def test_create_task_directory_sanitizes_task_id(tmp_path: Path) -> None:
    task_path = _create_task_directory(tmp_path, "R 1/cleanup")

    assert task_path.name.startswith("R-1-cleanup_")
    assert task_path.is_dir()


def test_render_agent_prompt_excludes_unrelated_task_slice(tmp_path: Path) -> None:
    ledger = _build_example_ledger()
    selection = TaskSelection(
        task=ledger["tasks"][0],
        shared_plan_context="Shared context.",
        active_task_plan_context="First task context.",
    )

    prompt = _render_agent_prompt(
        repo_path=tmp_path,
        ledger=ledger,
        selection=selection,
        python_venv_path=None,
    )

    assert "First task context." in prompt
    assert "Second task context." not in prompt
    assert "/.ralph" not in prompt
    assert "Codex" not in prompt


def test_render_agent_prompt_documents_python_venv(tmp_path: Path) -> None:
    ledger = _build_example_ledger()
    selection = TaskSelection(
        task=ledger["tasks"][0],
        shared_plan_context="Shared context.",
        active_task_plan_context="First task context.",
    )
    python_venv_path = tmp_path / "venv"

    prompt = _render_agent_prompt(
        repo_path=tmp_path,
        ledger=ledger,
        selection=selection,
        python_venv_path=python_venv_path,
    )

    assert f"Python venv: {python_venv_path}" in prompt
    assert "already first on PATH" in prompt
    assert "ntt" not in prompt
    assert "Notion" not in prompt


def test_build_bwrap_command_mounts_python_venv_from_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bin_path = tmp_path / "bin"
    bwrap_path = bin_path / "bwrap"
    agent_path = bin_path / "agent-cli"
    codex_home_path = tmp_path / "codex-home"
    python_venv_path = tmp_path / "venv"
    bin_path.mkdir()
    codex_home_path.mkdir()
    python_venv_path.mkdir()
    _write_executable_shim(bwrap_path)
    _write_executable_shim(agent_path)
    monkeypatch.setenv("PATH", str(bin_path))
    monkeypatch.setenv("CODEX_HOME", str(codex_home_path))

    command = _build_bwrap_codex_command(
        repo_path=tmp_path,
        agent_command="agent-cli",
        python_venv_path=python_venv_path,
    )

    assert command[0] == str(bwrap_path)
    assert str(agent_path) in command
    assert _contains_subsequence(command, ["--ro-bind", str(python_venv_path), str(python_venv_path)])
    assert _contains_subsequence(command, ["--setenv", "VIRTUAL_ENV", str(python_venv_path)])
    assert _contains_subsequence(command, ["--setenv", "BASH_ENV", str(python_venv_path / "bin" / "activate")])
    assert str(python_venv_path / "bin") in command[command.index("PATH") + 1].split(":")[0]


def test_build_bwrap_command_uses_allowlisted_worker_environment(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bin_path = tmp_path / "bin"
    bwrap_path = bin_path / "bwrap"
    agent_path = bin_path / "agent-cli"
    repo_path = tmp_path / "target-repo"
    codex_home_path = tmp_path / "codex-home"
    bin_path.mkdir()
    repo_path.mkdir()
    codex_home_path.mkdir()
    _write_executable_shim(bwrap_path)
    _write_executable_shim(agent_path)
    monkeypatch.setenv("PATH", str(bin_path))
    monkeypatch.setenv("CODEX_HOME", str(codex_home_path))
    monkeypatch.setenv("NOTION_API_KEY", "secret-notion-token")
    monkeypatch.setenv("OPENAI_API_KEY", "secret-openai-token")
    monkeypatch.setenv("SSH_AUTH_SOCK", "/tmp/ssh-agent.sock")

    command = _build_bwrap_codex_command(
        repo_path=repo_path,
        agent_command="agent-cli",
        python_venv_path=None,
    )

    assert ["--ro-bind", "/", "/"] not in _command_windows(command, 3)
    assert _contains_subsequence(command, ["--tmpfs", "/"])
    assert _contains_subsequence(command, ["--bind", str(repo_path), str(repo_path)])
    assert _contains_subsequence(command, ["--bind", str(codex_home_path), str(codex_home_path)])
    assert _contains_subsequence(command, ["--ro-bind", str(agent_path), str(agent_path)])
    assert _contains_subsequence(command, ["--clearenv"])
    assert _contains_subsequence(command, ["--setenv", "HOME", str(WORKER_HOME_PATH)])
    assert _contains_subsequence(command, ["--setenv", "TMPDIR", str(WORKER_TEMP_PATH)])
    assert _contains_subsequence(command, ["--setenv", "CODEX_HOME", str(codex_home_path)])
    assert _contains_subsequence(command, ["--setenv", "XDG_CONFIG_HOME", str(WORKER_HOME_PATH / ".config")])
    assert "--unsetenv" not in command
    assert str(Path.home() / ".notion-task-tracker") not in command
    assert "secret-notion-token" not in command
    assert "secret-openai-token" not in command
    assert str(Path.home() / ".local") not in command[command.index("PATH") + 1]


def test_build_agent_visibility_smoke_test_prompt_checks_sandbox_contract(tmp_path: Path) -> None:
    repo_path = tmp_path / "target repo"
    agent_home_path = tmp_path / "codex home"
    python_venv_path = tmp_path / "tool venv"

    prompt = _build_agent_visibility_smoke_test_prompt(
        repo_path=repo_path,
        agent_home_path=agent_home_path,
        python_venv_path=python_venv_path,
    )

    assert "RALPH_SANDBOX_OK" in prompt
    assert f"test ! -e {shlex.quote(str(Path.home() / '.ralph'))}" in prompt
    assert f"test ! -e {shlex.quote(str(Path.home() / '.notion-task-tracker'))}" in prompt
    assert f"test ! -e {shlex.quote(str(Path.home() / '.aws'))}" in prompt
    assert f"test ! -e {shlex.quote(str(Path.home() / '.claude'))}" in prompt
    assert "test ! -e /workspace/.codex" in prompt
    assert "test ! -e /workspace/.aws" in prompt
    assert "test ! -e /workspace/.claude" in prompt
    assert "test ! -e /workspace/.docker" in prompt
    assert "test ! -e /workspace/.kube" in prompt
    assert 'test -z "${NOTION_API_KEY:-}"' in prompt
    assert 'test -z "${OPENAI_API_KEY:-}"' in prompt
    assert f'test "$HOME" = {shlex.quote(str(WORKER_HOME_PATH))}' in prompt
    assert f'test "$TMPDIR" = {shlex.quote(str(WORKER_TEMP_PATH))}' in prompt
    assert f'test "$CODEX_HOME" = {shlex.quote(str(agent_home_path))}' in prompt
    assert f"mkdir {shlex.quote(str(repo_path / '.ralph-sandbox-write-test-dir'))}" in prompt
    assert f"rmdir {shlex.quote(str(repo_path / '.ralph-sandbox-write-test-dir'))}" in prompt
    assert f"test -d {shlex.quote(str(python_venv_path))}" in prompt
    assert "printf blocked >" in prompt
    assert ".ralph-sandbox-write-test" in prompt
    assert f'test "$VIRTUAL_ENV" = {shlex.quote(str(python_venv_path))}' in prompt


def test_build_agent_visibility_smoke_test_prompt_skips_venv_checks_when_absent(tmp_path: Path) -> None:
    prompt = _build_agent_visibility_smoke_test_prompt(
        repo_path=tmp_path / "target-repo",
        agent_home_path=tmp_path / "codex-home",
        python_venv_path=None,
    )

    assert "VIRTUAL_ENV" not in prompt
    assert "printf blocked" not in prompt


def test_build_agent_visibility_smoke_test_prompt_does_not_reject_explicit_mounts(tmp_path: Path) -> None:
    prompt = _build_agent_visibility_smoke_test_prompt(
        repo_path=tmp_path / "target-repo",
        agent_home_path=Path("/workspace/.codex"),
        python_venv_path=None,
    )

    assert "test ! -e /workspace/.codex" not in prompt
    assert f'test "$CODEX_HOME" = {shlex.quote("/workspace/.codex")}' in prompt


def test_run_agent_visibility_smoke_test_rejects_sensitive_repo_mount(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo_path = tmp_path / "workspace"
    sensitive_state_path = repo_path / ".aws"
    sensitive_state_path.mkdir(parents=True)
    monkeypatch.setattr(
        "ralph.run_ralph_loop._build_sensitive_paths_that_workers_must_not_see",
        lambda: [sensitive_state_path],
    )

    with pytest.raises(ValueError, match="Target repo must not overlap"):
        _run_agent_visibility_smoke_test(
            repo_path=repo_path,
            agent_command="agent-cli",
            python_venv_path=None,
        )


def test_refuse_unsafe_starting_state_rejects_sensitive_repo_mount(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo_path = _initialise_git_repo(tmp_path / "target-repo")
    job = _create_job_with_ledger(tmp_path, _build_example_ledger())
    sensitive_state_path = repo_path / ".aws"
    sensitive_state_path.mkdir()
    monkeypatch.setattr(
        "ralph.run_ralph_loop._build_sensitive_paths_that_workers_must_not_see",
        lambda: [sensitive_state_path],
    )

    with pytest.raises(ValueError, match="Target repo must not overlap"):
        _refuse_unsafe_starting_state(repo_path, job)


def test_require_codex_home_path_rejects_missing_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("CODEX_HOME", raising=False)

    with pytest.raises(RuntimeError, match="CODEX_HOME must be set"):
        _require_codex_home_path()


def test_require_codex_home_path_accepts_exact_codex_home(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    codex_home_path = tmp_path / ".codex"
    codex_home_path.mkdir()
    monkeypatch.setenv("CODEX_HOME", str(codex_home_path))
    monkeypatch.setattr(
        "ralph.run_ralph_loop._build_sensitive_paths_that_workers_must_not_see",
        lambda: [codex_home_path],
    )

    assert _require_codex_home_path() == codex_home_path


def test_require_codex_home_path_rejects_broad_sensitive_parent(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    codex_home_path = tmp_path / "workspace"
    sensitive_state_path = codex_home_path / ".aws"
    sensitive_state_path.mkdir(parents=True)
    monkeypatch.setenv("CODEX_HOME", str(codex_home_path))
    monkeypatch.setattr(
        "ralph.run_ralph_loop._build_sensitive_paths_that_workers_must_not_see",
        lambda: [codex_home_path / ".codex", sensitive_state_path],
    )

    with pytest.raises(ValueError, match="CODEX_HOME must not overlap"):
        _require_codex_home_path()


def test_resolve_python_venv_path_rejects_sensitive_path_overlap(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sensitive_state_path = tmp_path / "sensitive-state"
    python_venv_path = sensitive_state_path / "tool-venv"
    _create_python_venv_shape(python_venv_path)
    monkeypatch.setattr(
        "ralph.run_ralph_loop._build_sensitive_paths_that_workers_must_not_see",
        lambda: [sensitive_state_path],
    )

    with pytest.raises(ValueError, match="Python venv must not overlap"):
        _resolve_python_venv_path(str(python_venv_path))


def test_resolve_python_venv_path_accepts_non_sensitive_helper_venv(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    python_venv_path = tmp_path / "tool-venv"
    _create_python_venv_shape(python_venv_path)
    monkeypatch.setattr(
        "ralph.run_ralph_loop._build_sensitive_paths_that_workers_must_not_see",
        lambda: [tmp_path / "sensitive-state"],
    )

    assert _resolve_python_venv_path(str(python_venv_path)) == python_venv_path


def test_marks_task_done_without_mutating_input() -> None:
    ledger = _build_example_ledger()

    updated_ledger = _mark_task_done(ledger, "R1")

    assert ledger["tasks"][0]["status"] == "pending"
    assert updated_ledger["tasks"][0]["status"] == "done"
    assert "completed_at" in updated_ledger["tasks"][0]


def test_commits_verified_task_before_advancing_ledger(
    tmp_path: Path,
) -> None:
    repo_path = _initialise_git_repo(tmp_path / "target-repo")
    ledger = _build_example_ledger()
    job = _create_job_with_ledger(tmp_path, ledger)
    task_path = tmp_path / "task"
    observed_ledger_at_commit_path = tmp_path / "ledger-at-commit.yaml"
    parser_path = repo_path / "src" / "parser.py"
    parser_path.parent.mkdir()
    parser_path.write_text("def parse_value(value):\n    return value\n")
    _install_pre_commit_hook_that_requires_pending_ledger(
        repo_path=repo_path,
        ledger_path=job.ledger_path,
        observed_ledger_path=observed_ledger_at_commit_path,
    )

    _verify_task_result(
        repo_path=repo_path,
        task=_select_first_task(ledger).task,
        task_path=task_path,
    )
    commit_hash = _commit_verified_task(
        repo_path=repo_path,
        job=job,
        ledger=ledger,
        selection=_select_first_task(ledger),
        task_path=task_path,
    )

    committed_subject = _run_git(repo_path, "log", "--format=%s", "-1").strip()

    assert commit_hash == _run_git(repo_path, "rev-parse", "HEAD").strip()
    assert committed_subject == "Ralph: R1 Add parser"
    assert yaml.safe_load(observed_ledger_at_commit_path.read_text())["tasks"][0]["status"] == "pending"
    assert yaml.safe_load(job.ledger_path.read_text())["tasks"][0]["status"] == "done"
    assert "$ test -f src/parser.py" in task_path.joinpath("verification-output.txt").read_text()
    assert task_path.joinpath("commit.txt").read_text() == commit_hash


def test_commit_verified_task_keeps_ledger_pending_when_commit_fails(
    tmp_path: Path,
) -> None:
    repo_path = _initialise_git_repo(tmp_path / "target-repo")
    ledger = _build_example_ledger()
    job = _create_job_with_ledger(tmp_path, ledger)
    task_path = tmp_path / "task"
    parser_path = repo_path / "src" / "parser.py"
    parser_path.parent.mkdir()
    parser_path.write_text("def parse_value(value):\n    return value\n")
    _install_failing_pre_commit_hook(repo_path)

    with pytest.raises(RuntimeError, match="pre-commit refused commit"):
        _verify_task_result(
            repo_path=repo_path,
            task=_select_first_task(ledger).task,
            task_path=task_path,
        )
        _commit_verified_task(
            repo_path=repo_path,
            job=job,
            ledger=ledger,
            selection=_select_first_task(ledger),
            task_path=task_path,
        )

    assert yaml.safe_load(job.ledger_path.read_text())["tasks"][0]["status"] == "pending"
    assert "$ test -f src/parser.py" in task_path.joinpath("verification-output.txt").read_text()
    assert not task_path.joinpath("commit.txt").exists()


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


def _command_windows(command: list[str], size: int) -> list[list[str]]:
    return [
        command[index:index + size]
        for index in range(len(command) - size + 1)
    ]


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


def _create_python_venv_shape(python_venv_path: Path) -> None:
    python_path = python_venv_path / "bin" / "python"
    python_path.parent.mkdir(parents=True)
    python_path.write_text("")


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
