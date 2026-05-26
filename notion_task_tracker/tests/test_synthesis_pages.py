import pytest

from notion_task_tracker.notion_pages import NotionPlanningError
from notion_task_tracker.synthesis_pages import (
    ExistingSynthesisPageMention,
    SynthesisNotesMetadata,
    SynthesisPageMetadata,
    SynthesisSource,
    parse_synthesis_root_page_mentions,
)


class TestSynthesisNotesMetadataCreateSynthesisPage:
    def test_creates_one_flat_synthesis_subpage_from_supplied_context(self):
        synthesis_notes = SynthesisNotesMetadata()
        synthesis_page = SynthesisPageMetadata(
            synthesis_key="onnx_qdq_export",
            title="ONNX QDQ export behaviour",
            summary="Reusable notes on export behaviour.",
            sources=[
                SynthesisSource(
                    source_type="Notion page",
                    label="ALOVYA-2",
                    page_key="task:ALOVYA-2",
                ),
                SynthesisSource(
                    source_type="Miscellaneous notes",
                    label="2026-05-24",
                    page_key="miscellaneous:2026-05-24",
                ),
                SynthesisSource(
                    source_type="Google doc",
                    label="Export notes",
                    external_url="https://example.invalid/doc",
                ),
            ],
            lines=["QDQ nodes preserve quantisation boundaries for export."],
        )

        write_intent = synthesis_notes.create_synthesis_page(synthesis_page)

        assert list(synthesis_notes.pages) == ["onnx_qdq_export"]
        assert write_intent.operation_name == "create_synthesis_page"
        assert write_intent.target_page_key == "synthesis_notes"
        assert write_intent.arguments["page"]["parent_page_key"] == "synthesis_notes"
        assert write_intent.arguments["root_page_child_block"] == {
            "type": "page_mention",
            "page_key": "synthesis:onnx_qdq_export",
        }
        assert write_intent.arguments["blocks"][0] == {
            "type": "heading_2",
            "text": "Sources",
        }
        assert {"type": "paragraph", "text": "Reusable notes on export behaviour."} in write_intent.arguments["blocks"]
        assert {
            "type": "bulleted_list_item",
            "depth": 0,
            "text": "Notion page: ALOVYA-2",
            "page_key": "task:ALOVYA-2",
        } in write_intent.arguments["blocks"]
        assert {
            "type": "bulleted_list_item",
            "depth": 0,
            "text": "Google doc: Export notes: https://example.invalid/doc",
        } in write_intent.arguments["blocks"]


class TestSynthesisNotesMetadataBuildNotionWritePlan:
    def test_keeps_synthesis_root_as_flat_page_mentions(self):
        synthesis_notes = SynthesisNotesMetadata()
        synthesis_notes.existing_page_mentions["existing_guide"] = ExistingSynthesisPageMention(
            mention_key="existing_guide",
            title="Existing guide",
            notion_page_id="11111111111111111111111111111111",
        )
        synthesis_notes.create_synthesis_page(
            SynthesisPageMetadata(
                synthesis_key="onnx_qdq_export",
                title="ONNX QDQ export behaviour",
                summary="Reusable notes on export behaviour.",
            )
        )

        write_intents = synthesis_notes.build_notion_write_plan()

        operation_keys = {write_intent.operation_key for write_intent in write_intents}
        create_page_keys = {
            write_intent.arguments["local_page_key"]
            for write_intent in write_intents
            if write_intent.operation_name == "create_page"
        }
        root_refresh_intent = next(
            write_intent
            for write_intent in write_intents
            if write_intent.operation_key == "replace:synthesis_notes"
        )

        assert create_page_keys == {"synthesis_notes", "synthesis:onnx_qdq_export"}
        assert operation_keys == {
            "create:synthesis_notes",
            "create:synthesis:onnx_qdq_export",
            "replace:synthesis_notes",
            "replace:synthesis:onnx_qdq_export",
        }
        assert root_refresh_intent.arguments["blocks"] == [
            {
                "type": "page_mention",
                "page_key": "existing_synthesis:existing_guide",
            },
            {
                "type": "page_mention",
                "page_key": "synthesis:onnx_qdq_export",
            }
        ]


