# Notion Task Tracker Design

This package preserves three Notion page families:

1. A recursive ALOVYA task graph with ongoing and completed landing pages.
2. A dated miscellaneous-notes inbox.
3. A flat synthesis-notes index with reusable synthesis subpages.

The tracker is deterministic. Agents provide semantic input; Python owns graph projection, priority rollup, rendering, MCP tool names, MCP arguments, and call ordering.

## Task Pages

Every task is a row in `Alovya's task database`. Notion owns the structured fields:

```text
Ticket ID: 72
Ticket page: Measure activation mismatch after QNN export
Priority: P1
Status: Active
Parent: ALOVYA-5
Children: inverse relation
```

Task page bodies contain only timeline notes:

```text
Timeline log
2026-05-24
Investigated the current blocker.
```

Task-page body details:

1. `Timeline log` contains dated entries, newest first.
2. A dated entry can contain plain bullets or a subheading toggle with child bullets.
3. Priority, status, parent, and children live in database properties, not the page body.
4. PRs, Jira tickets, branches, docs, and source notes belong inside the relevant timeline entry.
5. Completed task pages use strikethrough page titles and priority `N/A` in derived views.

Task ids are always derived from Notion's `Ticket ID`.

## Task Graph

Tasks form a parent-child graph. The database `Parent` relation is authoritative during reconciliation.

Priority rolls upward only through `Active` and `Blocked` descendants:

```text
ALOVYA-2 P1
  ALOVYA-6 P2
    ALOVYA-7 P0 Active
```

Displayed priority becomes:

```text
ALOVYA-7 P0
ALOVYA-6 P0
ALOVYA-2 P0
```

When ALOVYA-7 becomes `Complete`, `Cancelled`, or `Parked`, ancestors recalculate from their own configured priority and any remaining active or blocked descendants.

## Task Landing Pages

The ongoing landing page is a derived task index. It groups incomplete top-level task trees by displayed priority. Once a top-level task is shown, its subtree is rendered with completed subtasks included.

```text
P0 (high impact and urgent) red
P1 (high impact) orange
P2 (lower impact but urgent) yellow
P3 (lower impact and not urgent) gray
```

The completed landing page contains terminal status sections for top-level tasks only. Completed children of ongoing top-level tasks stay off the completed landing page until their top-level task is also complete.

```text
Completed green
Cancelled gray
```

Each entry is a page mention with priority label and status. Indentation communicates nestedness within that page's filtered tree. Completed entries use `N/A`, green, and strikethrough inherited from the task page title.

## Task Locality

Task updates should stay local:

1. A parent lists direct children only.
2. The database `Parent` relation records direct child links.
3. A parent timeline records direct work and direct-child updates.
4. Deep child details appear on ancestors only when they affect status, priority, blockers, milestones, or reporting.

Example:

```text
ALOVYA-2
  ALOVYA-3
    ALOVYA-5
  ALOVYA-4
```

ALOVYA-2 directly owns ALOVYA-3 and ALOVYA-4 through database relations. ALOVYA-5 belongs on ALOVYA-3 unless it changes top-level state.

## Task Reconciliation

Task reconciliation runs before every task, miscellaneous, or synthesis command. It updates the local tracker state from database rows, then regenerates derived views only when it detects task graph changes.

1. Query the saved `Alovya's task database` view.
2. Convert rows into task metadata.
3. Rebuild parent-child links from database `Parent` relations.
4. Preserve local timeline metadata where the row maps to a known page.
5. Validate the graph and recalculate displayed priorities.
6. Repair derived landing pages and task titles when the graph projection changes.

If no change is detected, no repair write is sent. If repairs are needed, the CLI writes them before applying the user's requested command.

## Miscellaneous Notes

The miscellaneous root page is a dated inbox. It is independent of the task graph.

```text
Alovya's miscellanous notes

2026-05-24
2026-05-23
```

A dated subpage is just captured context:

```text
2026-05-24

Random thought not yet tied to a task.
Link to something potentially useful.
Meeting fragment.
```

Use miscellaneous notes when the user wants to dump context before it has a task or synthesis home.

## Synthesis Notes

The synthesis root page is a flat dump of page mentions and child pages. It has no headings, summaries, bullets, or nested storage.

```text
Alovya's synthesis notes

ONNX QDQ export behaviour
Activation outliers after SwiGLU
```

The root may contain:

1. Existing Notion pages that the tracker mentions but must not rewrite.
2. Tracker-created synthesis subpages.

A tracker-created synthesis subpage has:

```text
Title

Sources
Notion page: ALOVYA-2
Miscellaneous notes: 2026-05-24
Google doc: Export notes: https://example.invalid/doc

Reusable synthesis content.
```

Synthesis reconciliation reads the root page, preserves root order, preserves child-page tags as child-page tags, and replaces the local existing-page mention list with exactly what the root contains. It emits no Notion write calls.

## Agent Boundary

Agents may decide:

1. Task titles.
2. Timeline prose.
3. Whether work deserves a new task.
4. Which existing task owns an update.
5. Miscellaneous note content.
6. Synthesis title, sources, summary, and content.
7. Missing page titles for bare fetched synthesis mentions.

The tracker owns:

1. Ticket-id extraction from Notion database rows.
2. Parent-child graph mutation.
3. Priority rollup.
4. Fixed page structure.
5. Page mentions and colours.
6. Enhanced Markdown rendering.
7. MCP tool names and arguments.
8. Page-id blockers and call ordering.
9. Tracker-state shape.

Agents should use command JSON through the CLI. Do not hand-build Notion calls when the tracker supports the requested operation.

## Notion Boundary

Live fetches and writes use the authenticated Notion MCP client. Commands generate exact Notion MCP calls internally so the business logic stays deterministic and inspectable.

Normal writes compile to:

```text
notion-create-pages
notion-update-page with replace_content
notion-update-page with update_properties
```

After miscellaneous or synthesis `notion-create-pages`, the CLI records the returned page id and runs the needed refresh command. Task creation captures the new database row and assigned `Ticket ID` during live command execution.

Footgun: never set `allow_deleting_content` automatically. If Notion rejects replacement because physical child pages are present, stop and resolve the page layout.

The REST request planner and REST client are kept for the future REST-token path. They do not feed the MCP path, and the MCP path does not feed them. Do not grow the local enhanced-Markdown renderer into a general Notion SDK.

## Runtime

Run from the local virtual environment. Alovya's bashrc defines `src_venv` as sourcing `/workspace/venv/bin/activate`.
