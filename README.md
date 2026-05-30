# Agents

Private source of truth for personal agent instructions and agent-specific prompts.

## Shape

```text
AGENTS.md
sync-skills.py
ralph/
  PROMPT.md
```

Each immediate child directory can become a Codex skill by adding a `SKILL.md` file:

```text
example_agent/
  SKILL.md
  PROMPT.md
```

Directories without `SKILL.md` are kept in Git but are not installed as Codex skills.

## Runtime Links

This repo is canonical. `~/.codex` is the installed runtime location.

Run:

```bash
python sync-skills.py
```

This installs symlinks:

```text
~/.codex/AGENTS.md
  -> ~/agents/AGENTS.md

~/.codex/skills/<agent-directory>
  -> ~/agents/<agent-directory>
```

`notion_task_tracker` now lives in its own repository at `~/notion_task_tracker`.
