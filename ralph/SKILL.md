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
