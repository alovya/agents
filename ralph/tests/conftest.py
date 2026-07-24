from __future__ import annotations

import shlex
import subprocess
from pathlib import Path
from typing import Any

import pytest

from ralph.agent_backends import AgentBackend
from ralph.plan_selection import TaskSelection
from ralph.run_ralph_loop import RalphJob, _write_yaml_file


def build_example_ledger() -> dict[str, Any]:
    return {
        "version": 1,
        "job_name": "example",
        "ntt_ticket_prefix": "ALOVYA",
        "ntt_parent_task_id": "ALOVYA-89",
        "tasks": [
            {
                "ralph_task_id": "R1",
                "title": "Add parser",
                "status": "pending",
                "depends_on": [],
                "ntt_task_id": "ALOVYA-90",
            },
            {
                "ralph_task_id": "R2",
                "title": "Add command line entrypoint",
                "status": "pending",
                "depends_on": ["R1"],
                "ntt_task_id": "ALOVYA-91",
            },
        ],
    }


def build_ledger_where_first_pending_task_waits_and_second_pending_task_is_ready() -> dict[str, Any]:
    return {
        "version": 1,
        "job_name": "example",
        "ntt_ticket_prefix": "ALOVYA",
        "ntt_parent_task_id": "ALOVYA-89",
        "tasks": [
            {
                "ralph_task_id": "R0",
                "title": "Prepare dependency",
                "status": "blocked",
                "depends_on": [],
                "ntt_task_id": "ALOVYA-90",
            },
            {
                "ralph_task_id": "R1",
                "title": "Wait for dependency",
                "status": "pending",
                "depends_on": ["R0"],
                "ntt_task_id": "ALOVYA-91",
            },
            {
                "ralph_task_id": "R2",
                "title": "First ready task",
                "status": "pending",
                "depends_on": [],
                "ntt_task_id": "ALOVYA-92",
            },
            {
                "ralph_task_id": "R3",
                "title": "Second ready task",
                "status": "pending",
                "depends_on": [],
                "ntt_task_id": "ALOVYA-93",
            },
        ],
    }


def build_example_plan() -> str:
    return """
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


def build_three_task_plan() -> str:
    return """
<!-- ralph-shared:start -->
Shared context.
<!-- ralph-shared:end -->

<!-- ralph-task:start R0 -->
Dependency task context.
<!-- ralph-task:end R0 -->

<!-- ralph-task:start R1 -->
Waiting task context.
<!-- ralph-task:end R1 -->

<!-- ralph-task:start R2 -->
Second task context.
<!-- ralph-task:end R2 -->

<!-- ralph-task:start R3 -->
Third task context.
<!-- ralph-task:end R3 -->
"""


def contains_subsequence(command: list[str], expected: list[str]) -> bool:
    return any(
        command[index:index + len(expected)] == expected
        for index in range(len(command) - len(expected) + 1)
    )


def build_test_agent_backend(
    backend_name: str,
    agent_config_dir: Path,
    agent_home_environment_variable: str,
) -> AgentBackend:
    return AgentBackend(
        backend_name=backend_name,
        command_name=f"{backend_name}-cli",
        agent_config_dir=agent_config_dir,
        agent_home_environment_variable=agent_home_environment_variable,
    )


def command_windows(command: list[str], size: int) -> list[list[str]]:
    return [
        command[index:index + size]
        for index in range(len(command) - size + 1)
    ]


def select_first_task(ledger: dict[str, Any]) -> TaskSelection:
    return TaskSelection(
        task=ledger["tasks"][0],
        ntt_ticket_prefix=ledger["ntt_ticket_prefix"],
        shared_plan_context="Shared context.",
        active_task_plan_context="First task context.",
    )


def create_job_with_ledger(tmp_path: Path, ledger: dict[str, Any]) -> RalphJob:
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


def initialise_git_repo(repo_path: Path) -> Path:
    repo_path.mkdir()
    run_git(repo_path, "init")
    run_git(repo_path, "config", "user.email", "ralph-test@example.com")
    run_git(repo_path, "config", "user.name", "Ralph Test")
    readme_path = repo_path / "README.md"
    readme_path.write_text("Ralph test repository\n")
    run_git(repo_path, "add", ".")
    run_git(repo_path, "commit", "-m", "Initial commit")
    return repo_path


def create_python_venv_shape(python_venv_path: Path) -> None:
    python_path = python_venv_path / "bin" / "python"
    python_path.parent.mkdir(parents=True)
    python_path.write_text("")


def write_executable_shim(shim_path: Path) -> None:
    shim_path.write_text("#!/bin/sh\nexit 0\n")
    shim_path.chmod(0o755)


def run_git(repo_path: Path, *arguments: str) -> str:
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


def quote_shell_path(path: Path) -> str:
    return shlex.quote(str(path))
