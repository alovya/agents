# Notion Task Tracker

This package turns small agent-written JSON commands into Notion writes. The agent supplies intent; the tracker owns graph projection, page shape, rendering, write ordering, and exact Notion REST requests. Task metadata now comes from `Alovya's task database`; task page bodies contain timeline logs only, and the ongoing and completed task landing pages are derived views.

Fixed page names live in `common.py`:

1. `Alovya's ongoing tasks landing page`
2. `Alovya's completed tasks landing page`
3. `Alovya's miscellanous notes`
4. `Alovya's synthesis notes`

Notion page ids live in tracker state because Notion assigns them. The task database source and saved-view URLs live in `tasks/pages/task_database.py`.

## Agent Workflow

1. Read the current tracker state, usually `~/.codex/memories/notion_tasks_graph.json`.
2. Write a command JSON file for the user intent.
3. Run the tracker CLI with `--command-path`.
4. The CLI fetches only task pages needed by that command, updates their local metadata projection, applies the command, writes to Notion, and saves tracker state after successful writes.
5. Read `command_result.json` for completed operation keys and warnings.
6. Treat a CLI failure as a failed write. Do not manually send Notion writes unless debugging with the user.

Run command JSON from the local virtual environment:

```bash
cd /home/alovyachowdhury/.codex/memories
/workspace/venv/bin/python -m notion_task_tracker \
  --command-path command.json \
  --tracker-state-path notion_tasks_graph.json \
  --output-path command_result.json
```

REST execution needs `NOTION_API_KEY` to contain the `ntn_` Notion integration token. MCP remains available as an explicit fallback with `--notion-transport mcp`.

`command_result.json` contains:

1. `backup_path`: tracker state backup from before the command.
2. `command_path`: command JSON that was run.
3. `completed_operations`: operation keys successfully written to Notion.
4. `tracker_state_path`: canonical tracker-state path written after Notion writes succeeded.
5. `warnings`: non-fatal reconciliation warnings.

The live path uses the Notion REST client by default. The MCP client remains in-tree as a temporary fallback; delete it once REST is reliable for task creation, logging, completion, reconciliation, and landing-page rendering.

## Fetch And Reconcile From Notion

Use this when the user edited task rows in the Notion UI:

```bash
PYTHONPATH=/home/alovyachowdhury/.codex/memories \
  /workspace/venv/bin/python -m notion_task_tracker --reconcile-from-notion
```

This command creates a timestamped backup under `/tmp`, queries the saved `Alovya's task database` view, rebuilds the local graph projection from row properties, and repairs derived landing pages or task titles when needed.

Ordinary commands do not query the full database view. They fetch the task pages they depend on, so command execution is not blocked by slow saved-view export. If a targeted fetch finds a parent page outside local tracker state, run the full update command before retrying.

### Targeted Preflight Footguns

Normal commands are fast because they only refresh the task pages they touch. They do not discover every remote database edit.

1. `append_task_timeline_log` and `complete_task` fetch the target task page, refresh that task's database properties in local state, fetch timeline headings, then write.
2. `create_child_task` fetches the parent task and parent chain, creates the child database row, updates the parent timeline, and refreshes derived landing pages.
3. `create_sibling_task` fetches the existing sibling and parent chain, creates the new database row beside it, updates the parent timeline when there is a parent, and refreshes derived landing pages.
4. `create_top_level_task` creates a new top-level database row without fetching the full database view.
5. Miscellaneous and synthesis commands do not use the task database view.
6. `--reconcile-from-notion` is the only normal path that pulls the saved task database view and rebuilds the whole local task graph projection.

Run full reconciliation when a task was created only in Notion UI and is missing locally, when broad unrelated database edits must be reflected locally, when a manually added child or sibling must appear in derived landing pages, or when targeted preflight reports a missing related parent page.

Targeted preflight intentionally fails instead of guessing when the touched page has malformed task properties, reports a different `Ticket ID` than the requested task, has more than one parent, or points to a parent page that is absent from local tracker state.

