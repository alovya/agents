---
name: view-diff
description: Expose an existing commit or set of local committed changes as an unstaged working-tree diff so the user can review it in VS Code Source Control. Use when the user asks to view a git diff in VS Code, says they need Source Control to show a commit's changes, asks to uncommit for review, or asks to expose the appropriate commit for diff review.
disable-model-invocation: true
---

# View Diff

Make the requested commit visible as ordinary unstaged file changes, without losing its content.

## Workflow

1. Identify the commit or commits the user wants to review.
2. Confirm the worktree state with `git status --short`.
3. If the requested changes are already committed at `HEAD`, run `git reset --mixed HEAD^` for one commit, or `git reset --mixed <base-ref>` for a stack of commits.
4. If the requested commit is not at `HEAD`, choose the least surprising Git operation that exposes the same patch as unstaged changes, and explain the chosen base before acting.
5. Run `git status --short` again and report that VS Code Source Control should now show the diff.

## Guardrails

- Preserve the file content. Do not use commands that discard working-tree changes.
- Prefer unstaged changes so the Source Control panel shows normal file diffs.
- If unrelated local changes exist, stop and explain the conflict before rewriting commits.
- If the commit has already been pushed or belongs to a shared branch, mention that exposing it locally rewrites only the local checkout unless the user later pushes.
