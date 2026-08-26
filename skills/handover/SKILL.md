---
name: handover
description: Handover work to or from another agent.
disable-model-invocation: true
---

# Handover

Use this skill to handover work to or from another agent.

## Instructions

- **The `$AGENTS_REPO_ROOT/.handovers/` directory should contain all handovers.** Create it if it does not exist, and if `$AGENTS_REPO_ROOT` is unset or empty, stop and ask the user to set it instead of guessing it.
- **If the user mentions "write":** you are to dump our relevant conversations or investigations in extensive detail to a Markdown file for handover to another agent so that they can continue working on it; use the /make-lean-linear-and-coherent skill, and name the file with a sortable timestamp and a natural topic title, e.g. `2026-07-29-153000-<topic-title-about-some-conversation-or-investigation>.md`.
- **If the user mentions "read":** please read the handover contents of the handover most relevant to what the user requested. If you are not sure, please ask instead of blindly reading the wrong handover.