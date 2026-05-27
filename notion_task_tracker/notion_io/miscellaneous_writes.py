"""Plan Notion writes for miscellaneous notes."""

from __future__ import annotations

from notion_task_tracker.miscellaneous_pages import (
    MiscellaneousNoteEntry,
    MiscellaneousNotesMetadata,
    MiscellaneousNotesPageMetadata,
)
from notion_task_tracker.notion_io.markdown import bullet, join_markdown_blocks, page_mention
from notion_task_tracker.notion_io.page_registry import NotionPageRegistry
from notion_task_tracker.notion_io.writes import NotionWriteIntent
from notion_task_tracker.tracked_pages import TrackedPage, tracked_page_to_tracker_state


def page_registry_for_miscellaneous_notes(
    miscellaneous_notes: MiscellaneousNotesMetadata,
) -> NotionPageRegistry:
    return NotionPageRegistry.from_tracked_pages(_pages_that_should_exist(miscellaneous_notes))


def miscellaneous_note_append_write_intent(
    miscellaneous_notes: MiscellaneousNotesMetadata,
    dated_page: MiscellaneousNotesPageMetadata,
    note_entry: MiscellaneousNoteEntry,
) -> NotionWriteIntent:
    return NotionWriteIntent(
        operation_key=f"append_miscellaneous_context:{dated_page.local_page_key}",
        operation_name="append_miscellaneous_context",
        target_page_key=dated_page.local_page_key,
        arguments={
            "root_page_key": miscellaneous_notes.page.local_page_key,
            "dated_page": tracked_page_to_tracker_state(_miscellaneous_notes_page_pointer(miscellaneous_notes, dated_page)),
            "markdown": render_miscellaneous_note_entry_markdown(note_entry),
            "root_page_markdown": render_miscellaneous_root_page_markdown(miscellaneous_notes),
            "dated_page_markdown": render_miscellaneous_notes_page_markdown(dated_page),
        },
    )


def notion_write_plan_for_miscellaneous_notes(
    miscellaneous_notes: MiscellaneousNotesMetadata,
) -> list[NotionWriteIntent]:
    miscellaneous_notes.validate()
    return [
        *_missing_page_creation_intents(miscellaneous_notes),
        _root_page_refresh_intent(miscellaneous_notes),
        *_dated_page_refresh_intents(miscellaneous_notes),
    ]


def render_miscellaneous_root_page_markdown(miscellaneous_notes: MiscellaneousNotesMetadata) -> str:
    if not miscellaneous_notes.dated_pages:
        return "No miscellaneous notes yet."

    page_registry = page_registry_for_miscellaneous_notes(miscellaneous_notes)
    return join_markdown_blocks([
        bullet(_dated_page_reference(dated_page, page_registry))
        for dated_page in sorted(miscellaneous_notes.dated_pages.values(), key=lambda page: page.note_date, reverse=True)
    ])


def render_miscellaneous_notes_page_markdown(
    dated_page: MiscellaneousNotesPageMetadata,
) -> str:
    if not dated_page.entries:
        return "No notes yet."

    return join_markdown_blocks([
        render_miscellaneous_note_entry_markdown(note_entry)
        for note_entry in dated_page.entries
    ])


def render_miscellaneous_note_entry_markdown(note_entry: MiscellaneousNoteEntry) -> str:
    return join_markdown_blocks([
        bullet(line)
        for line in note_entry.lines
    ])


def _missing_page_creation_intents(miscellaneous_notes: MiscellaneousNotesMetadata) -> list[NotionWriteIntent]:
    return [
        NotionWriteIntent(
            operation_key=f"create:{page.local_page_key}",
            operation_name="create_page",
            target_page_key=None,
            arguments={
                "local_page_key": page.local_page_key,
                "title": page.title,
                "parent_page_key": page.parent_page_key,
                "markdown": _page_creation_markdown(miscellaneous_notes, page.local_page_key),
            },
        )
        for page in _pages_that_should_exist(miscellaneous_notes)
        if page.notion_page_id is None
    ]


def _root_page_refresh_intent(miscellaneous_notes: MiscellaneousNotesMetadata) -> NotionWriteIntent:
    return NotionWriteIntent(
        operation_key="replace:miscellaneous_notes",
        operation_name="replace_page_markdown",
        target_page_key=miscellaneous_notes.page.local_page_key,
        arguments={"markdown": render_miscellaneous_root_page_markdown(miscellaneous_notes)},
    )


def _dated_page_refresh_intents(miscellaneous_notes: MiscellaneousNotesMetadata) -> list[NotionWriteIntent]:
    return [
        NotionWriteIntent(
            operation_key=f"replace:{dated_page.local_page_key}",
            operation_name="replace_page_markdown",
            target_page_key=dated_page.local_page_key,
            arguments={"markdown": render_miscellaneous_notes_page_markdown(dated_page)},
        )
        for dated_page in sorted(miscellaneous_notes.dated_pages.values(), key=lambda page: page.note_date, reverse=True)
    ]


def _pages_that_should_exist(miscellaneous_notes: MiscellaneousNotesMetadata) -> list[TrackedPage]:
    return [
        miscellaneous_notes.page,
        *[
            _miscellaneous_notes_page_pointer(miscellaneous_notes, dated_page)
            for dated_page in miscellaneous_notes.dated_pages.values()
        ],
    ]


def _miscellaneous_notes_page_pointer(
    miscellaneous_notes: MiscellaneousNotesMetadata,
    dated_page: MiscellaneousNotesPageMetadata,
) -> TrackedPage:
    return TrackedPage(
        local_page_key=dated_page.local_page_key,
        title=dated_page.title,
        notion_page_id=dated_page.notion_page_id,
        parent_page_key=miscellaneous_notes.page.local_page_key,
    )


def _dated_page_reference(
    dated_page: MiscellaneousNotesPageMetadata,
    page_registry: NotionPageRegistry,
) -> str:
    if dated_page.notion_page_id is None:
        return dated_page.title

    return page_mention(dated_page.local_page_key, page_registry)


def _page_creation_markdown(miscellaneous_notes: MiscellaneousNotesMetadata, local_page_key: str) -> str:
    if local_page_key == miscellaneous_notes.page.local_page_key:
        return render_miscellaneous_root_page_markdown(miscellaneous_notes)

    note_date = local_page_key.removeprefix("miscellaneous:")
    return render_miscellaneous_notes_page_markdown(miscellaneous_notes.dated_pages[note_date])
