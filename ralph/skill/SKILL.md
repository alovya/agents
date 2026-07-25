---
name: ralph
description: Create Ralph loop plans and ledgers, or run Ralph-style Codex task loops that slice durable plan context and execute one task per fresh worker.
---

# Ralph

Use this skill when planning, running, or maintaining a Ralph job.

Read [`../README.md`](../README.md) before changing Ralph control artefacts or
running the controller. The README owns behaviour, file shapes, commands,
execution modes, NTT lifecycle, and recovery semantics. The canonical examples
own the exact plan and ledger formats.

## Choose one role

1. Planner

   1. Create or update private control artefacts outside the target repository.
   2. Put shared behavioural context and one behavioural slice per task in
      `PLAN.md`.
   3. Put identities, dependencies, and lifecycle state in `ledger.yaml`.
   4. Stop after writing or presenting the plan. Do not implement repository
      changes or launch workers.

2. Controller

   1. Validate the job before running it.
   2. Prepare the target branch or worktree.
   3. Pass the private control root explicitly with `--ralph-home-path`.
   4. Run `ralph/run_ralph_loop.py` rather than implementing worker slices
      manually.
   5. Inspect controller outputs and stop on graph, lifecycle, commit, or
      repository inconsistencies.

3. Worker

   1. Implement only the active slice supplied by the controller.
   2. Do not read Ralph controller state or run Ralph commands.
   3. Log implementation history only to the assigned NTT task with
      `ntt --log`.
   4. Do not read or alter NTT structure or lifecycle.

## Apply judgement

- Keep private Ralph state outside the target repository.
- Let the planner decide what prior knowledge belongs in future worker context.
- Never insert NTT reads into the current worker prompt.
- Source `<tool-venv>/bin/activate` and launch Ralph in the same shell command
  so the controller and workers inherit `ntt`, its network access, and its
  credentials.
- Use `--ask-for-review` when the user wants to review each completed slice
  before Ralph continues.
