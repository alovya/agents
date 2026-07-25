# Ralph

Ralph turns one durable plan into a sequence of isolated implementation slices.
Each slice runs in a fresh worker session with only the shared plan context and
the active task context.

## What a run does

Given this dependency graph:

```text
R1 Add parser
    ↓
R2 Add command line entrypoint
```

Ralph performs the following workflow:

1. Validate that `PLAN.md` and `ledger.yaml` describe the same acyclic task
   graph.
2. Create every corresponding NTT task before launching the first worker.
3. Make every NTT task an immediate child of the job's configured NTT parent.
4. Copy the complete Ralph dependency graph into NTT and validate the resulting
   structure.
5. Select the first pending task whose dependencies are done.
6. Give a fresh worker only the shared plan context, its active slice, its Ralph
   identity, its NTT identity, and the NTT logging contract.
7. Accept `DONE` only when the worker reports the committed repository `HEAD`
   and leaves no uncommitted changes.
8. Complete the NTT task after accepting the commit.
9. Mark the Ralph task done only after NTT confirms completion.
10. Repeat until no runnable task remains.

Workers returning `BLOCKED` or `ABORT` stop the loop and give the corresponding
status to the Ralph task.

## Job files

Ralph control state is private and must remain outside the target repository:

```text
<ralph-home-path>/jobs/<job-name>/
  PLAN.md
  ledger.yaml
  tasks/
```

Pass this control root explicitly with `--ralph-home-path`. Do not place a
private `PLAN.md`, `ledger.yaml`, or Ralph home directory inside the target
repository.

The `tasks/` directory contains prompts, transcripts, commit identities, and NTT
command outputs from each attempt.

## Plan shape

`PLAN.md` contains shared behavioural context followed by one behavioural slice
for every ledger task:

```markdown
<!-- ralph-shared:start -->
Build the smallest useful version of the feature.
<!-- ralph-shared:end -->

<!-- ralph-task:start R1 -->
Add a parser that accepts valid input and reports invalid input clearly.
<!-- ralph-task:end R1 -->

<!-- ralph-task:start R2 -->
Add a command line entrypoint that uses the parser.
<!-- ralph-task:end R2 -->
```

The planner chooses what context future workers receive. Content read from NTT
never enters the current worker prompt automatically.

See [`examples/PLAN.md`](examples/PLAN.md) for the canonical plan.

## Ledger shape

`ledger.yaml` stores identities, lifecycle state, and dependencies rather than
implementation prose:

```yaml
version: 1
job_name: example
ntt_ticket_prefix: PROJECT
ntt_parent_task_id: PROJECT-99
tasks:
  - ralph_task_id: R1
    title: Add parser
    status: pending
    depends_on: []
    ntt_task_id: null

  - ralph_task_id: R2
    title: Add command line entrypoint
    status: pending
    depends_on:
      - R1
    ntt_task_id: null
```

The planner leaves `ntt_task_id` null. The controller allocates and saves each
identity during eager materialisation.

See [`examples/ledger.yaml`](examples/ledger.yaml) for the canonical ledger.

## NTT ownership

NTT is the human-facing task graph and durable implementation journal:

```text
Planner    → chooses future worker context in PLAN.md
Controller → owns NTT structure, dependencies, validation, and completion
Worker     → implements one slice and appends implementation logs
NTT        → preserves task lifecycle and implementation history
```

Before execution, the NTT parent must be active and have no dependencies or
dependants. Every Ralph task becomes exactly one immediate child. Ralph and NTT
dependency edges must match exactly.

Workers use only `ntt --log` on their assigned task. They must not read tasks or
create, restructure, complete, cancel, or change dependencies on NTT tasks.

## Validate a job

Validate the control files without creating NTT tasks or launching workers:

```bash
python -m ralph.run_ralph_loop validate \
  --ralph-home-path <ralph-home-path> \
  --job-name <job-name>
```

