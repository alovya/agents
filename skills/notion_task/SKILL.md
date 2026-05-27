---
name: notion_task
description: Work or create ALOVYA tasks, log ALOVYA task progress, complete or cancel ALOVYA tasks, capture miscellaneous notes, or create synthesis notes from the personal Notion task graph. Use when the user types notion_task work N, notion_task log N [notes], notion_task complete N [notes], notion_task cancel N [notes], notion_task new [pX] [title], notion_task child PARENT [pX] [title], notion_task sibling EXISTING [pX] [title], notion_task misc [title] NOTES, notion_task synth [title] SOURCES NOTES, asks to continue an existing ALOVYA task, or asks to write task/misc/synthesis context to Notion.
---

# Notion Task

## First Steps

1. Let `codex_home` be `$CODEX_HOME` if set, otherwise `~/.codex`.
2. Let `memories_dir` be `codex_home / "memories"`.
3. Read `memories_dir / "notion_task_tracker" / "README.md"` before creating commands or interpreting command results.
4. Read `memories_dir / "notion_task_tracker" / "DESIGN.md"` only when page shape, priority behaviour, or fuzzy boundaries are unclear.
5. Use `memories_dir / "notion_tasks_graph.json"` as the canonical tracker state.

The README is the API guide. Do not rederive schemas from memory.

## Shared Workflow

Before any command that creates or updates task, miscellaneous, or synthesis metadata:

1. Express the user action as command JSON.
2. Run the tracker CLI as documented in README, with network access outside the sandbox.
3. Let the CLI fetch only the task pages needed by the command, refresh their local metadata projection, apply the command, write to Notion, and save tracker state.
4. Treat CLI errors as failed writes. Do not manually send Notion writes unless debugging with the user.
5. If page creation still needs a captured page id, stop and report the blocker instead of guessing.

If `NOTION_API_KEY` is missing, stop and report that REST execution needs the `ntn_` Notion integration token. Use `--notion-transport mcp` only as a temporary fallback while REST reliability is being proven.

Footgun: never set `allow_deleting_content` automatically. If Notion rejects replacement due to physical child content, stop and explain the blocker.

## Runtime And Auth

Live Notion tracker commands must be run outside the network-restricted Codex sandbox. The default path calls the Notion REST API with `NOTION_API_KEY`.

Use the venv Python and request command escalation for live Notion commands:

```bash
PYTHONPATH=/home/alovyachowdhury/.codex/memories \
  /workspace/venv/bin/python -m notion_task_tracker ...
```

If the explicit MCP fallback reaches `https://mcp.notion.com/mcp` but returns `401 Unauthorized`, refresh auth with:

```bash
codex mcp login Notion
```

For REST, diagnose `401 Unauthorized` as a missing or invalid `NOTION_API_KEY`. Page-permission failures usually return `403`.

## Command Forms

`notion_task update` reconciles local task metadata from the saved `Alovya's task database` view and repairs derived views when needed.

1. Run `python -m notion_task_tracker --reconcile-from-notion` outside the sandbox.
2. Read printed `task_graph_changes` and `warnings`.
3. Treat CLI errors as failed writes.
4. If the saved view query fails, stop and report that task database reconciliation failed.

Normal task commands do not query the full saved database view. They use targeted task-page fetches; run `notion_task update` only for explicit reconciliation or when targeted preflight says the local tracker state is missing a related page.

`notion_task work <number>` works an existing task.

1. Resolve `<number>` to `ALOVYA-<number>`.
2. Fail if the task does not exist.
3. Suggest `notion_task new [pX] [title]` or `notion_task child <parent-number> [pX] [title]` when creation is needed.
4. Fetch the task page and directly relevant parent or child pages only when useful for the work.

`notion_task log <number> [notes]` writes recent progress to an existing task timeline.

1. Resolve `<number>` to `ALOVYA-<number>`.
2. Fail if the task does not exist.
3. Summarise relevant current conversation context plus `[notes]` as concise timeline lines.
4. Use today's date for `entry_date`.
5. Use a heading of `<mention-date start="YYYY-MM-DD"/>`.
6. Use `append_task_timeline_log`.
7. The tracker preserves handwritten Notion timeline content: before writing, it fetches the task page and records existing date headings under `Timeline log`. If the page has no usable `Timeline log` section with at least one date, the tracker initialises the body as `Timeline log`, today's date, then any existing body content underneath. New date sections are prepended under `Timeline log`; existing date headings receive new lines under the existing heading.
8. For normal paragraphs and code blocks, use `timeline_entry.blocks` instead of `timeline_entry.lines`. The tracker renders `lines` as bullet list items. Use paragraph blocks for prose and code blocks for commands, stack traces, structured output, tensor/input lists, shapes, mappings, and multi-line snippets. Put inline technical text in backticks inside paragraph text, for example `scp -O`, `/var/cache/qnn_sdk`, `allow_missing_cameras=False`, `QnnExec`, and `ValueError`. Prefer code blocks over inline text when the content is a full command, command output, traceback, or multi-line snippet. Use entries such as `{"type": "paragraph", "text": "The target failed to create `/var/cache/qnn_sdk/test_write`."}` and `{"type": "code", "language": "bash", "text": "ssh root@target '/mnt/bin/touch /var/cache/qnn_sdk/test_write'"}`. Do not put fenced Markdown inside `lines`.
9. Do not force numbering into timeline lines. The tracker renders `lines` as bullets. Use plain bullet-style sentences unless the user explicitly asks for ordered steps, and avoid Markdown ordered-list prefixes like `1.` or `2.` because Notion may reinterpret the formatting.

`notion_task log <number> sub:<subheading> [notes]` writes the new lines under a Notion toggle inside today's date entry. Put `<subheading>` in `timeline_entry.subheading`; do not fold it into the first log line.

