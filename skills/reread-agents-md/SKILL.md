---
name: reread-agents-md
description: Reread $AGENTS_REPO_ROOT/AGENTS.md. Use when the user asks to reread, reload, or refresh AGENTS.md, or says the instructions may be stale.
disable-model-invocation: true
---

- Use `$AGENTS_REPO_ROOT/AGENTS.md` as the file to reread. If `$AGENTS_REPO_ROOT` is unset or empty, stop and ask the user to set it instead of guessing the repository directory.
- Read the full file fresh from disk; do not rely on any earlier cached read of it from this conversation.
- After reading, apply the instructions in it for the rest of the conversation, and mention explicitly if anything changed since the version you had before.
