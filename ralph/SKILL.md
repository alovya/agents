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

Store Ralph project state under:

```text
~/.ralph/projects/<project-name>/
  PLAN.md
  ledger.yaml
  runs/
```

Do not place Ralph control files in the target repository.

## Notion Task Pairing

When creating a Ralph plan, pair the Ralph project with ALOVYA tasks through the
`notion_task_tracker` skill. Notion is the human-facing project/task record; Ralph's
`PLAN.md` and `ledger.yaml` are private execution control files.

If the user mentions `parent:<id>` while asking for a Ralph plan:

1. Treat `<id>` as the parent ALOVYA ticket for the initial Ralph task set.
2. Create the initial Notion task or tasks as children of that parent with
   `notion_task child <id> [title]`.
3. For later subtasks discovered while planning or executing, decide the relationship
   from the work structure:
   - Use `notion_task child <existing-child-id> [title]` when the new work is a
     narrower implementation slice, investigation, follow-up, or blocker under an
     existing child task.
   - Use `notion_task sibling <existing-child-id> [title]` when the new work is a
     peer track next to an existing child task under the same parent.
4. Do not force every later task directly under the original `parent:<id>`; use that
   parent as the root of the initial task tree, then attach new tasks where they
   semantically belong.

If the user does not mention `parent:<id>`, create a top-level task with
`notion_task parent [title]` when the Ralph work is substantial enough to track. For
small one-off loops, ask whether they want a Notion task before creating one.

Record the paired ALOVYA task ids in Ralph project metadata or `ledger.yaml`, but do
not copy Notion task prose or implementation notes into `ledger.yaml`.

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
project_name: example
tasks:
  - id: R1
    title: Add parser
    status: pending
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
python ~/agents/ralph/run_ralph_loop.py run --repo-path /path/to/repo --project-name example
```

The runner owns task selection, verification, ledger advancement, and commits.
