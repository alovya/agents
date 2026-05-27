from notion_task_tracker.miscellaneous_pages import MiscellaneousNotesMetadata
from notion_task_tracker.notion_io.miscellaneous_writes import (
    miscellaneous_note_append_write_intent,
    notion_write_plan_for_miscellaneous_notes,
)


class TestMiscellaneousNotesMetadataAppendToDatedPage:
    def test_appends_context_to_one_dated_subpage(self):
        miscellaneous_notes = MiscellaneousNotesMetadata()

        dated_page, note_entry = miscellaneous_notes.append_to_dated_page(
            note_date="2026-05-24",
            lines=["Random thought not yet tied to a task."],
            source_page_id="source-page",
            source_block_id="source-block",
        )
        write_intent = miscellaneous_note_append_write_intent(miscellaneous_notes, dated_page, note_entry)

        assert list(miscellaneous_notes.dated_pages) == ["2026-05-24"]
        assert miscellaneous_notes.dated_pages["2026-05-24"].entries[0].lines == [
            "Random thought not yet tied to a task."
        ]
        assert write_intent.operation_name == "append_miscellaneous_context"
        assert write_intent.target_page_key == "miscellaneous:2026-05-24"
        assert write_intent.arguments["root_page_key"] == "miscellaneous_notes"
        assert write_intent.arguments["dated_page"]["parent_page_key"] == "miscellaneous_notes"
        assert write_intent.arguments["markdown"] == "- Random thought not yet tied to a task."


class TestMiscellaneousNotesMetadataBuildNotionWritePlan:
    def test_creates_root_page_and_dated_subpages_without_touching_tasks(self):
        miscellaneous_notes = MiscellaneousNotesMetadata()
        miscellaneous_notes.append_to_dated_page(
            note_date="2026-05-24",
            lines=["Meeting fragment that may become work later."],
        )

        write_intents = notion_write_plan_for_miscellaneous_notes(miscellaneous_notes)

        create_page_keys = {
            write_intent.arguments["local_page_key"]
            for write_intent in write_intents
            if write_intent.operation_name == "create_page"
        }
        root_refresh_intent = next(
            write_intent
            for write_intent in write_intents
            if write_intent.operation_key == "replace:miscellaneous_notes"
        )
        dated_page_refresh_intent = next(
            write_intent
            for write_intent in write_intents
            if write_intent.operation_key == "replace:miscellaneous:2026-05-24"
        )

        assert create_page_keys == {"miscellaneous_notes", "miscellaneous:2026-05-24"}
        assert root_refresh_intent.arguments["markdown"] == "- 2026-05-24"
        assert dated_page_refresh_intent.arguments["markdown"] == "- Meeting fragment that may become work later."


class TestMiscellaneousNotesMetadataSnapshot:
    def test_preserves_dated_subpages(self):
        miscellaneous_notes = MiscellaneousNotesMetadata()
        miscellaneous_notes.append_to_dated_page(
            note_date="2026-05-24",
            lines=["Meeting fragment that may become work later."],
        )

        loaded_miscellaneous_notes = MiscellaneousNotesMetadata.from_tracker_state(miscellaneous_notes.to_tracker_state())

        assert loaded_miscellaneous_notes.to_tracker_state() == miscellaneous_notes.to_tracker_state()