Task ids are derived from Notion's `Ticket ID`. The visible Notion page title stays as the human title and does not include the `ALOVYA-N` prefix.

## Task Commands

Append a timeline log. Timeline logs are user-owned in Notion and may contain handwritten edits, so this command must emit targeted Notion writes. It must never replace a whole task page or landing page just to add log lines once a timeline log exists. Before writing, the CLI fetches the target task page and records any existing date headings under `Timeline log`. If the page lacks a usable `Timeline log` section with at least one date heading, the CLI initialises the body as `Timeline log`, today's date, then any existing body content underneath. New date sections are prepended directly under `Timeline log`; existing date sections get new lines inserted under their date heading:

```json
{
  "command": "append_task_timeline_log",
  "task_id": "ALOVYA-5",
  "timeline_entry": {
    "entry_date": "2026-05-24",
    "heading": "<mention-date start=\"2026-05-24\"/>",
    "lines": ["Investigated the current blocker."]
  }
}
```

Add `subheading` to put the new log lines under a Notion toggle for that date:

```json
{
  "command": "append_task_timeline_log",
  "task_id": "ALOVYA-5",
  "timeline_entry": {
    "entry_date": "2026-05-24",
    "heading": "<mention-date start=\"2026-05-24\"/>",
    "subheading": "Design notes",
    "lines": ["Moved task metadata into the database."]
  }
}
```

Complete a task. The tracker marks the task `Complete`, appends or merges the timeline entry by `entry_date`, updates database properties, and refreshes the ongoing and completed landing pages:

```json
{
  "command": "complete_task",
  "task_id": "ALOVYA-5",
  "timeline_entry": {
    "entry_date": "2026-05-24",
    "heading": "<mention-date start=\"2026-05-24\"/>",
    "lines": ["Completed the task."]
  }
}
```

Create a top-level task. In database-backed mode, the tracker creates a database row, Notion assigns `Ticket ID`, and the tracker then records the assigned task id:

```json
{
  "command": "create_top_level_task",
  "task": {
    "title": "Measure activation mismatch after QNN export",
    "configured_priority": "P1",
    "status": "Active"
  },
  "timeline_entry": {
    "entry_date": "2026-05-24",
    "heading": "<mention-date start=\"2026-05-24\"/>",
    "lines": ["Started task: measure activation mismatch after QNN export."]
  }
}
```

Create a child task. The command does not include `task_id`; Notion assigns it. The new child page is created with a dated Timeline log entry that links back to the parent task. The parent task receives a dated Timeline log entry that links to the created child page:

```json
{
  "command": "create_child_task",
  "parent_task_id": "ALOVYA-5",
  "child_task": {
    "title": "Measure activation mismatch after QNN export",
    "configured_priority": "P1",
    "status": "Active"
  },
  "parent_timeline_entry": {
    "entry_date": "2026-05-24",
    "heading": "<mention-date start=\"2026-05-24\"/>",
    "lines": ["Spawned child task: measure activation mismatch after QNN export."]
  }
}
```

Record a page id returned by `notion-create-pages`. This is used by miscellaneous and synthesis page creation; task creation captures the created database row and assigned `Ticket ID` inside live command execution:

```json
{
  "command": "record_page_id",
  "local_page_key": "miscellaneous:2026-05-24",
  "notion_page_id": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
}
```

Refresh task views and task database properties:

```json
{
  "command": "refresh_task_pages",
  "operation_keys": ["update_properties:task:ALOVYA-5", "replace:landing_page"]
}
```

Omit `operation_keys` to update every known task title/property and both task landing pages. Task page body replacement is not part of current task refresh; task bodies are timeline logs.

The ongoing and completed landing pages are rendered task indexes. They are not the source of truth for task membership or hierarchy. The ongoing landing page starts entries only from incomplete top-level tasks, but still shows completed subtasks inside those trees. The completed landing page starts entries only from completed or cancelled top-level tasks.

## Miscellaneous Commands

Append context to a dated miscellaneous page:

