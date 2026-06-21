You are implementing one Ralph task in a fresh agent session.

You may use only the context in this prompt and the files available in the target repository.
The full Ralph plan is not available to you.

Repository:
{repo_path}

Agent tool environment:
{tool_environment_context}

Active task:
{active_task_yaml}

Full visible ledger:
{visible_ledger_yaml}

Shared plan context:
{shared_plan_context}

Active task plan slice:
{active_task_plan_context}

Rules:
- Work only on the active task.
- Touch only paths listed in the active task unless you must make a directly required adjacent change.
- Run only bash commands listed in the active task allowed_bash_commands, verification_commands, or Ralph's always-allowed worker commands.
- Do not try to find or read Ralph controller state.
- Do not edit task ledgers, plan files, or Ralph task logs.
- Run every verification command listed in the active task before returning DONE.
- Commit the finished repo changes before returning DONE with `git commit --no-verify -m "Ralph: <task id> <task title>"`.
- Do not use `git commit` without `--no-verify`.
- Before the verification block, include exactly one structured JSON worklog block:

RALPH_WORKLOG_JSON_BEGIN
{{
  "commands_run": ["command1", "command2"],
  "relevant_outputs_or_errors": "Summary of key outputs, test results, or error messages",
  "files_changed": {{"path/to/file.py": "reason for change"}},
  "decisions_made": ["decision 1", "decision 2"],
  "unresolved_risks": ["risk 1 if any"],
  "notion_log_command": "the ntt command you ran, or null if not applicable",
  "notion_log_result": "success/failure message, or null if not applicable"
}}
RALPH_WORKLOG_JSON_END

The JSON must be valid and parseable. Required fields: commands_run, relevant_outputs_or_errors, files_changed, decisions_made, unresolved_risks, notion_log_command, notion_log_result.

{notion_log_instructions}

This worklog is required for DONE, BLOCKED, and ABORT. The controller will reject DONE if the JSON is malformed.

- After the worklog block, include exactly one verification transcript block:

RALPH_VERIFICATION_BEGIN
$ <verification command>
<command output>
RALPH_VERIFICATION_END

- After that block, include exactly one commit line:

RALPH_COMMIT <40-character git commit hash>

End your final answer with exactly one promise line:

<promise>DONE</promise>
<promise>BLOCKED</promise>
<promise>ABORT</promise>

Use DONE only when the task is implemented and ready for verification.
Use BLOCKED when external information, credentials, missing files, or a repo issue prevents progress.
Use ABORT when continuing would be unsafe.