Include the target repository to validate its non-mutating starting state:

```bash
python -m ralph.run_ralph_loop validate \
  --ralph-home-path <ralph-home-path> \
  --job-name <job-name> \
  --repo-path <repo-path>
```

The target repository must normally be clean. Use `--allow-dirty-start` only
when deliberately resuming existing uncommitted work.

## Run with direct Codex workers

Use direct execution when workers must log to NTT:

```bash
source /path/to/tool-venv/bin/activate && \
CODEX_HOME=<codex-config-dir> python -m ralph.run_ralph_loop run \
  --repo-path <repo-path> \
  --ralph-home-path <ralph-home-path> \
  --job-name <job-name> \
  --agent-backend codex \
  --skip-ralph-sandbox
```

`--skip-ralph-sandbox` is an explicit execution-mode switch. It gives Codex the
existing configuration, writable Git metadata, network access, and configured
NTT credentials.

Source the virtual environment and launch Ralph in the same shell command. The
controller validates that both `python` and `ntt` come from that environment,
then configures every direct Codex subprocess with the validated `PATH` and
`VIRTUAL_ENV`. Invoking `/path/to/tool-venv/bin/python` directly is not
equivalent because it does not activate the environment.

## Run with sandboxed workers

Without `--skip-ralph-sandbox`, Ralph preserves its Bubblewrap sandbox and runs
the worker visibility smoke test before the loop:

```bash
source /path/to/tool-venv/bin/activate && \
CODEX_HOME=<codex-config-dir> python -m ralph.run_ralph_loop run \
  --repo-path <repo-path> \
  --ralph-home-path <ralph-home-path> \
  --job-name <job-name> \
  --agent-backend codex
```

## Run with direct Claude workers

Use direct execution when workers must log to NTT:

```bash
source /path/to/tool-venv/bin/activate && \
CLAUDE_CONFIG_DIR=<claude-config-dir> python -m ralph.run_ralph_loop run \
  --repo-path <repo-path> \
  --ralph-home-path <ralph-home-path> \
  --job-name <job-name> \
  --agent-backend claude \
  --skip-ralph-sandbox
```

`--skip-ralph-sandbox` is an explicit execution-mode switch. It gives Claude the
existing configuration, writable Git metadata, network access, and configured
NTT credentials.

## Run with sandboxed Claude workers

Without `--skip-ralph-sandbox`, Ralph preserves its Bubblewrap sandbox:

```bash
source /path/to/tool-venv/bin/activate && \
CLAUDE_CONFIG_DIR=<claude-config-dir> python -m ralph.run_ralph_loop run \
  --repo-path <repo-path> \
  --ralph-home-path <ralph-home-path> \
  --job-name <job-name> \
  --agent-backend claude
```

Sandboxed workers cannot log directly to NTT unless their environment is given
the required network and credentials.

## Review each slice

Add `--ask-for-review` when each accepted worker commit should become an
uncommitted diff for human review before Ralph recommits it and continues:

```bash
python -m ralph.run_ralph_loop run \
  --repo-path <repo-path> \
  --ralph-home-path <ralph-home-path> \
  --job-name <job-name> \
  --ask-for-review
```

## Recovery and consistency

Materialisation and completion are ordered so interrupted runs can resume:

1. Ralph validates existing `ntt_task_id` values and creates only missing
   children.
2. Each newly allocated identity is written to the ledger immediately.
3. Dependency writes replace the complete dependency set, so retries are
   deterministic.
4. NTT structure is read back and compared with the ledger before workers run.
5. An NTT task completed before an interrupted ledger write is reconciled to
   `done` when the controller restarts.
6. A ledger task marked done while its NTT task is not completed is treated as a
   consistency error.
7. A graph mismatch stops execution instead of choosing one source silently.

If NTT creates a task but the ledger write fails, inspect the saved NTT command
output under the job directory before retrying. It contains the allocated task
identity needed for manual recovery.
