import os
import subprocess
import sys
from pathlib import Path

import pytest


@pytest.mark.parametrize(
    (
        "missing_environment_variable",
        "missing_agent_name",
        "missing_option_name",
    ),
        [
            ("CODEX_HOME", "Codex", "--codex-home"),
            ("CLAUDE_CONFIG_DIR", "Claude", "--claude-config-dir"),
            ("CURSOR_HOME", "Cursor", "--cursor-home"),
            ("PI_CODING_AGENT_DIR", "Pi", "--pi-coding-agent-dir"),
        ],
)
def test_main_warns_and_skips_an_agent_when_its_home_is_missing(
    tmp_path: Path,
    missing_environment_variable: str,
    missing_agent_name: str,
    missing_option_name: str,
) -> None:
    agents_repo_dir = Path(__file__).resolve().parents[1]
    environment = os.environ.copy()
    for home_environment_variable in ("CODEX_HOME", "CLAUDE_CONFIG_DIR", "CURSOR_HOME", "PI_CODING_AGENT_DIR"):
        environment[home_environment_variable] = str(tmp_path / home_environment_variable.lower())
    environment.pop(missing_environment_variable, None)

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


@pytest.mark.parametrize(
    (
        "only_option_name",
        "home_option_name",
        "instructions_filename",
    ),
        [
            ("--codex-only", "--codex-home", "AGENTS.md"),
            ("--claude-only", "--claude-config-dir", "CLAUDE.md"),
            ("--cursor-only", "--cursor-home", None),
            ("--pi-only", "--pi-coding-agent-dir", "AGENTS.md"),
        ],
)
def test_main_links_skills_and_instructions_into_the_configured_home(
    tmp_path: Path,
    only_option_name: str,
    home_option_name: str,
    instructions_filename: str | None,
) -> None:
    agents_repo_dir = tmp_path / "configured-agents"
    skill_dir = agents_repo_dir / "skills" / "demo"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text("---\nname: demo\n---\n", encoding="utf-8")
    (agents_repo_dir / "AGENTS.md").write_text("agent instructions\n", encoding="utf-8")

    agent_home_dir = tmp_path / "agent-home"

    completed_process = subprocess.run(
        [
            sys.executable,
            "install_personal_agent_instructions.py",
            "--dry-run",
            only_option_name,
            home_option_name,
            str(agent_home_dir),
            "--agents-repo-dir",
            str(agents_repo_dir),
        ],
        cwd=Path(__file__).resolve().parents[1],
        env=os.environ.copy(),
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed_process.returncode == 0
    assert f"would link {agent_home_dir / 'skills' / 'demo'} -> {skill_dir}" in completed_process.stdout

    if instructions_filename is None:
        assert f"-> {agents_repo_dir / 'AGENTS.md'}" not in completed_process.stdout
    else:
        assert (
            f"would link {agent_home_dir / instructions_filename} -> {agents_repo_dir / 'AGENTS.md'}"
            in completed_process.stdout
        )
