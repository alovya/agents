"""Miscellaneous notes metadata and dated subpage planning."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from notion_task_tracker.notion_pages import (
    MISCELLANEOUS_NOTES_PAGE_LOCAL_KEY,
    MISCELLANEOUS_NOTES_PAGE_TITLE,
    NotionPageRegistry,
    NotionWriteIntent,
    PagePointer,
    fixed_page_pointer_from_snapshot,
    page_pointer_to_snapshot,
    paragraph_block,
    validate_fixed_page_pointer,
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

    page: PagePointer = field(
        default_factory=lambda: PagePointer(
            local_page_key=MISCELLANEOUS_NOTES_PAGE_LOCAL_KEY,
            title=MISCELLANEOUS_NOTES_PAGE_TITLE,
        )
    )
    dated_pages: dict[str, MiscellaneousNotesPageMetadata] = field(default_factory=dict)

    @classmethod
    def from_snapshot(cls, snapshot: dict[str, Any]) -> MiscellaneousNotesMetadata:
        miscellaneous_notes = cls(
            page=fixed_page_pointer_from_snapshot(
                snapshot=snapshot["page"],
                local_page_key=MISCELLANEOUS_NOTES_PAGE_LOCAL_KEY,
                title=MISCELLANEOUS_NOTES_PAGE_TITLE,
            ),
        )
        miscellaneous_notes.dated_pages = {
            note_date: _miscellaneous_notes_page_from_snapshot(page_snapshot)
            for note_date, page_snapshot in snapshot.get("dated_pages", {}).items()
        }
        miscellaneous_notes.validate()
        return miscellaneous_notes

    def append_to_dated_page(
        self,
        note_date: str,
        lines: list[str],
        source_page_id: str | None = None,
        source_block_id: str | None = None,
    ) -> NotionWriteIntent:
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
        return self._plan_dated_page_append(dated_page, note_entry)

    def build_notion_write_plan(self) -> list[NotionWriteIntent]:
        self.validate()

        write_intents = []
        write_intents.extend(self._plan_missing_page_creation())
        write_intents.append(self._plan_root_page_refresh())
        write_intents.extend(self._plan_dated_page_refreshes())
        return write_intents

    def validate(self) -> None:
        validate_fixed_page_pointer(
            page=self.page,
            expected_local_page_key=MISCELLANEOUS_NOTES_PAGE_LOCAL_KEY,
            expected_title=MISCELLANEOUS_NOTES_PAGE_TITLE,
        )
        self._validate_page_keys_match_page_values()

    def page_registry(self) -> NotionPageRegistry:
        self.validate()
        return NotionPageRegistry.from_page_pointers(self._pages_that_should_exist())

    def to_snapshot(self) -> dict[str, Any]:
        return {
            "page": page_pointer_to_snapshot(self.page),
            "dated_pages": {
                note_date: _miscellaneous_notes_page_to_snapshot(dated_page)
                for note_date, dated_page in sorted(self.dated_pages.items())
            },
        }

    def _plan_dated_page_append(
        self,
        dated_page: MiscellaneousNotesPageMetadata,
        note_entry: MiscellaneousNoteEntry,
    ) -> NotionWriteIntent:
        return NotionWriteIntent(
            operation_key=f"append_miscellaneous_context:{dated_page.local_page_key}",
            operation_name="append_miscellaneous_context",
            target_page_key=dated_page.local_page_key,
            arguments={
                "root_page_key": self.page.local_page_key,
                "dated_page": _miscellaneous_notes_page_pointer_to_snapshot(self.page, dated_page),
                "blocks": _render_miscellaneous_note_entry_blocks(note_entry),
                "root_page_blocks": self._render_root_page_blocks(),
                "dated_page_blocks": _render_miscellaneous_notes_page_blocks(dated_page),
            },
        )

    def _plan_missing_page_creation(self) -> list[NotionWriteIntent]:
        write_intents = []

        for page in self._pages_that_should_exist():
            if page.notion_page_id is None:
                write_intents.append(
                    NotionWriteIntent(
                        operation_key=f"create:{page.local_page_key}",
                        operation_name="create_page",
                        target_page_key=None,
                        arguments={
                            "local_page_key": page.local_page_key,
                            "title": page.title,
                            "parent_page_key": page.parent_page_key,
                            "blocks": self._page_creation_blocks(page.local_page_key),
                        },
                    )
                )

        return write_intents

    def _plan_root_page_refresh(self) -> NotionWriteIntent:
        return NotionWriteIntent(
            operation_key="replace:miscellaneous_notes",
            operation_name="replace_page_children",
            target_page_key=self.page.local_page_key,
            arguments={
                "blocks": self._render_root_page_blocks(),
            },
        )

    def _plan_dated_page_refreshes(self) -> list[NotionWriteIntent]:
        return [
            NotionWriteIntent(
                operation_key=f"replace:{dated_page.local_page_key}",
                operation_name="replace_page_children",
                target_page_key=dated_page.local_page_key,
                arguments={
                    "blocks": _render_miscellaneous_notes_page_blocks(dated_page),
                },
            )
            for dated_page in sorted(self.dated_pages.values(), key=lambda page: page.note_date, reverse=True)
        ]

    def _pages_that_should_exist(self) -> list[PagePointer]:
        pages = [self.page]

        for dated_page in self.dated_pages.values():
            pages.append(_miscellaneous_notes_page_pointer(self.page, dated_page))

        return pages

    def _render_root_page_blocks(self) -> list[dict[str, Any]]:
        if not self.dated_pages:
            return [paragraph_block(text="No miscellaneous notes yet.")]

        return [
            {
                "type": "bulleted_list_item",
                "depth": 0,
                "text": dated_page.title,
                "page_key": dated_page.local_page_key,
            }
            for dated_page in sorted(self.dated_pages.values(), key=lambda page: page.note_date, reverse=True)
        ]

    def _page_creation_blocks(self, local_page_key: str) -> list[dict[str, Any]]:
        if local_page_key == self.page.local_page_key:
            return self._render_root_page_blocks()

        note_date = local_page_key.removeprefix("miscellaneous:")
        return _render_miscellaneous_notes_page_blocks(self.dated_pages[note_date])

    def _validate_page_keys_match_page_values(self) -> None:
        for note_date, dated_page in self.dated_pages.items():
            if note_date != dated_page.note_date:
                raise ValueError(
                    f"Miscellaneous page dictionary key {note_date!r} "
                    f"does not match page {dated_page.note_date!r}"
                )


def _miscellaneous_notes_page_pointer(
    root_page: PagePointer,
    dated_page: MiscellaneousNotesPageMetadata,
) -> PagePointer:
    return PagePointer(
        local_page_key=dated_page.local_page_key,
        title=dated_page.title,
        notion_page_id=dated_page.notion_page_id,
        parent_page_key=root_page.local_page_key,
    )


def _miscellaneous_notes_page_pointer_to_snapshot(
    root_page: PagePointer,
    dated_page: MiscellaneousNotesPageMetadata,
) -> dict[str, Any]:
    return page_pointer_to_snapshot(_miscellaneous_notes_page_pointer(root_page, dated_page))


def _render_miscellaneous_notes_page_blocks(
    dated_page: MiscellaneousNotesPageMetadata,
) -> list[dict[str, Any]]:
    if not dated_page.entries:
        return [paragraph_block(text="No notes yet.")]

    blocks = []

    for note_entry in dated_page.entries:
        blocks.extend(_render_miscellaneous_note_entry_blocks(note_entry))

    return blocks


def _render_miscellaneous_note_entry_blocks(note_entry: MiscellaneousNoteEntry) -> list[dict[str, Any]]:
    return [
        {
            "type": "bulleted_list_item",
            "depth": 0,
            "text": line,
            "source_page_id": note_entry.source_page_id,
            "source_block_id": note_entry.source_block_id,
        }
        for line in note_entry.lines
    ]


def _miscellaneous_notes_page_to_snapshot(
    dated_page: MiscellaneousNotesPageMetadata,
) -> dict[str, Any]:
    return {
        "note_date": dated_page.note_date,
        "entries": [
            _miscellaneous_note_entry_to_snapshot(note_entry)
            for note_entry in dated_page.entries
        ],
        "notion_page_id": dated_page.notion_page_id,
    }


def _miscellaneous_note_entry_to_snapshot(note_entry: MiscellaneousNoteEntry) -> dict[str, Any]:
    return {
        "note_date": note_entry.note_date,
        "lines": list(note_entry.lines),
        "source_page_id": note_entry.source_page_id,
        "source_block_id": note_entry.source_block_id,
    }


def _miscellaneous_notes_page_from_snapshot(snapshot: dict[str, Any]) -> MiscellaneousNotesPageMetadata:
    return MiscellaneousNotesPageMetadata(
        note_date=snapshot["note_date"],
        entries=[
            _miscellaneous_note_entry_from_snapshot(note_snapshot)
            for note_snapshot in snapshot.get("entries", [])
        ],
        notion_page_id=snapshot.get("notion_page_id"),
    )


def _miscellaneous_note_entry_from_snapshot(snapshot: dict[str, Any]) -> MiscellaneousNoteEntry:
    return MiscellaneousNoteEntry(
        note_date=snapshot["note_date"],
        lines=list(snapshot.get("lines", [])),
        source_page_id=snapshot.get("source_page_id"),
        source_block_id=snapshot.get("source_block_id"),
    )
