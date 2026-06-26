---
name: ralph
description: Create Ralph loop plans and ledgers, or run Ralph-style Codex task loops that slice durable plan context and execute one task per fresh worker.
---

# Ralph

Use this skill when creating or maintaining Ralph loop artefacts.

Ralph is a controller for slicing a private plan into isolated worker tasks. The
skill should guide human judgement; validators, prompts, tests, and examples own
the exact file contracts.

## Role Boundary

Decide which role the current agent is playing before acting:

1. Planner: create or update Ralph control artefacts under `/workspace/.ralph`.
   Stop after writing or presenting those artefacts. Do not implement target
   repository changes and do not launch workers.
2. Controller: run `ralph/run_ralph_loop.py`, prepare branches or worktrees,
   materialise and log Notion tasks, inspect Ralph outputs, and handle
   verification failures.
   Do not manually implement worker tasks in the main session.
3. Worker: only an agent launched by the Ralph runner implements one selected
   task. Workers must not read Ralph controller state or run Ralph commands.
   Workers should use `ntt` to log detailed work on the materialised Notion task
   when the active task has Notion pairing.

Task `ralph-allowed-bash` blocks belong to the isolated worker. Include only the
commands needed to complete, log, and verify that one task.

## Files

Store Ralph job state outside the target repository:

```text
/workspace/.ralph/jobs/<job-name>/
  PLAN.md
  ledger.yaml
  tasks/
```

Use `RALPH_HOME` only when the host needs a different explicit Ralph control root.
Do not place private Ralph control files in the target repository.

## Notion Pairing

Notion is the human-facing task record. Ralph's `PLAN.md` and `ledger.yaml` are
private execution control files.

When a user gives `parent:<id>`, treat it as the root ALOVYA task for the initial
Ralph task set. Record intended Notion relationships in `ledger.yaml`, but do not
materialise every planned Notion task during planning. The controller materialises
each task when its Ralph slice starts.

Choose relationships by work shape:

1. Use `child` when the new task narrows, investigates, follows up, or unblocks
   an existing task.
2. Use `sibling` when the new task is a peer track under the same parent.
3. Use `related_to: ALOVYA-123` for an existing Notion task.
4. Use `related_to: R1` only when the current Ralph task depends on `R1`, so the
   controller can resolve the materialised Notion id first.

For small one-off loops without a `parent:<id>`, ask whether the user wants a
Notion task before creating one.

## Canonical Shape

Keep the canonical example files valid:

```text
ralph/examples/PLAN.md
ralph/examples/ledger.yaml
```

Use that shape when creating a new job. Keep command policy in `PLAN.md`, keep
task status and Notion pairing in `ledger.yaml`, and avoid copying task prose or
implementation notes into the ledger.

## Validate Before Running

Run validation before handing off a plan or launching workers:

```bash
python -m ralph.run_ralph_loop validate --job-name <job-name>
python -m ralph.run_ralph_loop validate --job-name <job-name> --repo-path <repo-path>
```

With `--repo-path`, validation also checks the non-mutating start state that a run
would require. Validation does not materialise Notion tasks and does not launch
workers.

Run Ralph commands that launch inner agent sandboxes with network access;
otherwise the inner sandboxes fail.

Run the loop only after validation passes:

```bash
CODEX_HOME=/workspace/.codex python -m ralph.run_ralph_loop run --repo-path <repo-path> --job-name <job-name> --agent-backend codex
CLAUDE_CONFIG_DIR=/workspace/.claude python -m ralph.run_ralph_loop run --repo-path <repo-path> --job-name <job-name> --agent-backend claude
```

Add `--ask-for-review` when the user wants to review each completed Ralph task
before Ralph commits it and moves on to the next task.
