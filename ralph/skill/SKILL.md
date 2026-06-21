---
name: ralph
description: Create Ralph loop plans and ledgers, or run Ralph-style Codex task loops that slice durable plan context and execute one task per fresh worker.
---

# Ralph

Use this skill when creating or maintaining Ralph loop artefacts.

Ralph separates planning from execution:

1. Planning sessions may read and write `/workspace/.ralph`.
2. Execution workers must not see Ralph controller state or credential-bearing
   personal/tool state under `HOME` or `/workspace`.
3. The Ralph controller slices the private plan and gives each worker only the active task context.

## Project Shape

Store Ralph job state under:

```text
/workspace/.ralph/jobs/<job-name>/
  PLAN.md
  ledger.yaml
  tasks/
```

Do not place Ralph control files in the target repository.
Set `RALPH_HOME` only when a host needs a different explicit Ralph control root.
Use `/workspace/.notion-task-tracker/notion_tasks_tree.json` as the default
Notion tracker state for controller-owned `ntt` calls.

## Notion Task Pairing

When creating a Ralph plan, pair the Ralph job with ALOVYA tasks through the
`notion_task_tracker` skill. Notion is the human-facing project/task record; Ralph's
`PLAN.md` and `ledger.yaml` are private execution control files.

Ralph plans must encode the intended Notion task pairing up front, but must not
materialise every planned task in Notion up front. The ledger distinguishes the
planned task relationship from the actual Notion task id created later.

If the user mentions `parent:<id>` while asking for a Ralph plan:

1. Treat `<id>` as the root parent ALOVYA ticket for the initial Ralph task set.
2. Record that root parent in `ledger.yaml`.
3. For each planned Ralph task, record its intended Notion relationship in the
   task's ledger entry with `relationship` and `related_to`.
4. Do not create those Notion child tasks during planning. Leave their
   `materialized_task_id` as `null` until the controller starts that Ralph slice.
5. For later subtasks discovered while planning or executing, decide the relationship
   from the work structure:
   - Use `notion_task child <existing-child-id> [title]` when the new work is a
     narrower implementation slice, investigation, follow-up, or blocker under an
     existing child task.
   - Use `notion_task sibling <existing-child-id> [title]` when the new work is a
     peer track next to an existing child task under the same parent.
6. Do not force every later task directly under the original `parent:<id>`; use that
   parent as the root of the initial task tree, then attach new tasks where they
   semantically belong.

`related_to` may be either an existing ALOVYA task id or another Ralph task id:

- `related_to: ALOVYA-89` means the relationship targets an existing Notion task.
- `related_to: R1` means the relationship targets the Notion task materialised for
  Ralph task `R1`.

When `related_to` is another Ralph task id, the controller must resolve that task's
`materialized_task_id` before creating the new task. If the related Ralph task has
not materialised yet, the current task is not ready to materialise its Notion task;
fix the task dependency ordering before launching the worker or report `BLOCKED`.

If the user does not mention `parent:<id>`, create a top-level task with
`notion_task parent [title]` only when the Ralph work needs a root human-facing
container. For small one-off loops, ask whether they want a Notion task before
creating one.

Each planned Ralph task should have a `notion_task` entry in `ledger.yaml`:

```yaml
notion:
  root_parent_task_id: ALOVYA-89

tasks:
  - id: R1
    title: Delete redundant Notion client wrapper
    status: pending
    notion_task:
      planned: true
      relationship: child
      related_to: ALOVYA-89
      title: Delete redundant Notion client wrapper
      materialized_task_id: null
```

When the controller starts a Ralph task, it should materialise the planned Notion
task before launching the worker if `materialized_task_id` is `null`, using the
planned relationship and title from the ledger:

- `relationship: child` means call `ntt child <resolved related_to> <title>`.
- `relationship: sibling` means call `ntt sibling <resolved related_to> <title>`.

After creation, update the ledger with the assigned task id. A planned task is not
considered paired for execution until `materialized_task_id` is set.

Materialising the Notion task is not enough. The controller should keep the paired
Notion task useful as a human-facing execution log without exposing Notion
credentials or tracker state to workers:

1. At slice start, log the Ralph task id, goal, touchable paths, verification
   commands, and any immediate assumptions or constraints.
2. Workers write a `.ralph-worklog.json` file in the repository root with rich
   execution details. Workers do NOT run `ntt` or any Notion commands. The
   controller validates the worklog file and sends it to Notion after the worker
   returns DONE, BLOCKED, or ABORT.
3. At slice completion, the controller logs the concrete files changed, verification
   commands run, and the commit hash.
4. Use detailed `notion_task_tracker` log content with paragraph and code blocks.
   Do not write vague entries such as "implemented R1" or "ran tests" when the
   useful content is the command, output, diff summary, or error.
5. If execution discovers follow-up tasks, log the reason and relationship on both
   the current task and the new child/sibling task when relevant.

The worker worklog file must have this exact JSON shape:

```json
{
  "subheading": "Short log title",
  "blocks": [
    {"type": "paragraph", "text": "Human-readable summary"},
    {"type": "code", "language": "text", "text": "command output or details"}
  ]
}
```

Required fields:
- `subheading`: non-empty string
- `blocks`: non-empty list of block objects
- Each block: `type` ("paragraph" or "code") and `text` (non-empty string)
- Code blocks also require `language` (non-empty string)

If the worker returns DONE, BLOCKED, or ABORT and the worklog file is missing or
malformed, the controller rejects the task with a clear validation error.

Record paired ALOVYA task ids in `ledger.yaml`, but do not copy Notion task prose or
implementation notes into `ledger.yaml`.

## Plan Format

Write `PLAN.md` with comment fences:

