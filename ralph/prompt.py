from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from ralph.plan_selection import TaskSelection


def render_agent_prompt(
    repo_path: Path,
    ledger: dict[str, Any],
    selection: TaskSelection,
    python_venv_path: Path | None,
) -> str:
    prompt_template_path = Path(__file__).resolve().parent / "PROMPT.md"
    prompt_template = prompt_template_path.read_text()
    visible_ledger = _remove_duplicated_task_prose_before_rendering_prompt(ledger)
    active_task = _remove_duplicated_task_prose_before_rendering_prompt(selection.task)

    return prompt_template.format(
        repo_path=repo_path,
        tool_environment_context=describe_python_venv_for_worker_prompt(python_venv_path),
        active_task_yaml=_dump_yaml(active_task),
        visible_ledger_yaml=_dump_yaml(visible_ledger),
        shared_plan_context=selection.shared_plan_context.strip(),
        active_task_plan_context=selection.active_task_plan_context.strip(),
    )


def describe_python_venv_for_worker_prompt(python_venv_path: Path | None) -> str:
    if python_venv_path is None:
        return "No Python venv was configured for helper tools. Use only tools already available on PATH."

    return "\n".join(
        [
            f"Python venv: {python_venv_path}",
            f"`{python_venv_path / 'bin'}` is already first on PATH.",
            f"`VIRTUAL_ENV` is already set to `{python_venv_path}`.",
            f"`BASH_ENV` points at `{python_venv_path / 'bin' / 'activate'}` so shell tool calls keep the venv active.",
            "Use commands installed in this venv only when the active task requires them.",
        ]
    )


def _remove_duplicated_task_prose_before_rendering_prompt(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: _remove_duplicated_task_prose_before_rendering_prompt(child_value)
            for key, child_value in value.items()
            if key not in {"plan", "context", "notes", "description", "implementation"}
        }
    if isinstance(value, list):
        return [_remove_duplicated_task_prose_before_rendering_prompt(item) for item in value]
    return value


def _dump_yaml(value: Any) -> str:
    return yaml.safe_dump(value, sort_keys=False)
