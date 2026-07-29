import os
import subprocess
import sys
from pathlib import Path

import pytest


@pytest.mark.parametrize(
    (
        "missing_environment_variable",
        "configured_environment_variable",
        "missing_agent_name",
        "configured_agent_name",
        "missing_option_name",
    ),
        [
            ("CODEX_HOME", "CLAUDE_CONFIG_DIR", "Codex", "Claude", "--codex-home"),
            ("CLAUDE_CONFIG_DIR", "CODEX_HOME", "Claude", "Codex", "--claude-config-dir"),
        ],
)
def test_main_warns_and_skips_an_agent_when_its_home_is_missing(
    tmp_path: Path,
    missing_environment_variable: str,
    configured_environment_variable: str,
    missing_agent_name: str,
    configured_agent_name: str,
    missing_option_name: str,
) -> None:
    agents_repo_dir = Path(__file__).resolve().parents[1]
    environment = os.environ.copy()
    environment.pop(missing_environment_variable, None)
    environment[configured_environment_variable] = str(tmp_path / "configured-agent-home")

    completed_process = subprocess.run(
        [
            sys.executable,
            "install_personal_agent_instructions.py",
            "--dry-run",
            "--agents-repo-dir",
            str(agents_repo_dir),
        ],
        cwd=Path(__file__).resolve().parents[1],
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed_process.returncode == 0
    assert completed_process.stderr == (
        f"Warning: skipping {missing_agent_name} because {missing_environment_variable} is unset "
        f"and {missing_option_name} was not provided.\n"
    )
    assert f"would replace" in completed_process.stdout or f"would link" in completed_process.stdout
    assert f"{missing_agent_name}:" not in completed_process.stdout


def test_main_uses_configured_agents_repo_dir(tmp_path: Path) -> None:
    agents_repo_dir = tmp_path / "configured-agents"
    skill_dir = agents_repo_dir / "skills" / "demo"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text("---\nname: demo\n---\n", encoding="utf-8")
    (agents_repo_dir / "AGENTS.md").write_text("agent instructions\n", encoding="utf-8")

    environment = os.environ.copy()
    environment["CODEX_HOME"] = str(tmp_path / "codex-home")

    completed_process = subprocess.run(
        [
            sys.executable,
            "install_personal_agent_instructions.py",
            "--dry-run",
            "--codex-only",
            "--agents-repo-dir",
            str(agents_repo_dir),
        ],
        cwd=Path(__file__).resolve().parents[1],
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed_process.returncode == 0
    assert f"would link {tmp_path / 'codex-home' / 'skills' / 'demo'} -> {skill_dir}" in completed_process.stdout
    assert f"-> {agents_repo_dir / 'AGENTS.md'}" in completed_process.stdout
