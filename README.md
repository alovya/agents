# Agents

Private source of truth for personal agent tooling.

## Shape

```text
skills/
  notion_task/
    SKILL.md

notion_task_tracker/
  README.md
  DESIGN.md
  *.py
  tests/

scripts/
  sync.py
```

## Runtime Links

This repo is canonical. `~/.codex` is the installed runtime location.

Run:

```bash
python scripts/sync.py
```

This installs symlinks:

```text
~/.codex/skills/notion_task
  -> ~/agents/skills/notion_task

~/.codex/memories/notion_task_tracker
  -> ~/agents/notion_task_tracker
```

The local tracker state remains outside git:

```text
~/.codex/memories/notion_tasks_graph.json
```

Auth remains outside git:

```text
~/.codex/.credentials.json
```

## Test

```bash
PYTHONPATH=$PWD /workspace/venv/bin/python -m pytest \
  notion_task_tracker/tests \
  notion_task_tracker/task_pages/tests
```

