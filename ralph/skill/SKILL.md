---
name: ralph
description: Create Ralph loop plans and ledgers, or run Ralph-style Codex task loops that slice durable plan context and execute one task per fresh worker.
---

# Ralph

Use this skill when creating or maintaining Ralph loop artefacts.

Ralph separates planning from execution:

1. Planning sessions may read and write `~/.ralph`.
2. Execution workers must not see `~/.ralph`.
3. The Ralph controller slices the private plan and gives each worker only the active task context.

## Project Shape

Store Ralph job state under:

```text
~/.ralph/jobs/<job-name>/
  PLAN.md
  ledger.yaml
  tasks/
```

Do not place Ralph control files in the target repository.

## Notion Task Pairing

When creating a Ralph plan, pair the Ralph job with ALOVYA tasks through the
`notion_task_tracker` skill. Notion is the human-facing project/task record; Ralph's
`PLAN.md` and `ledger.yaml` are private execution control files.

Ralph plans must encode the intended Notion task pairing up front, but must not
materialize every planned task in Notion up front. The ledger distinguishes the
planned task relationship from the actual Notion task id created later.

If the user mentions `parent:<id>` while asking for a Ralph plan:

1. Treat `<id>` as the root parent ALOVYA ticket for the initial Ralph task set.
2. Record that root parent in `ledger.yaml`.
3. For each planned Ralph task, record its intended Notion relationship in the
   task's ledger entry with `relationship` and `related_to`.
4. Do not create those Notion child tasks during planning. Leave their
   `materialized_task_id` as `null` until the worker starts that Ralph slice.
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
- `related_to: R1` means the relationship targets the Notion task materialized for
  Ralph task `R1`.

When `related_to` is another Ralph task id, the worker must resolve that task's
`materialized_task_id` before creating the new task. If the related Ralph task has
not materialized yet, the current task is not ready to materialize its Notion task;
fix the task dependency ordering or report `BLOCKED`.

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
2. During execution, log meaningful discoveries, blockers, design decisions, failed
   commands, stack traces, and changed approach when they affect the work.
3. At slice completion, log the concrete files changed, behaviour changed,
   verification commands run, command outputs or failures, unresolved risks, and the
   commit hash if the runner committed the slice.
4. Use detailed `notion_task_tracker` log content with paragraph and code blocks.
   Do not write vague entries such as "implemented R1" or "ran tests" when the
   useful content is the command, output, diff summary, or error.
5. If execution discovers follow-up tasks, log the reason and relationship on both
   the current task and the new child/sibling task when relevant.

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
<!-- ralph-task:end R1 -->
```

Each task id in `ledger.yaml` must have exactly one matching `ralph-task` block.

## Ledger Format

Keep `ledger.yaml` minimal. It may contain ids, titles, statuses, dependencies, touchable paths, and verification commands:

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
    verification_commands:
      - python -m pytest tests/test_parser.py
```

Do not copy task prose or full implementation notes into the ledger.

## Execution

Run:

```bash
python ~/agents/ralph/run_ralph_loop.py run --repo-path /path/to/repo --job-name example
```

If workers need helper commands from a Python venv, pass that venv explicitly:

```bash
python ~/agents/ralph/run_ralph_loop.py run --repo-path /path/to/repo --job-name example --python-venv /path/to/venv
```

The runner mounts that venv into the worker, sets `VIRTUAL_ENV`, and prepends
`/path/to/venv/bin` to `PATH`. The rendered prompt tells the worker that the venv is
already active; the worker can run those helper commands directly.

Do not pass Notion access through the worker venv. The controller owns Notion
materialisation and logging outside the worker sandbox.

The runner owns task selection, verification, ledger advancement, and commits.