```md
<!-- ralph-shared:start -->
Context every task may see.
<!-- ralph-shared:end -->

<!-- ralph-task:start R1 -->
Only task R1 context.

<!-- ralph-allowed-bash:start -->
- rg *
- sed -n *
<!-- ralph-allowed-bash:end -->

<!-- ralph-verification:start -->
- python -m pytest tests/test_parser.py
<!-- ralph-verification:end -->
<!-- ralph-task:end R1 -->
```

Each task id in `ledger.yaml` must have exactly one matching `ralph-task` block.
Each `ralph-task` block must include exactly one `ralph-allowed-bash` block and
exactly one `ralph-verification` block.

## Ledger Format

Keep `ledger.yaml` minimal. It may contain ids, titles, statuses, dependencies, and touchable paths. Keep command policy in `PLAN.md`:

```yaml
version: 1
job_name: example
notion:
  root_parent_task_id: ALOVYA-89
tasks:
  - id: R1
    title: Add parser
    status: pending
    notion_task:
      planned: true
      relationship: child
      related_to: ALOVYA-89
      title: Add parser
      materialized_task_id: null
    depends_on: []
    touchable_paths:
      - src/parser.py
      - tests/test_parser.py
```

Do not copy task prose or full implementation notes into the ledger.

## Execution

Run as a direct script or as a package module:

```bash
CODEX_HOME=/workspace/.codex python /workspace/agents/ralph/run_ralph_loop.py run --repo-path /path/to/repo --job-name example --agent-backend codex
```

Or equivalently as a package:

```bash
CODEX_HOME=/workspace/.codex python -m ralph.run_ralph_loop run --repo-path /path/to/repo --job-name example --agent-backend codex
```

Codex workers require `CODEX_HOME` to point at the Codex state directory that the
worker may use. Ralph mounts only that selected Codex state path, not the whole
host home directory.

Run Claude Code workers by selecting the Claude backend and passing the Claude
state directory:

```bash
CLAUDE_CONFIG_DIR=/workspace/.claude python /workspace/agents/ralph/run_ralph_loop.py run --repo-path /path/to/repo --job-name example --agent-backend claude
```

Claude workers require `CLAUDE_CONFIG_DIR` to point at the Claude Code state
directory that the worker may use. Ralph mounts only that selected Claude state
path, and does not pass `CODEX_HOME` to Claude workers.

### Claude Worker Output

Claude worker output produces two artefacts for each task:

1. `agent-output.txt` is the operator-facing transcript. It is the text Ralph
   tees to the terminal while the worker is running.
2. `agent-output.raw.jsonl` is the diagnostic transcript. It preserves Claude's
   newline-delimited stream-json exactly as Claude emitted it.

The readable transcript favours the events a human needs while watching a task:

1. Assistant text is written as plain transcript lines.
2. Assistant tool-use blocks are summarised as the tool name plus useful input
   fields such as the command and description.
3. User tool-result blocks are written as command output, or as tool errors when
   Claude marks the result as an error.
4. Result events write the final answer when that answer has not already appeared
   in assistant text.
5. Hook and partial-message events are suppressed unless they carry a useful
   error message.
6. Malformed stream lines are kept visible in the readable transcript so an
   operator can see that Claude emitted invalid stream-json.

Promise parsing still uses Claude's final `result` event when that event is
available. If Claude does not emit a final result event, Ralph falls back to the
last assistant text. Keep the raw stream artefact available because hook events,
partial messages, usage metadata, and malformed stream lines can be useful when
debugging a Claude worker or the formatter itself.

If workers need helper commands from a Python venv, pass that venv explicitly:

```bash
CODEX_HOME=/workspace/.codex python /workspace/agents/ralph/run_ralph_loop.py run --repo-path /path/to/repo --job-name example --agent-backend codex --python-venv /path/to/venv
```

The runner mounts that venv into the worker, sets `VIRTUAL_ENV`, and prepends
`/path/to/venv/bin` to `PATH`. The rendered prompt tells the worker that the venv is
already active; the worker can run those helper commands directly.

Do not pass Notion access through the worker venv. The controller owns Notion
materialisation and logging outside the worker sandbox.

The runner owns task selection, verification, ledger advancement, and commits.

## Codex Worker Command Enforcement

When running Codex workers, Ralph enforces command restrictions through Codex
execpolicy rules rather than relying on `--ignore-rules`:

1. Before launching a Codex worker, Ralph snapshots the real
   `CODEX_HOME/rules/default.rules` file.
2. Ralph writes a backup marker under the active task directory containing
   enough information to restore the original rules if Ralph crashes.
3. Ralph generates a per-task execpolicy rules file from the allowed bash
   commands and atomically replaces the real rules file.
4. Codex launches with `--ask-for-approval untrusted` instead of
   `--ask-for-approval never --ignore-rules`.
5. After Codex finishes (success, error, or exception), Ralph restores the
   original rules file from the snapshot and deletes the backup marker.

If Ralph crashes after writing generated rules, the next Ralph run detects the
stale backup marker, restores the original rules, deletes the marker, and
refuses to continue with a clear message asking the operator to restart.

Generated rules use Codex execpolicy syntax:

```text
prefix_rule(pattern=['rg'], decision="allow")
prefix_rule(pattern=['sed', '-n'], decision="allow")
prefix_rule(pattern=['git', 'commit', '--no-verify', '-m'], decision="allow")
```

A trailing `*` in the allowed command list means extra trailing arguments are
permitted. Ralph strips that final `*` before building the prefix rule pattern:

- `rg *` becomes `prefix_rule(pattern=['rg'], decision="allow")`
- `sed -n *` becomes `prefix_rule(pattern=['sed', '-n'], decision="allow")`

Commands without a trailing `*` must match exactly.
