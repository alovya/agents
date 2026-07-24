from __future__ import annotations

from pathlib import Path

import pytest

from ralph.agent_backends import AgentBackend
from ralph.codex_backend import (
    CODEX_WORKER_HOME_SEED_FILENAMES,
    build_direct_codex_command,
    codex_permission_setup,
    codex_rules_path,
    generate_codex_execpolicy_rules,
    parse_command_to_execpolicy_pattern,
    prepare_codex_worker_home,
    require_codex_home_path,
    write_codex_rules_atomically,
)


def test_build_direct_codex_command_keeps_git_writable_for_worker_commits(
    tmp_path: Path,
) -> None:
    codex_home_path = tmp_path / "codex-home"
    repo_path = tmp_path / "repo"
    agent_backend = AgentBackend(
        backend_name="codex",
        command_name="/usr/bin/codex",
        agent_config_dir=codex_home_path,
        agent_home_environment_variable="CODEX_HOME",
    )

    assert build_direct_codex_command(agent_backend=agent_backend, repo_path=repo_path) == [
        "/usr/bin/codex",
        "--ask-for-approval",
        "never",
        "exec",
        "-C",
        str(repo_path),
        "--sandbox",
        "danger-full-access",
        "--ephemeral",
        "-",
    ]


def test_require_codex_home_path_rejects_missing_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("CODEX_HOME", raising=False)

    with pytest.raises(RuntimeError, match="CODEX_HOME must be set"):
        require_codex_home_path()


