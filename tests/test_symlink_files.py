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
        ("CLAUDE_CONFIG_DIR", "CODEX_HOME", "Claude", "Codex", "--claude-home"),
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
    environment = os.environ.copy()
    environment.pop(missing_environment_variable, None)
    environment[configured_environment_variable] = str(tmp_path / "configured-agent-home")

    completed_process = subprocess.run(
        [sys.executable, "symlink-files.py", "--dry-run"],
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
    assert f"{configured_agent_name}: would link" in completed_process.stdout
    assert f"{missing_agent_name}:" not in completed_process.stdout
