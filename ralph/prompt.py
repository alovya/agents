from __future__ import annotations

from pathlib import Path

from ralph.plan_selection import TaskSelection


def render_agent_prompt(
    repo_path: Path,
    selection: TaskSelection,
    python_venv_path: Path | None,
) -> str:
    return WORKER_PROMPT_TEMPLATE.format(
        repo_path=repo_path,
        tool_environment_context=describe_python_venv_for_worker_prompt(python_venv_path),
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


WORKER_PROMPT_TEMPLATE = """You are implementing one Ralph task in a fresh agent session.

You may use only the context in this prompt and the files available in the target repository.
The full Ralph plan is not available to you.

Repository:
{repo_path}

Agent tool environment:
{tool_environment_context}

Shared plan context:
{shared_plan_context}

Active task plan slice:
{active_task_plan_context}

Rules:
- Work only on the active task.
- Do not try to find or read Ralph controller state.
- Do not edit task ledgers, plan files, or Ralph task logs.
- Decide how to verify the completed behaviour and run the relevant checks before returning DONE.
- Commit the finished repo changes before returning DONE with `git commit --no-verify -m "Ralph: <task id> <task title>"`.
- Do not use `git commit` without `--no-verify`.

{notion_log_instructions}

- Include exactly one commit line:

RALPH_COMMIT <40-character git commit hash>

End your final answer with exactly one promise line:

<promise>DONE</promise>
<promise>BLOCKED</promise>
<promise>ABORT</promise>

Use DONE only when the task is implemented and ready for verification.
Use BLOCKED when external information, credentials, missing files, or a repo issue prevents progress.
Use ABORT when continuing would be unsafe.
"""


def _build_notion_log_instructions(task: dict[str, Any]) -> str:
    notion_task = task.get("notion_task")
    if not isinstance(notion_task, dict):
        return _build_notion_log_instructions_not_applicable()

    materialised_task_id = notion_task.get("materialized_task_id")
    if not materialised_task_id:
        return _build_notion_log_instructions_not_applicable()

    return "\n".join([
        "Notion worklog (required before DONE, BLOCKED, or ABORT):",
        f"- Write `{WORKER_NOTION_WORKLOG_FILENAME}` in the repository root as a valid JSON object with this exact shape:",
        '  ```json',
        '  {',
        '    "title": "Short log title",',
        '    "blocks": [',
        '      {"type": "paragraph", "text": "Human-readable summary"},',
        '      {"type": "code", "language": "text", "text": "command output or details"}',
        '    ]',
        '  }',
        '  ```',
        "- The `title` field is required and must be a non-empty string.",
        "- The `blocks` field is required and must be a non-empty list.",
        "- Each block must have `type` (either `paragraph` or `code`) and `text` (non-empty string).",
        "- Code blocks must also have `language` (non-empty string, e.g. `text`, `python`, `yaml`).",
        "- Include blocks for: commands run (with key outputs or errors), files changed and why, decisions made, and unresolved risks (if any).",
        "- Do not run `ntt` or contact Notion. The controller validates and submits this JSON.",
        f"- Never stage or commit `{WORKER_NOTION_WORKLOG_FILENAME}`. It is transient controller input, not a repository change.",
        "- Do NOT put the worklog JSON in your final answer. The controller reads it from the file.",
        "- Do NOT delete the worklog file. The controller deletes it after successful logging.",
        "- For BLOCKED or ABORT, include the blocker or abort reason in the worklog before returning.",
        "- If the worklog file is missing or malformed when you return DONE/BLOCKED/ABORT, the controller will reject the task.",
    ])


def _build_notion_log_instructions_not_applicable() -> str:
    return "Notion logging is not applicable for this task."
