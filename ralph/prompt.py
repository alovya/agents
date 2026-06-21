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
        notion_log_instructions=_build_notion_log_instructions(selection.task),
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


WORKER_NOTION_WORKLOG_FILENAME = ".ralph-worklog.json"


def _build_notion_log_instructions(task: dict[str, Any]) -> str:
    notion_task = task.get("notion_task")
    if not isinstance(notion_task, dict):
        return _build_notion_log_instructions_not_applicable()

    materialised_task_id = notion_task.get("materialized_task_id")
    if not materialised_task_id:
        return _build_notion_log_instructions_not_applicable()

    from ralph.notion import build_worker_notion_log_command
    command = build_worker_notion_log_command(materialised_task_id)
    return "\n".join([
        "Notion worklog (required before verification):",
        f"- Write `{WORKER_NOTION_WORKLOG_FILENAME}` as a valid ntt content JSON object with the following shape:",
        '  ```json',
        '  {',
        '    "subheading": "Short log title",',
        '    "blocks": [',
        '      {"type": "paragraph", "text": "Human-readable summary"},',
        '      {"type": "code", "language": "text", "text": "command output or details"}',
        '    ]',
        '  }',
        '  ```',
        "- Include blocks for: commands run (with key outputs or errors), files changed and why, decisions made, unresolved risks (if any), and the Notion log command result.",
        f"- Run the Notion log command exactly as: `{command}`",
        "- Do not use shell redirection when running the ntt command.",
        "- Do not put this JSON in the final answer for the controller to parse.",
        "- If the log command fails or the content file is malformed, rewrite the file and rerun before returning.",
        "- For BLOCKED or ABORT, log the blocker or abort reason to Notion before returning.",
        "- If the Notion command fails but the code task is complete, proceed with DONE.",
        f"- Delete `{WORKER_NOTION_WORKLOG_FILENAME}` after successfully logging to Notion.",
    ])


def _build_notion_log_instructions_not_applicable() -> str:
    return "Notion logging is not applicable for this task."


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
