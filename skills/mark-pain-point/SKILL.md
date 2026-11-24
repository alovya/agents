---
name: mark-pain-point
description: Record workflow pain points for later improvement.
---

# Mark a pain point

Use this skill to capture workflow pain points for later follow-up.

## Instructions

- **The `$AGENTS_REPO_ROOT/.pain-points/` directory should contain all pain points.** Create it if it does not exist, and if `$AGENTS_REPO_ROOT` is unset or empty, stop and ask the user instead of guessing.
- **If the user mentions "pain point":** record the workflow issue in a Markdown file with a sortable timestamp and a natural topic title, e.g. `2026-07-29-153000-<workflow-pain-point-title>.md`. Use the `/make-lean-linear-and-coherent` skill, preserve the reported issue and relevant context and acknowledge the note's path.
