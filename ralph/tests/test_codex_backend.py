from __future__ import annotations

from pathlib import Path

import pytest

from ralph.agent_backends import AgentBackend
from ralph.codex_backend import (
    CODEX_RULES_BACKUP_FILENAME,
    CODEX_WORKER_HOME_SEED_FILENAMES,
    CodexRulesSnapshot,
    codex_permission_setup,
    codex_rules_path,
    find_interrupted_codex_rules_backup,
    generate_codex_execpolicy_rules,
    parse_command_to_execpolicy_pattern,
    prepare_codex_worker_home,
    read_codex_rules_backup,
    recover_interrupted_codex_rules,
    require_codex_home_path,
    restore_codex_rules,
    snapshot_codex_rules,
    write_codex_rules_atomically,
    write_codex_rules_backup,
)
from ralph.tests.conftest import build_example_ledger, create_job_with_ledger


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
    source_codex_home_path = tmp_path / "source-codex-home"
    external_skill_path = tmp_path / "external-ralph-skill"
    source_releases_path = source_codex_home_path / "packages" / "standalone" / "releases"
    source_current_release_path = source_releases_path / "codex-v1"
    source_codex_home_path.mkdir()
    external_skill_path.mkdir()
    source_current_release_path.mkdir(parents=True)
    _write_codex_seed_files(source_codex_home_path)
    (source_codex_home_path / "plugins").mkdir()
    (source_codex_home_path / "cache").mkdir()
    (source_codex_home_path / "skills").mkdir()
    (source_codex_home_path / "skills" / "ralph").symlink_to(external_skill_path)
    (external_skill_path / "SKILL.md").write_text("Ralph skill", encoding="utf-8")
    (source_codex_home_path / "packages" / "standalone" / "current").symlink_to(
        source_current_release_path
    )
    (source_codex_home_path / "packages" / "standalone" / "install.lock").write_text(
        "locked",
        encoding="utf-8",
    )
    source_backend_config = AgentBackend(
        backend_name="codex",
        command_name="codex",
        agent_state_dir=source_codex_home_path,
        agent_home_environment_variable="CODEX_HOME",
    )

    with prepare_codex_worker_home(source_backend_config) as worker_backend_config:
        worker_codex_home_path = worker_backend_config.agent_state_dir
        worker_skill_path = worker_codex_home_path / "skills" / "ralph"
        worker_current_path = worker_codex_home_path / "packages" / "standalone" / "current"
        worker_releases_path = worker_codex_home_path / "packages" / "standalone" / "releases"

        assert worker_backend_config.backend_name == "codex"
        assert worker_backend_config.command_name == "codex"
        assert worker_backend_config.agent_home_environment_variable == "CODEX_HOME"
        assert worker_codex_home_path != source_codex_home_path
        assert _read_codex_seed_files(worker_codex_home_path) == _read_codex_seed_files(
            source_codex_home_path
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
        assert worker_backend_config.read_only_home_mounts[0].host_path == source_releases_path
        assert worker_backend_config.read_only_home_mounts[0].worker_path == worker_releases_path

    assert not worker_codex_home_path.exists()


def test_codex_permission_setup_writes_rules_inside_prepared_worker_home(tmp_path: Path) -> None:
    source_codex_home_path = tmp_path / "source-codex-home"
    task_path = tmp_path / "task"
    source_codex_home_path.mkdir()
    task_path.mkdir()
    source_backend_config = AgentBackend(
        backend_name="codex",
        command_name="codex",
        agent_state_dir=source_codex_home_path,
        agent_home_environment_variable="CODEX_HOME",
    )

    with prepare_codex_worker_home(source_backend_config) as worker_backend_config:
        source_rules_path = codex_rules_path(source_codex_home_path)
        worker_rules_path = codex_rules_path(worker_backend_config.agent_state_dir)

        with codex_permission_setup(
            backend_config=worker_backend_config,
            allowed_bash_commands=["rg *"],
            task_path=task_path,
        ):
            assert (
                worker_rules_path.read_text(encoding="utf-8")
                == "prefix_rule(pattern=['rg'], decision=\"allow\")\n"
            )
            assert not source_rules_path.exists()

        assert not worker_rules_path.exists()
        assert not source_rules_path.exists()


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


def test_snapshot_codex_rules_captures_existing_content(tmp_path: Path) -> None:
    rules_path = tmp_path / "rules" / "default.rules"
    rules_path.parent.mkdir(parents=True)
    rules_path.write_text("original rules")

    snapshot = snapshot_codex_rules(rules_path)

    assert snapshot.existed is True
    assert snapshot.content == "original rules"


def test_snapshot_codex_rules_records_absence(tmp_path: Path) -> None:
    rules_path = tmp_path / "rules" / "default.rules"

    snapshot = snapshot_codex_rules(rules_path)

    assert snapshot.existed is False
    assert snapshot.content is None


def test_restore_codex_rules_recreates_original_content(tmp_path: Path) -> None:
    rules_path = tmp_path / "rules" / "default.rules"
    rules_path.parent.mkdir(parents=True)
    rules_path.write_text("modified rules")

    restore_codex_rules(rules_path, CodexRulesSnapshot(existed=True, content="original rules"))

    assert rules_path.read_text() == "original rules"


def test_restore_codex_rules_removes_rules_when_originally_absent(tmp_path: Path) -> None:
    rules_path = tmp_path / "rules" / "default.rules"
    rules_path.parent.mkdir(parents=True)
    rules_path.write_text("generated rules")

    restore_codex_rules(rules_path, CodexRulesSnapshot(existed=False, content=None))

    assert not rules_path.exists()


def test_write_and_read_codex_rules_backup(tmp_path: Path) -> None:
    marker_path = tmp_path / "task" / CODEX_RULES_BACKUP_FILENAME
    original_snapshot = CodexRulesSnapshot(existed=True, content="original rules")

    write_codex_rules_backup(marker_path, original_snapshot)
    recovered_snapshot = read_codex_rules_backup(marker_path)

    assert recovered_snapshot.existed is True
    assert recovered_snapshot.content == "original rules"


def test_codex_rules_backup_location_under_ralph_task_directory(tmp_path: Path) -> None:
    task_path = tmp_path / "tasks" / "R1_20260621T120000Z"
    task_path.mkdir(parents=True)
    marker_path = task_path / CODEX_RULES_BACKUP_FILENAME

    write_codex_rules_backup(marker_path, CodexRulesSnapshot(existed=False, content=None))

    assert marker_path.is_file()
    assert marker_path.parent == task_path


def test_find_interrupted_codex_rules_backup_returns_backup_path(tmp_path: Path) -> None:
    job = create_job_with_ledger(tmp_path, build_example_ledger())
    task_path = job.tasks_path / "R1_20260621T120000Z"
    task_path.mkdir(parents=True)
    marker_path = task_path / CODEX_RULES_BACKUP_FILENAME
    marker_path.write_text('{"existed": true, "content": "original"}')

    found_marker = find_interrupted_codex_rules_backup(job)

    assert found_marker == marker_path


def test_find_interrupted_codex_rules_backup_returns_none_when_absent(tmp_path: Path) -> None:
    job = create_job_with_ledger(tmp_path, build_example_ledger())
    job.tasks_path.mkdir(parents=True, exist_ok=True)

    found_marker = find_interrupted_codex_rules_backup(job)

    assert found_marker is None


def test_recover_interrupted_codex_rules_restores_and_raises(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    codex_home_path = tmp_path / "codex-home"
    codex_home_path.mkdir()
    rules_path = codex_rules_path(codex_home_path)
    rules_path.parent.mkdir(parents=True)
    rules_path.write_text("generated rules")

    job = create_job_with_ledger(tmp_path, build_example_ledger())
    task_path = job.tasks_path / "R1_20260621T120000Z"
    task_path.mkdir(parents=True)
    marker_path = task_path / CODEX_RULES_BACKUP_FILENAME
    marker_path.write_text('{"existed": true, "content": "original rules"}')

    monkeypatch.setenv("CODEX_HOME", str(codex_home_path))

    with pytest.raises(RuntimeError, match="Recovered Codex rules left by interrupted worker"):
        recover_interrupted_codex_rules(job)

    assert rules_path.read_text() == "original rules"
    assert not marker_path.exists()


def test_recover_interrupted_codex_rules_removes_rules_when_originally_absent(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    codex_home_path = tmp_path / "codex-home"
    codex_home_path.mkdir()
    rules_path = codex_rules_path(codex_home_path)
    rules_path.parent.mkdir(parents=True)
    rules_path.write_text("generated rules")

    job = create_job_with_ledger(tmp_path, build_example_ledger())
    task_path = job.tasks_path / "R1_20260621T120000Z"
    task_path.mkdir(parents=True)
    marker_path = task_path / CODEX_RULES_BACKUP_FILENAME
    marker_path.write_text('{"existed": false, "content": null}')

    monkeypatch.setenv("CODEX_HOME", str(codex_home_path))

    with pytest.raises(RuntimeError, match="Recovered Codex rules left by interrupted worker"):
        recover_interrupted_codex_rules(job)

    assert not rules_path.exists()
    assert not marker_path.exists()


def test_codex_permission_setup_writes_temporary_rules_then_restores_original_rules(
    tmp_path: Path,
) -> None:
    codex_home_path = tmp_path / "codex-home"
    task_path = tmp_path / "task"
    rules_path = codex_rules_path(codex_home_path)
    codex_home_path.mkdir()
    task_path.mkdir()
    rules_path.parent.mkdir(parents=True)
    rules_path.write_text("original rules", encoding="utf-8")
    observed_rules_inside_context: list[str] = []
    observed_backup_inside_context: list[bool] = []

    backend_config = AgentBackend(
        backend_name="codex",
        command_name="codex",
        agent_state_dir=codex_home_path,
        agent_home_environment_variable="CODEX_HOME",
    )

    with codex_permission_setup(
        backend_config=backend_config,
        allowed_bash_commands=["rg *"],
        task_path=task_path,
    ):
        observed_rules_inside_context.append(rules_path.read_text(encoding="utf-8"))
        observed_backup_inside_context.append(
            (task_path / CODEX_RULES_BACKUP_FILENAME).is_file()
        )

    assert observed_backup_inside_context == [True]
    assert observed_rules_inside_context == ["prefix_rule(pattern=['rg'], decision=\"allow\")\n"]
    assert rules_path.read_text(encoding="utf-8") == "original rules"
    assert not (task_path / CODEX_RULES_BACKUP_FILENAME).exists()


def _write_codex_seed_files(codex_home_path: Path) -> None:
    for seed_filename in CODEX_WORKER_HOME_SEED_FILENAMES:
        (codex_home_path / seed_filename).write_text(f"{seed_filename} content", encoding="utf-8")


def _read_codex_seed_files(codex_home_path: Path) -> dict[str, str]:
    return {
        seed_filename: (codex_home_path / seed_filename).read_text(encoding="utf-8")
        for seed_filename in CODEX_WORKER_HOME_SEED_FILENAMES
    }