```json
{
  "command": "append_miscellaneous_note",
  "note_date": "2026-05-24",
  "lines": ["Recent context to preserve before it becomes a task or synthesis page."]
}
```

Refresh miscellaneous pages:

```json
{
  "command": "refresh_miscellaneous_pages"
}
```

## Synthesis Commands

Create a synthesis page with explicit sources:

```json
{
  "command": "create_synthesis_page",
  "synthesis_key": "onnx_qdq_export",
  "title": "ONNX QDQ export behaviour",
  "summary": "Reusable notes on export behaviour.",
  "sources": [
    {
      "source_type": "Notion page",
      "label": "ALOVYA-2",
      "page_key": "task:ALOVYA-2"
    },
    {
      "source_type": "Google doc",
      "label": "Export notes",
      "external_url": "https://example.invalid/doc"
    }
  ],
  "lines": ["QDQ nodes preserve quantisation boundaries for export."]
}
```

Reconcile the synthesis root after editing page mentions in Notion:

```json
{
  "command": "reconcile_synthesis_root_page_mentions",
  "root_page_content": "<mention-page url=\"https://www.notion.so/wayve/Guide-aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa\">Guide</mention-page>",
  "page_titles_by_id": {
    "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb": "Title for a bare page mention"
  }
}
```

This replaces the local existing-page mention list with exactly the page mentions or child pages present on the fetched synthesis root. It emits no Notion write calls.

## Supported Commands

- `append_task_timeline_log`: add a dated timeline entry to one task with targeted page content. New dates are prepended under `Timeline log`; existing dates are updated under their date heading. It must not replace the task page or landing pages.
- `complete_task`: mark one task complete, append or merge a dated timeline entry, update database properties, and refresh the ongoing and completed landing pages.
- `create_top_level_task`: create a top-level task database row and use Notion's assigned `Ticket ID`.
- `create_child_task`: create a child task database row under an existing parent, initialise the child Timeline log with a parent link, and append a parent timeline entry linking to the child.
- `create_sibling_task`: create a task database row under the same parent as an existing task, or top-level when the existing task has no parent. If the sibling has a parent, initialise the new page with a parent link and append a parent timeline entry linking to the new page.
- `record_page_id`: record a page id returned by a page creation write.
- `refresh_task_pages`: update task database properties and the derived task landing pages.
- `append_miscellaneous_note`: add lines to a dated miscellaneous subpage.
- `refresh_miscellaneous_pages`: regenerate the miscellaneous root and dated pages.
- `create_synthesis_page`: create one synthesis subpage with sources and content.
- `reconcile_synthesis_root_page_mentions`: update local synthesis-root references from fetched Notion page mentions without writing to Notion.
- `refresh_synthesis_pages`: regenerate the synthesis root page and tracker-created synthesis pages.

## Package Shape

The package is Python metadata and Notion write execution code. Live fetch/write execution uses the authenticated Notion REST client by default. The MCP client is a temporary fallback while REST reliability is proven.

- `__main__.py`: CLI for command JSON and direct task database reconciliation.
- `commands.py`: command dispatcher from JSON to tracker-state updates and Notion writes.
- `tasks/workflow.py`: top-level task command and reconciliation workflow.
- `tasks/actions/`: task actions such as timeline logging, task creation, and dependency reconciliation.
- `tasks/pages/`: task database projection, task graph metadata, and rendering.
- `rest/`: Notion REST client and workflow transport.
- `mcp/`: temporary Notion MCP fallback client, call compiler, and workflow transport.
- `notion_client.py`: compatibility imports for the public task workflow.
- `miscellaneous_pages.py`: dated miscellaneous notes.
- `synthesis_pages.py`: flat synthesis root mentions and synthesis subpages with sources.
- `notion_enhanced_markdown.py`: renderer from internal blocks to Notion enhanced Markdown.
- `common.py`: shared page references, write intents, fixed page titles, and block helpers.

## Tests

```bash
cd /home/alovyachowdhury/.codex/memories
/workspace/venv/bin/python -m pytest notion_task_tracker
```