class TestSynthesisNotesMetadataReconcileRootPageMentionsFromContent:
    def test_replaces_local_existing_mentions_with_the_fetched_root_page_order(self):
        synthesis_notes = SynthesisNotesMetadata()
        synthesis_notes.existing_page_mentions["stale"] = ExistingSynthesisPageMention(
            mention_key="stale",
            title="Stale page",
            notion_page_id="11111111111111111111111111111111",
        )
        synthesis_notes.existing_page_mentions["22222222222222222222222222222222"] = ExistingSynthesisPageMention(
            mention_key="22222222222222222222222222222222",
            title="Old title",
            notion_page_id="22222222222222222222222222222222",
        )

        synthesis_notes.reconcile_root_page_mentions_from_content(
            root_page_content=(
                '<mention-page url="https://www.notion.so/wayve/New-title-'
                '33333333333333333333333333333333">New title</mention-page>\n'
                '<mention-page url="https://www.notion.so/wayve/22222222222222222222222222222222"/>'
            ),
        )

        assert list(synthesis_notes.existing_page_mentions) == [
            "33333333333333333333333333333333",
            "22222222222222222222222222222222",
        ]
        assert synthesis_notes.existing_page_mentions["33333333333333333333333333333333"].title == "New title"
        assert synthesis_notes.existing_page_mentions["33333333333333333333333333333333"].display_order == 0
        assert synthesis_notes.existing_page_mentions["33333333333333333333333333333333"].root_block_type == (
            "page_mention"
        )
        assert synthesis_notes.existing_page_mentions["22222222222222222222222222222222"].title == "Old title"
        assert synthesis_notes.existing_page_mentions["22222222222222222222222222222222"].display_order == 1

    def test_preserves_child_page_entries_from_a_full_fetched_page(self):
        synthesis_notes = SynthesisNotesMetadata()

        synthesis_notes.reconcile_root_page_mentions_from_content(
            root_page_content=(
                '<page url="https://www.notion.so/rootrootrootrootrootrootrootroot" icon="🧾">\n'
                "<content>\n"
                '<page url="https://www.notion.so/wayve/Guide-'
                '99999999999999999999999999999999">Guide</page>\n'
                "</content>\n"
                "</page>"
            ),
        )

        root_page_entry = synthesis_notes.existing_page_mentions["99999999999999999999999999999999"]
        root_page_blocks = synthesis_notes.build_notion_write_plan()[1].arguments["blocks"]

        assert root_page_entry.title == "Guide"
        assert root_page_entry.root_block_type == "child_page"
        assert root_page_blocks == [
            {
                "type": "child_page",
                "page_key": "existing_synthesis:99999999999999999999999999999999",
            },
        ]

    def test_uses_agent_supplied_titles_for_bare_new_page_mentions(self):
        synthesis_notes = SynthesisNotesMetadata()

        synthesis_notes.reconcile_root_page_mentions_from_content(
            root_page_content=(
                '<mention-page url="https://www.notion.so/wayve/'
                '44444444444444444444444444444444"/>'
            ),
            page_titles_by_id={
                "44444444-4444-4444-4444-444444444444": "Supplied title",
            },
        )

        assert synthesis_notes.existing_page_mentions["44444444444444444444444444444444"].title == "Supplied title"

    def test_rejects_bare_new_page_mentions_without_a_known_title(self):
        synthesis_notes = SynthesisNotesMetadata()

        with pytest.raises(NotionPlanningError):
            synthesis_notes.reconcile_root_page_mentions_from_content(
                root_page_content=(
                    '<mention-page url="https://www.notion.so/wayve/'
                    '55555555555555555555555555555555"/>'
                ),
            )

    def test_rejects_duplicate_existing_page_mentions(self):
        synthesis_notes = SynthesisNotesMetadata()

        with pytest.raises(NotionPlanningError):
            synthesis_notes.reconcile_root_page_mentions_from_content(
                root_page_content=(
                    '<mention-page url="https://www.notion.so/wayve/'
                    '66666666666666666666666666666666">Duplicate</mention-page>\n'
                    '<mention-page url="https://www.notion.so/wayve/'
                    '66666666666666666666666666666666">Duplicate</mention-page>'
                ),
            )


class TestParseSynthesisRootPageMentions:
    def test_extracts_page_ids_and_optional_titles_from_mcp_markdown(self):
        page_mentions = parse_synthesis_root_page_mentions(
            '<mention-page url="https://www.notion.so/wayve/Guide-'
            '77777777777777777777777777777777">Guide</mention-page>\n'
            '<mention-page url="https://www.notion.so/wayve/'
            '88888888888888888888888888888888"/>'
        )

        assert page_mentions[0].notion_page_id == "77777777777777777777777777777777"
        assert page_mentions[0].title == "Guide"
        assert page_mentions[1].notion_page_id == "88888888888888888888888888888888"
        assert page_mentions[1].title is None
        assert page_mentions[1].root_block_type == "page_mention"


class TestSynthesisNotesMetadataSnapshot:
    def test_preserves_flat_synthesis_pages(self):
        synthesis_notes = SynthesisNotesMetadata()
        synthesis_notes.create_synthesis_page(
            SynthesisPageMetadata(
                synthesis_key="activation_outliers",
                title="Activation outliers after SwiGLU",
                summary="Reusable explanation.",
                sources=[
                    SynthesisSource(
                        source_type="Slack thread",
                        label="Activation discussion",
                        external_url="https://example.invalid/slack",
                    )
                ],
            )
        )

        loaded_synthesis_notes = SynthesisNotesMetadata.from_snapshot(synthesis_notes.to_snapshot())

        assert loaded_synthesis_notes.to_snapshot() == synthesis_notes.to_snapshot()
        assert loaded_synthesis_notes.pages["activation_outliers"].summary == "Reusable explanation."
        assert loaded_synthesis_notes.pages["activation_outliers"].sources[0].source_type == "Slack thread"

    def test_preserves_existing_page_mentions_without_creating_them(self):
        synthesis_notes = SynthesisNotesMetadata()
        synthesis_notes.existing_page_mentions["existing_guide"] = ExistingSynthesisPageMention(
            mention_key="existing_guide",
            title="Existing guide",
            notion_page_id="11111111111111111111111111111111",
            display_order=3,
        )

        write_intents = synthesis_notes.build_notion_write_plan()
        create_page_keys = {
            write_intent.arguments["local_page_key"]
            for write_intent in write_intents
            if write_intent.operation_name == "create_page"
        }

        loaded_synthesis_notes = SynthesisNotesMetadata.from_snapshot(synthesis_notes.to_snapshot())

        assert loaded_synthesis_notes.existing_page_mentions["existing_guide"].title == "Existing guide"
        assert loaded_synthesis_notes.existing_page_mentions["existing_guide"].display_order == 3
        assert create_page_keys == {"synthesis_notes"}