def test_require_codex_home_path_accepts_exact_codex_home(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    codex_home_path = tmp_path / ".codex"
    codex_home_path.mkdir()
    monkeypatch.setenv("CODEX_HOME", str(codex_home_path))
    monkeypatch.setattr(
        "ralph.sandbox.build_sensitive_paths_that_workers_must_not_see",
        lambda: [codex_home_path],
    )

    assert require_codex_home_path() == codex_home_path


def test_require_codex_home_path_accepts_symlink_to_exact_codex_home(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    codex_home_path = tmp_path / ".codex"
    codex_home_link_path = tmp_path / "codex-link"
    codex_home_path.mkdir()
    codex_home_link_path.symlink_to(codex_home_path)
    monkeypatch.setenv("CODEX_HOME", str(codex_home_link_path))
    monkeypatch.setattr(
        "ralph.sandbox.build_sensitive_paths_that_workers_must_not_see",
        lambda: [codex_home_path],
    )

    assert require_codex_home_path() == codex_home_path


def test_require_codex_home_path_rejects_broad_sensitive_parent(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    codex_home_path = tmp_path / "workspace"
    sensitive_state_path = codex_home_path / ".aws"
    sensitive_state_path.mkdir(parents=True)
    monkeypatch.setenv("CODEX_HOME", str(codex_home_path))
    monkeypatch.setattr(
        "ralph.sandbox.build_sensitive_paths_that_workers_must_not_see",
        lambda: [codex_home_path / ".codex", sensitive_state_path],
    )

    with pytest.raises(ValueError, match="CODEX_HOME must not overlap"):
        require_codex_home_path()


def test_prepare_codex_worker_home_seeds_only_worker_required_files(tmp_path: Path) -> None:
    master_codex_home_path = tmp_path / "master-codex-home"
    external_skill_path = tmp_path / "external-ralph-skill"
    master_releases_path = master_codex_home_path / "packages" / "standalone" / "releases"
    master_current_release_path = master_releases_path / "codex-v1"
    master_codex_home_path.mkdir()
    external_skill_path.mkdir()
    master_current_release_path.mkdir(parents=True)
    _write_codex_seed_files(master_codex_home_path)
    (master_codex_home_path / "plugins").mkdir()
    (master_codex_home_path / "cache").mkdir()
    (master_codex_home_path / "skills").mkdir()
    (master_codex_home_path / "skills" / "ralph").symlink_to(external_skill_path)
    (external_skill_path / "SKILL.md").write_text("Ralph skill", encoding="utf-8")
    (master_codex_home_path / "packages" / "standalone" / "current").symlink_to(
        master_current_release_path
    )
    (master_codex_home_path / "packages" / "standalone" / "install.lock").write_text(
        "locked",
        encoding="utf-8",
    )
    master_agent_backend = AgentBackend(
        backend_name="codex",
        command_name="codex",
        agent_config_dir=master_codex_home_path,
        agent_home_environment_variable="CODEX_HOME",
    )

    with prepare_codex_worker_home(master_agent_backend) as worker_agent_backend:
        worker_codex_home_path = worker_agent_backend.agent_config_dir
        worker_skill_path = worker_codex_home_path / "skills" / "ralph"
        worker_current_path = worker_codex_home_path / "packages" / "standalone" / "current"
        worker_releases_path = worker_codex_home_path / "packages" / "standalone" / "releases"

        assert worker_agent_backend.backend_name == "codex"
        assert worker_agent_backend.command_name == "codex"
        assert worker_agent_backend.agent_home_environment_variable == "CODEX_HOME"
        assert worker_codex_home_path != master_codex_home_path
        assert _read_codex_seed_files(worker_codex_home_path) == _read_codex_seed_files(
            master_codex_home_path
        )
        assert worker_skill_path.is_dir()
        assert not worker_skill_path.is_symlink()
        assert (worker_skill_path / "SKILL.md").read_text(encoding="utf-8") == "Ralph skill"
        assert (worker_codex_home_path / "rules").is_dir()
        assert (worker_codex_home_path / ".tmp").is_dir()
        assert not (worker_codex_home_path / "plugins").exists()
        assert not (worker_codex_home_path / "cache").exists()
        worker_install_lock_path = worker_codex_home_path / "packages" / "standalone" / "install.lock"
        assert worker_install_lock_path.read_text(encoding="utf-8") == "locked"
        assert worker_current_path.is_symlink()
        assert worker_current_path.resolve() == worker_releases_path / "codex-v1"
        assert worker_current_path.resolve().is_relative_to(worker_codex_home_path)
        assert worker_agent_backend.read_only_home_mounts[0].host_path == master_releases_path
        assert worker_agent_backend.read_only_home_mounts[0].worker_path == worker_releases_path

    assert not worker_codex_home_path.exists()


def test_codex_permission_setup_writes_rules_inside_prepared_worker_home(tmp_path: Path) -> None:
    master_codex_home_path = tmp_path / "master-codex-home"
    task_path = tmp_path / "task"
    master_codex_home_path.mkdir()
    task_path.mkdir()
    master_agent_backend = AgentBackend(
        backend_name="codex",
        command_name="codex",
        agent_config_dir=master_codex_home_path,
        agent_home_environment_variable="CODEX_HOME",
    )

    with prepare_codex_worker_home(master_agent_backend) as worker_agent_backend:
        master_rules_path = codex_rules_path(master_codex_home_path)
        worker_rules_path = codex_rules_path(worker_agent_backend.agent_config_dir)

        with codex_permission_setup(
            agent_backend=worker_agent_backend,
            allowed_bash_commands=["rg *"],
            task_path=task_path,
        ):
            assert (
                worker_rules_path.read_text(encoding="utf-8")
                == "prefix_rule(pattern=['rg'], decision=\"allow\")\n"
            )
            assert not master_rules_path.exists()

        assert not worker_rules_path.exists()
        assert not master_rules_path.exists()


def test_generate_codex_execpolicy_rules_renders_prefix_rule_syntax() -> None:
    allowed_bash_commands = ["rg pattern", "sed -n 1p"]

    rules = generate_codex_execpolicy_rules(allowed_bash_commands)

    assert rules == (
        "prefix_rule(pattern=['rg', 'pattern'], decision=\"allow\")\n"
        "prefix_rule(pattern=['sed', '-n', '1p'], decision=\"allow\")\n"
    )


def test_parse_command_to_execpolicy_pattern_strips_final_wildcard() -> None:
    assert parse_command_to_execpolicy_pattern("rg *") == ["rg"]
    assert parse_command_to_execpolicy_pattern("sed -n *") == ["sed", "-n"]
    assert parse_command_to_execpolicy_pattern("git commit --no-verify -m *") == [
        "git", "commit", "--no-verify", "-m"
    ]


def test_parse_command_to_execpolicy_pattern_preserves_literal_arguments() -> None:
    assert parse_command_to_execpolicy_pattern("python -m pytest tests/test_run.py") == [
        "python", "-m", "pytest", "tests/test_run.py"
    ]


def test_parse_command_to_execpolicy_pattern_rejects_non_final_wildcard() -> None:
    with pytest.raises(ValueError, match="only allowed as the final token"):
        parse_command_to_execpolicy_pattern("git * commit")


def test_parse_command_to_execpolicy_pattern_rejects_command_only_wildcard() -> None:
    with pytest.raises(ValueError, match="cannot be only a wildcard"):
        parse_command_to_execpolicy_pattern("*")


def test_write_codex_rules_atomically_creates_rules_directory(tmp_path: Path) -> None:
    rules_path = tmp_path / "rules" / "default.rules"

    write_codex_rules_atomically(rules_path, "prefix_rule(pattern=['rg'], decision=\"allow\")\n")

    assert rules_path.is_file()
    assert rules_path.read_text() == "prefix_rule(pattern=['rg'], decision=\"allow\")\n"


def test_write_codex_rules_atomically_replaces_existing_rules(tmp_path: Path) -> None:
    rules_path = tmp_path / "rules" / "default.rules"
    rules_path.parent.mkdir(parents=True)
    rules_path.write_text("old rules content")

    write_codex_rules_atomically(rules_path, "new rules content")

    assert rules_path.read_text() == "new rules content"


def test_write_codex_rules_atomically_leaves_no_temp_file_after_success(tmp_path: Path) -> None:
    rules_path = tmp_path / "rules" / "default.rules"

    write_codex_rules_atomically(rules_path, "content")

    temp_path = rules_path.with_suffix(".rules.tmp")
    assert not temp_path.exists()


def test_codex_permission_setup_writes_temporary_rules_then_removes_them(
    tmp_path: Path,
) -> None:
    codex_home_path = tmp_path / "codex-home"
    task_path = tmp_path / "task"
    rules_path = codex_rules_path(codex_home_path)
    codex_home_path.mkdir()
    task_path.mkdir()
    rules_path.parent.mkdir(parents=True)
    observed_rules_inside_context: list[str] = []
    observed_task_files_inside_context: list[list[str]] = []

    agent_backend = AgentBackend(
        backend_name="codex",
        command_name="codex",
        agent_config_dir=codex_home_path,
        agent_home_environment_variable="CODEX_HOME",
    )

    with codex_permission_setup(
        agent_backend=agent_backend,
        allowed_bash_commands=["rg *"],
        task_path=task_path,
    ):
        observed_rules_inside_context.append(rules_path.read_text(encoding="utf-8"))
        observed_task_files_inside_context.append(
            sorted(path.name for path in task_path.iterdir())
        )

    assert observed_task_files_inside_context == [[]]
    assert observed_rules_inside_context == ["prefix_rule(pattern=['rg'], decision=\"allow\")\n"]
    assert not rules_path.exists()
    assert list(task_path.iterdir()) == []


def _write_codex_seed_files(codex_home_path: Path) -> None:
    for seed_filename in CODEX_WORKER_HOME_SEED_FILENAMES:
        (codex_home_path / seed_filename).write_text(f"{seed_filename} content", encoding="utf-8")


def _read_codex_seed_files(codex_home_path: Path) -> dict[str, str]:
    return {
        seed_filename: (codex_home_path / seed_filename).read_text(encoding="utf-8")
        for seed_filename in CODEX_WORKER_HOME_SEED_FILENAMES
    }
