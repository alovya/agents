"""Apply narrow JSON commands and produce tracker updates plus Notion writes."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from notion_task_tracker.common import (
    NotionPageRegistry,
    NotionPlanningError,
    NotionWriteIntent,
    write_json_snapshot,
)
from notion_task_tracker.miscellaneous_pages import MiscellaneousNotesMetadata
from notion_task_tracker.synthesis_pages import SynthesisNotesMetadata, SynthesisPageMetadata, SynthesisSource
from notion_task_tracker.tasks.pages import (
    TaskDependencyGraph,
    TimelineEntry,
)
from notion_task_tracker.tasks.pages.task_metadata import MENTION_DATE_START_PATTERN


@dataclass(frozen=True, init=False)
class CommandResult:
    """Tracker state candidate and exact Notion writes from one command."""

    tracker_state: dict[str, Any]
    write_intents: list[NotionWriteIntent]
    page_registry: NotionPageRegistry | None
    warnings: list[dict[str, str]] | None = None

    def __init__(
        self,
        tracker_state: dict[str, Any],
        write_intents: list[NotionWriteIntent] | None = None,
        page_registry: NotionPageRegistry | None = None,
        warnings: list[dict[str, str]] | None = None,
    ) -> None:
        object.__setattr__(self, "tracker_state", tracker_state)
        object.__setattr__(self, "write_intents", list(write_intents or []))
        object.__setattr__(self, "page_registry", page_registry)
        object.__setattr__(self, "warnings", warnings)

    @classmethod
    def from_json(cls, call: dict[str, Any]) -> "CommandResult":
        return cls(
            tracker_state=dict(call["tracker_state"]),
            write_intents=[],
            page_registry=None,
            warnings=list(call.get("warnings", [])),
        )

    def write_json(self, output_path: str | Path) -> None:
        write_json_snapshot(self.to_json(), output_path)

    def to_json(self) -> dict[str, Any]:
        return {
            "tracker_state": self.tracker_state,
            "warnings": list(self.warnings or []),
        }


def apply_command_files(
    command_path: str | Path,
    tracker_state_path: str | Path,
    output_path: str | Path,
) -> CommandResult:
    command = _read_json_file(command_path)
    tracker_state = _read_json_file(tracker_state_path)
    command_result = apply_command_to_tracker_state(command, tracker_state)
    command_result.write_json(output_path)
    return command_result


def apply_command_to_tracker_state(command: dict[str, Any], tracker_state: dict[str, Any]) -> CommandResult:
    command_name = command["command"]

    if command_name == "record_page_id":
        return _record_page_id_in_tracker_state(command, tracker_state)

    if command_name == "append_task_timeline_log":
        return _apply_task_command(command, tracker_state, _append_task_timeline_log)

    if command_name == "complete_task":
        return _apply_task_command(command, tracker_state, _complete_task)

    if command_name == "refresh_task_pages":
        return _refresh_task_pages(command, tracker_state)

    if command_name == "append_miscellaneous_note":
        return _apply_miscellaneous_command(command, tracker_state)

    if command_name == "refresh_miscellaneous_pages":
        return _refresh_miscellaneous_pages(command, tracker_state)

    if command_name == "create_synthesis_page":
        return _apply_synthesis_command(command, tracker_state)

    if command_name == "reconcile_synthesis_root_page_mentions":
        return _reconcile_synthesis_root_page_mentions(command, tracker_state)

    if command_name == "refresh_synthesis_pages":
        return _refresh_synthesis_pages(command, tracker_state)

    raise NotionPlanningError(f"Unsupported command {command_name!r}")


def _record_page_id_in_tracker_state(command: dict[str, Any], tracker_state: dict[str, Any]) -> CommandResult:
    updated_tracker_state = json.loads(json.dumps(tracker_state))
    local_page_key = command["local_page_key"]
    notion_page_id = command["notion_page_id"]

    if local_page_key == "landing_page":
        updated_tracker_state["landing_page"]["notion_page_id"] = notion_page_id
        return CommandResult(tracker_state=updated_tracker_state)

    if local_page_key == "completed_landing_page":
        updated_tracker_state["completed_landing_page"]["notion_page_id"] = notion_page_id
        return CommandResult(tracker_state=updated_tracker_state)

    if local_page_key == "miscellaneous_notes":
        _record_miscellaneous_notes_page_id(updated_tracker_state, notion_page_id)
        return CommandResult(tracker_state=updated_tracker_state)

    if local_page_key.startswith("miscellaneous:"):
        note_date = local_page_key.removeprefix("miscellaneous:")
        _record_miscellaneous_dated_page_id(updated_tracker_state, note_date, notion_page_id)
        return CommandResult(tracker_state=updated_tracker_state)

    if local_page_key == "synthesis_notes":
        _record_synthesis_notes_page_id(updated_tracker_state, notion_page_id)
        return CommandResult(tracker_state=updated_tracker_state)

    if local_page_key.startswith("synthesis:"):
        synthesis_key = local_page_key.removeprefix("synthesis:")
        _record_synthesis_page_id(updated_tracker_state, synthesis_key, notion_page_id)
        return CommandResult(tracker_state=updated_tracker_state)

    raise NotionPlanningError(f"Cannot record page id for unknown local page key {local_page_key!r}")


def _apply_task_command(
    command: dict[str, Any],
    tracker_state: dict[str, Any],
    command_handler,
) -> CommandResult:
    work_graph = TaskDependencyGraph.from_snapshot(tracker_state)
    write_intents = _write_intents_from_task_command(command_handler(work_graph, command))
    page_registry = work_graph.page_registry()
    return CommandResult(
        tracker_state=_replace_task_pages_in_tracker_state(tracker_state, work_graph),
        write_intents=write_intents,
        page_registry=page_registry,
    )


def _write_intents_from_task_command(command_result) -> list:
    if isinstance(command_result, list):
        return command_result

    return [command_result]


def _append_task_timeline_log(
    work_graph: TaskDependencyGraph,
    command: dict[str, Any],
):
    return work_graph.append_task_timeline_log(
        task_id=command["task_id"],
        timeline_entry=_timeline_entry_from_command(command["timeline_entry"]),
    )


def _complete_task(
    work_graph: TaskDependencyGraph,
    command: dict[str, Any],
):
    return work_graph.complete_task(
        task_id=command["task_id"],
        timeline_entry=_timeline_entry_from_command(command["timeline_entry"]),
    )


def _refresh_task_pages(command: dict[str, Any], tracker_state: dict[str, Any]) -> CommandResult:
    work_graph = TaskDependencyGraph.from_snapshot(tracker_state)
    write_intents = _filter_write_intents(work_graph.build_notion_write_plan(), command.get("operation_keys"))
    page_registry = work_graph.page_registry()
    return CommandResult(
        tracker_state=_replace_task_pages_in_tracker_state(tracker_state, work_graph),
        write_intents=write_intents,
        page_registry=page_registry,
    )


def _apply_miscellaneous_command(command: dict[str, Any], tracker_state: dict[str, Any]) -> CommandResult:
    miscellaneous_notes = MiscellaneousNotesMetadata.from_snapshot(tracker_state["miscellaneous_notes"])
    write_intent = miscellaneous_notes.append_to_dated_page(
        note_date=command["note_date"],
        lines=list(command["lines"]),
        source_page_id=command.get("source_page_id"),
        source_block_id=command.get("source_block_id"),
    )
    page_registry = miscellaneous_notes.page_registry()
    return CommandResult(
        tracker_state=_replace_miscellaneous_notes_in_tracker_state(tracker_state, miscellaneous_notes),
        write_intents=[write_intent],
        page_registry=page_registry,
    )


def _refresh_miscellaneous_pages(command: dict[str, Any], tracker_state: dict[str, Any]) -> CommandResult:
    miscellaneous_notes = MiscellaneousNotesMetadata.from_snapshot(tracker_state["miscellaneous_notes"])
    write_intents = _filter_write_intents(
        miscellaneous_notes.build_notion_write_plan(),
        command.get("operation_keys"),
    )
    page_registry = miscellaneous_notes.page_registry()
    return CommandResult(
        tracker_state=_replace_miscellaneous_notes_in_tracker_state(tracker_state, miscellaneous_notes),
        write_intents=write_intents,
        page_registry=page_registry,
    )


def _apply_synthesis_command(command: dict[str, Any], tracker_state: dict[str, Any]) -> CommandResult:
    synthesis_notes = SynthesisNotesMetadata.from_snapshot(tracker_state["synthesis_notes"])
    write_intent = synthesis_notes.create_synthesis_page(
        SynthesisPageMetadata(
            synthesis_key=command["synthesis_key"],
            title=command["title"],
            summary=command.get("summary", ""),
            lines=list(command.get("lines", [])),
            sources=[
                _synthesis_source_from_command(source_command)
                for source_command in command.get("sources", [])
            ],
        )
    )
    page_registry = _page_registry_for_synthesis_command(tracker_state, synthesis_notes)
    return CommandResult(
        tracker_state=_replace_synthesis_notes_in_tracker_state(tracker_state, synthesis_notes),
        write_intents=[write_intent],
        page_registry=page_registry,
    )


def _reconcile_synthesis_root_page_mentions(command: dict[str, Any], tracker_state: dict[str, Any]) -> CommandResult:
    synthesis_notes = SynthesisNotesMetadata.from_snapshot(tracker_state["synthesis_notes"])
    synthesis_notes.reconcile_root_page_mentions_from_content(
        root_page_content=command["root_page_content"],
        page_titles_by_id=command.get("page_titles_by_id", {}),
    )
    return CommandResult(
        tracker_state=_replace_synthesis_notes_in_tracker_state(tracker_state, synthesis_notes),
    )


def _refresh_synthesis_pages(command: dict[str, Any], tracker_state: dict[str, Any]) -> CommandResult:
    synthesis_notes = SynthesisNotesMetadata.from_snapshot(tracker_state["synthesis_notes"])
    write_intents = _filter_write_intents(
        synthesis_notes.build_notion_write_plan(),
        command.get("operation_keys"),
    )
    page_registry = _page_registry_for_synthesis_command(tracker_state, synthesis_notes)
    return CommandResult(
        tracker_state=_replace_synthesis_notes_in_tracker_state(tracker_state, synthesis_notes),
        write_intents=write_intents,
        page_registry=page_registry,
    )


def _record_miscellaneous_notes_page_id(tracker_state: dict[str, Any], notion_page_id: str) -> None:
    tracker_state["miscellaneous_notes"]["page"]["notion_page_id"] = notion_page_id


def _record_miscellaneous_dated_page_id(
    tracker_state: dict[str, Any],
    note_date: str,
    notion_page_id: str,
) -> None:
    tracker_state["miscellaneous_notes"]["dated_pages"][note_date]["notion_page_id"] = notion_page_id


def _record_synthesis_notes_page_id(tracker_state: dict[str, Any], notion_page_id: str) -> None:
    tracker_state["synthesis_notes"]["page"]["notion_page_id"] = notion_page_id


def _record_synthesis_page_id(
    tracker_state: dict[str, Any],
    synthesis_key: str,
    notion_page_id: str,
) -> None:
    tracker_state["synthesis_notes"]["pages"][synthesis_key]["notion_page_id"] = notion_page_id


def _replace_task_pages_in_tracker_state(tracker_state: dict[str, Any], work_graph: TaskDependencyGraph) -> dict[str, Any]:
    updated_tracker_state = json.loads(json.dumps(tracker_state))
    task_state = work_graph.to_snapshot()
    updated_tracker_state["landing_page"] = task_state["landing_page"]
    updated_tracker_state["completed_landing_page"] = task_state["completed_landing_page"]
    updated_tracker_state["tasks"] = task_state["tasks"]
    return updated_tracker_state


def _replace_miscellaneous_notes_in_tracker_state(
    tracker_state: dict[str, Any],
    miscellaneous_notes: MiscellaneousNotesMetadata,
) -> dict[str, Any]:
    updated_tracker_state = json.loads(json.dumps(tracker_state))
    updated_tracker_state["miscellaneous_notes"] = miscellaneous_notes.to_snapshot()
    return updated_tracker_state


def _replace_synthesis_notes_in_tracker_state(
    tracker_state: dict[str, Any],
    synthesis_notes: SynthesisNotesMetadata,
) -> dict[str, Any]:
    updated_tracker_state = json.loads(json.dumps(tracker_state))
    updated_tracker_state["synthesis_notes"] = synthesis_notes.to_snapshot()
    return updated_tracker_state


def _page_registry_for_synthesis_command(
    tracker_state: dict[str, Any],
    synthesis_notes: SynthesisNotesMetadata,
) -> NotionPageRegistry:
    return _merge_page_registries(
        TaskDependencyGraph.from_snapshot(tracker_state).page_registry(),
        MiscellaneousNotesMetadata.from_snapshot(tracker_state["miscellaneous_notes"]).page_registry(),
        synthesis_notes.page_registry(),
    )


def _merge_page_registries(*page_registries: NotionPageRegistry) -> NotionPageRegistry:
    pages = {}

    for page_registry in page_registries:
        pages.update(page_registry.pages)

    return NotionPageRegistry(pages=pages)


def _filter_write_intents(
    write_intents,
    operation_keys: list[str] | None,
):
    if operation_keys is None:
        return write_intents

    operation_key_set = set(operation_keys)
    return [
        write_intent
        for write_intent in write_intents
        if write_intent.operation_key in operation_key_set
    ]


def _timeline_entry_from_command(command: dict[str, Any]) -> TimelineEntry:
    entry_date = command["entry_date"]
    return TimelineEntry(
        entry_date=entry_date,
        heading=_date_only_timeline_heading(command.get("heading", ""), entry_date),
        lines=list(command.get("lines", [])),
        blocks=list(command.get("blocks", [])),
        subheading=command.get("subheading"),
    )


def _date_only_timeline_heading(raw_heading: str, entry_date: str) -> str:
    date_match = MENTION_DATE_START_PATTERN.search(raw_heading)
    if date_match is not None:
        return f'<mention-date start="{date_match.group(1)}"/>'

    return f'<mention-date start="{entry_date}"/>'


def _synthesis_source_from_command(command: dict[str, Any]) -> SynthesisSource:
    return SynthesisSource(
        source_type=command["source_type"],
        label=command["label"],
        page_key=command.get("page_key"),
        external_url=command.get("external_url"),
    )


def _read_json_file(path: str | Path) -> dict[str, Any]:
    source_path = Path(path)
    return json.loads(source_path.read_text(encoding="utf-8"))