`notion_task complete <number> [notes]` marks an existing task complete.

1. Resolve `<number>` to `ALOVYA-<number>`.
2. Fail if the task does not exist.
3. Summarise relevant current conversation context plus `[notes]` as concise completion lines.
4. Use today's date for `entry_date`.
5. Use a heading of `<mention-date start="YYYY-MM-DD"/>`.
6. Use `complete_task`.
7. The tracker owns completion behaviour: it sets status `Complete`, renders priority as `N/A` in derived views, applies completed-title styling, updates the ongoing and completed landing pages, and appends or merges the timeline entry by date.

`notion_task cancel <number> [notes]` marks an existing task cancelled.

1. Resolve `<number>` to `ALOVYA-<number>`.
2. Fail if the task does not exist.
3. Summarise relevant current conversation context plus `[notes]` as concise cancellation lines.
4. Use today's date for `entry_date`.
5. Use a heading of `<mention-date start="YYYY-MM-DD"/>`.
6. Use `cancel_task`.
7. The tracker owns cancellation behaviour: it sets status `Cancelled`, renders priority as `N/A` in derived views, updates the ongoing and completed landing pages, and appends or merges the timeline entry by date.

`notion_task new [pX] [title]` creates a top-level task.

1. Default priority is `P1`.
2. Default status is `Active`.
3. Use `[title]` when provided; ask for a title if the user did not provide one.
4. If the user asks to log, capture, file, or record a new problem, bug, investigation, incident, or context while creating the task, include that context in the same `create_top_level_task` command as `timeline_entry`. Do not create a bare task and then append the first log afterwards when the initial context is already available.
5. Summarise relevant current conversation context into concise initial timeline content. Use `timeline_entry.blocks` for paragraph prose and code blocks. Put inline technical text in backticks inside paragraph text. Use code blocks for full commands, command output, stack traces, paths grouped with outputs, structured observations, and multi-line snippets. Use `timeline_entry.lines` only when the user explicitly wants bullet-style notes.
6. Use today's date for `entry_date`.
7. Use a heading of `<mention-date start="YYYY-MM-DD"/>`.
8. Use `create_top_level_task`; Notion assigns `Ticket ID` and the tracker records the assigned task id.

`notion_task child <parent-number> [pX] [title]` creates a child task under an existing parent.

1. Resolve `<parent-number>` to `ALOVYA-<parent-number>`.
2. The parent must exist.
3. Default priority is `P1`.
4. Default status is `Active`.
5. Use `[title]` when provided; ask for a title if the user did not provide one.
6. Use `create_child_task`; Notion assigns `Ticket ID` and the tracker records the assigned task id.
7. The tracker initialises the child page Timeline log with today's date and a parent-page mention, then writes a parent Timeline log entry that links to the created child page.

`notion_task sibling <existing-number> [pX] [title]` creates a sibling task next to an existing task.

1. Resolve `<existing-number>` to `ALOVYA-<existing-number>`.
2. The existing task must exist.
3. Default priority is `P1`.
4. Default status is `Active`.
5. Use `[title]` when provided; ask for a title if the user did not provide one.
6. Use `create_sibling_task`; Notion assigns `Ticket ID` and the tracker records the assigned task id.
7. If the existing task has a parent, the new task gets the same parent. If the existing task is top-level, the new task is also top-level.
8. If the new sibling has a parent, the tracker initialises the new page Timeline log with a parent-page mention and writes a parent Timeline log entry that links to the new page.

Never silently create a task from `notion_task <number>`.

`notion_task misc [title] <user-notes>` appends to today's miscellaneous notes.

1. Summarise relevant current conversation context.
2. Combine that summary with `<user-notes>`.
3. Use today's date.
4. Use `append_miscellaneous_note`.

`notion_task synth [title] <source-1> <source-2> ... <user-notes>` creates a synthesis subpage.

1. Treat sources as Notion pages, task pages, miscellaneous pages, Google Docs, Slack threads, GitHub links, or URLs.
2. Fetch sources only enough to support synthesis.
3. Infer a concise title and stable `synthesis_key`.
4. Put source references in `sources`, short synthesis in `summary`, and reusable content in `lines`.
5. Use `create_synthesis_page`.

## Reconciliation Notes

When the user edited task database rows in Notion:

1. Run the user's command normally if it touches a known task; targeted preflight will refresh that task and its parent chain.
2. Treat broad database edits, missing local tasks, or missing related parent pages as `notion_task update`.
3. Continue with the user's requested command only after generated repair calls succeed.

When the user edited the synthesis root:

1. Fetch `Alovya's synthesis notes`.
2. Run `reconcile_synthesis_root_page_mentions`.
3. Fetch titles only for bare page mentions not already known in the tracker state.
4. Do not run `refresh_synthesis_pages` unless the user explicitly wants the root rewritten.

## Agent Boundary

The agent supplies only semantic input:

- requested command form;
- task title;
- priority when user supplied it, otherwise default `P1` for new tasks;
- timeline wording;
- miscellaneous note summary and lines;
- synthesis title, sources, summary, and content.

The task database owns ticket-number assignment and parent-child relations. The tracker owns graph projection, priority rollup, page structure, rendering, page mentions, colours, REST request ordering, page-id blockers, and tracker-state shape.

## Work Workflow

When working an existing task:

1. Use the task page for intent, status, blockers, links, and recent timeline.
2. If the graph lacks the task page id, run `notion_task update` from the task database source of truth.
3. If the task points to repo work, obey repo `AGENTS.md` and relevant decision records before editing code.
4. Put details on the most specific task page. Parent pages get compressed direct-child updates only when useful.

## Final Response

Report the task id worked or created, Notion pages created or updated, tracker-state path written, and any blockers.
