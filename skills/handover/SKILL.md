---
name: handover
description: Summarise the current discussion for handover to another agent.
---

- Use `$AGENTS_REPO_ROOT/.handovers/` as the handover directory. If `$AGENTS_REPO_ROOT` is unset or empty, stop and ask the user to set it instead of guessing the repository root.
- If the user says "write", then please dump our discussion till now in extensive detail to `$AGENTS_REPO_ROOT/.handovers/` for handover to another agent. Create the directory if it does not exist. Name the file with a sortable timestamp, for example `2026-07-29-153000.md`. Please use the /log-as-lean-linear-story skill when doing so.
- If the user mentions "read", please read the handover contents of the latest or most relevant handover in `$AGENTS_REPO_ROOT/.handovers/`. If you are not sure, ask instead of blindly reading the wrong handover.
