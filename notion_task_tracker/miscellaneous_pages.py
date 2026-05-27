"""Miscellaneous notes metadata and dated subpages."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from notion_task_tracker.fixed_pages import (
    MISCELLANEOUS_NOTES_PAGE_LOCAL_KEY,
    MISCELLANEOUS_NOTES_PAGE_TITLE,
)
from notion_task_tracker.tracked_pages import (
    TrackedPage,
    fixed_tracked_page_from_tracker_state,
    tracked_page_to_tracker_state,
    validate_fixed_tracked_page,
)


@dataclass
class MiscellaneousNoteEntry:
    """Captured note that has no task home yet."""

    note_date: str
    lines: list[str] = field(default_factory=list)
    source_page_id: str | None = None
    source_block_id: str | None = None


@dataclass
class MiscellaneousNotesPageMetadata:
    """One dated Miscellaneous notes subpage."""

    note_date: str
    entries: list[MiscellaneousNoteEntry] = field(default_factory=list)
    notion_page_id: str | None = None

    @property
    def local_page_key(self) -> str:
        return f"miscellaneous:{self.note_date}"

    @property
    def title(self) -> str:
        return self.note_date


@dataclass
class MiscellaneousNotesMetadata:
    """Root page and dated subpages for unresolved capture."""

    page: TrackedPage = field(
        default_factory=lambda: TrackedPage(
            local_page_key=MISCELLANEOUS_NOTES_PAGE_LOCAL_KEY,
            title=MISCELLANEOUS_NOTES_PAGE_TITLE,
        )
    )
    dated_pages: dict[str, MiscellaneousNotesPageMetadata] = field(default_factory=dict)

    @classmethod
    def from_tracker_state(cls, tracker_state: dict[str, Any]) -> MiscellaneousNotesMetadata:
        miscellaneous_notes = cls(
            page=fixed_tracked_page_from_tracker_state(
                tracker_state=tracker_state["page"],
                local_page_key=MISCELLANEOUS_NOTES_PAGE_LOCAL_KEY,
                title=MISCELLANEOUS_NOTES_PAGE_TITLE,
            ),
        )
        miscellaneous_notes.dated_pages = {
            note_date: _miscellaneous_notes_page_from_tracker_state(page_state)
            for note_date, page_state in tracker_state.get("dated_pages", {}).items()
        }
        miscellaneous_notes.validate()
        return miscellaneous_notes

    def append_to_dated_page(
        self,
        note_date: str,
        lines: list[str],
        source_page_id: str | None = None,
        source_block_id: str | None = None,
    ) -> tuple[MiscellaneousNotesPageMetadata, MiscellaneousNoteEntry]:
        dated_page = self.dated_pages.setdefault(
            note_date,
            MiscellaneousNotesPageMetadata(note_date=note_date),
        )
        note_entry = MiscellaneousNoteEntry(
            note_date=note_date,
            lines=lines,
            source_page_id=source_page_id,
            source_block_id=source_block_id,
        )
        dated_page.entries.append(note_entry)
        return dated_page, note_entry

    def validate(self) -> None:
        validate_fixed_tracked_page(
            page=self.page,
            expected_local_page_key=MISCELLANEOUS_NOTES_PAGE_LOCAL_KEY,
            expected_title=MISCELLANEOUS_NOTES_PAGE_TITLE,
        )
        self._validate_page_keys_match_page_values()

    def to_tracker_state(self) -> dict[str, Any]:
        return {
            "page": tracked_page_to_tracker_state(self.page),
            "dated_pages": {
                note_date: _miscellaneous_notes_page_to_tracker_state(dated_page)
                for note_date, dated_page in sorted(self.dated_pages.items())
            },
        }

    def _validate_page_keys_match_page_values(self) -> None:
        for note_date, dated_page in self.dated_pages.items():
            if note_date != dated_page.note_date:
                raise ValueError(
                    f"Miscellaneous page dictionary key {note_date!r} "
                    f"does not match page {dated_page.note_date!r}"
                )


def _miscellaneous_notes_page_to_tracker_state(
    dated_page: MiscellaneousNotesPageMetadata,
) -> dict[str, Any]:
    return {
        "note_date": dated_page.note_date,
        "entries": [
            _miscellaneous_note_entry_to_tracker_state(note_entry)
            for note_entry in dated_page.entries
        ],
        "notion_page_id": dated_page.notion_page_id,
    }


def _miscellaneous_note_entry_to_tracker_state(note_entry: MiscellaneousNoteEntry) -> dict[str, Any]:
    return {
        "note_date": note_entry.note_date,
        "lines": list(note_entry.lines),
        "source_page_id": note_entry.source_page_id,
        "source_block_id": note_entry.source_block_id,
    }


def _miscellaneous_notes_page_from_tracker_state(tracker_state: dict[str, Any]) -> MiscellaneousNotesPageMetadata:
    return MiscellaneousNotesPageMetadata(
        note_date=tracker_state["note_date"],
        entries=[
            _miscellaneous_note_entry_from_tracker_state(note_state)
            for note_state in tracker_state.get("entries", [])
        ],
        notion_page_id=tracker_state.get("notion_page_id"),
    )


def _miscellaneous_note_entry_from_tracker_state(tracker_state: dict[str, Any]) -> MiscellaneousNoteEntry:
    return MiscellaneousNoteEntry(
        note_date=tracker_state["note_date"],
        lines=list(tracker_state.get("lines", [])),
        source_page_id=tracker_state.get("source_page_id"),
        source_block_id=tracker_state.get("source_block_id"),
    )
