import json

from notion_task_tracker.common import LANDING_PAGE_TITLE, NotionPageReference, NotionPageRegistry, NotionWriteIntent
from notion_task_tracker.miscellaneous_pages import MiscellaneousNotesMetadata
from notion_task_tracker.notion_rest_requests import NotionRestRequestPlan, NotionRestRequestPlanner
from notion_task_tracker.synthesis_pages import SynthesisNotesMetadata, SynthesisPageMetadata, SynthesisSource
from notion_task_tracker.task_pages import (
    Priority,
    TaskPageMetadata,
    TaskStatus,
    TimelineEntry,
    TaskDependencyGraph,
)


class TestNotionRestRequestPlannerCompileWriteIntent:
    def test_compiles_create_page_intent_to_create_pages_call(self):
        write_intent = NotionWriteIntent(
            operation_key="create:miscellaneous:2026-05-24",
            operation_name="create_page",
            target_page_key=None,
            arguments={
                "local_page_key": "miscellaneous:2026-05-24",
                "title": "2026-05-24",
                "parent_page_key": None,
                "blocks": [
                    {"type": "paragraph", "text": "Recent context."},
                ],
            },
        )

        request_plan = NotionRestRequestPlanner(NotionPageRegistry(pages={})).compile_write_intent(write_intent)

        assert request_plan.blocked_operations == []
        assert request_plan.requests[0].method == "POST"
        assert request_plan.requests[0].path == "/v1/pages"
        assert request_plan.requests[0].captures_page_key == "miscellaneous:2026-05-24"
        assert request_plan.requests[0].body == {
            "properties": {
                "title": [{"text": {"content": "2026-05-24"}}],
            },
            "markdown": "Recent context.",
        }

    def test_compiles_replace_page_children_intent_to_replace_content_call(self):
        work_graph = _single_task_graph()
        landing_refresh_intent = next(
            write_intent
            for write_intent in work_graph.build_notion_write_plan()
            if write_intent.operation_key == "replace:landing_page"
        )

        request_plan = NotionRestRequestPlanner(work_graph.page_registry()).compile_write_intent(landing_refresh_intent)

        assert request_plan.blocked_operations == []
        assert request_plan.requests[0].method == "PATCH"
        assert request_plan.requests[0].path == "/v1/pages/11111111111111111111111111111111/markdown"
        assert request_plan.requests[0].body["type"] == "replace_content"
        assert request_plan.requests[0].body["replace_content"]["new_str"] == "\n".join(
            [
                "## P1 (high impact)",
                (
                    '- [P1] <mention-page url="https://www.notion.so/22222222222222222222222222222222"/>'
                    ': Active {color="orange"}'
                ),
            ]
        )

    def test_compiles_update_page_properties_intent_to_update_properties_call(self):
        work_graph = _single_task_graph()
        title_update_intent = next(
            write_intent
            for write_intent in work_graph.build_notion_write_plan()
            if write_intent.operation_key == "update_properties:task:ALOVYA-1"
        )

        request_plan = NotionRestRequestPlanner(work_graph.page_registry()).compile_write_intent(title_update_intent)

        assert request_plan.blocked_operations == []
        assert request_plan.requests[0].method == "PATCH"
        assert request_plan.requests[0].path == "/v1/pages/22222222222222222222222222222222"
        assert request_plan.requests[0].body == {
            "properties": {
                "Ticket page": "Root task",
                "Priority": "P1",
                "Status": "Active",
            },
        }

    def test_compiles_new_timeline_date_to_prepend_under_timeline_log(self):
        work_graph = _single_task_graph()
        timeline_intent = work_graph.append_task_timeline_log(
            task_id="ALOVYA-1",
            timeline_entry=TimelineEntry(
                entry_date="2026-05-24",
                heading='<mention-date start="2026-05-24"/>',
                lines=["Found the remaining blocker."],
            ),
        )

        request_plan = NotionRestRequestPlanner(work_graph.page_registry()).compile_write_intent(timeline_intent)

        assert request_plan.blocked_operations == []
        assert len(request_plan.requests) == 1
        assert request_plan.requests[0].path == "/v1/pages/22222222222222222222222222222222/markdown"
        assert request_plan.requests[0].body["type"] == "update_content"
        assert request_plan.requests[0].body["update_content"]["content_updates"] == [
            {
                "old_str": "## Timeline log",
                "new_str": "\n".join(
                    [
                        "## Timeline log",
                        '### <mention-date start="2026-05-24"/>',
                        "- Found the remaining blocker.",
                    ]
                ),
            }
        ]

    def test_compiles_existing_timeline_update_to_insert_after_date_heading(self):
        work_graph = _single_task_graph()
        work_graph.tasks["ALOVYA-1"].timeline_entries.append(
            TimelineEntry(
                entry_date="2026-05-24",
                heading='<mention-date start="2026-05-24"/>',
                lines=["Existing handwritten or reconciled line."],
            )
        )
        timeline_intent = work_graph.append_task_timeline_log(
            task_id="ALOVYA-1",
            timeline_entry=TimelineEntry(
                entry_date="2026-05-24",
                heading='<mention-date start="2026-05-24"/>',
                lines=["New agent line."],
            ),
        )

        request_plan = NotionRestRequestPlanner(work_graph.page_registry()).compile_write_intent(timeline_intent)

        assert request_plan.blocked_operations == []
        assert len(request_plan.requests) == 1
        assert request_plan.requests[0].body["type"] == "update_content"
        assert request_plan.requests[0].body["update_content"]["content_updates"] == [
            {
                "old_str": '### <mention-date start="2026-05-24"/>',
                "new_str": "\n".join(
                    [
                        '### <mention-date start="2026-05-24"/>',
                        "- New agent line.",
                    ]
                ),
            }
        ]

    def test_compiles_timeline_blocks_without_bullets(self):
        work_graph = _single_task_graph()
        timeline_intent = work_graph.append_task_timeline_log(
            task_id="ALOVYA-1",
            timeline_entry=TimelineEntry(
                entry_date="2026-05-24",
                heading='<mention-date start="2026-05-24"/>',
                blocks=[
                    {"type": "paragraph", "text": "Commands run:"},
                    {
                        "type": "code",
                        "language": "bash",
                        "text": "st status\nstax rs --restack",
                    },
                ],
            ),
        )

        request_plan = NotionRestRequestPlanner(work_graph.page_registry()).compile_write_intent(timeline_intent)

        assert request_plan.blocked_operations == []
        assert request_plan.requests[0].body["update_content"]["content_updates"] == [
            {
                "old_str": "## Timeline log",
                "new_str": "\n".join(
                    [
                        "## Timeline log",
                        '### <mention-date start="2026-05-24"/>',
                        "Commands run:",
                        "```bash",
                        "st status\nstax rs --restack",
                        "```",
                    ]
                ),
            }
        ]

    def test_stages_miscellaneous_page_creation_then_refreshes_dated_and_root_pages(self):
        miscellaneous_notes = MiscellaneousNotesMetadata()
        miscellaneous_notes.page.notion_page_id = "44444444444444444444444444444444"
        append_intent = miscellaneous_notes.append_to_dated_page(
            note_date="2026-05-24",
            lines=["Recent context."],
        )

        first_request_plan = NotionRestRequestPlanner(miscellaneous_notes.page_registry()).compile_write_intent(append_intent)

        assert len(first_request_plan.requests) == 1
        assert first_request_plan.requests[0].method == "POST"
        assert first_request_plan.requests[0].body["parent"] == {
            "page_id": "44444444444444444444444444444444",
            "type": "page_id",
        }
        assert first_request_plan.requests[0].captures_page_key == "miscellaneous:2026-05-24"

        page_registry_with_dated_page = miscellaneous_notes.page_registry().with_page_id(
            local_page_key="miscellaneous:2026-05-24",
            notion_page_id="55555555555555555555555555555555",
        )
        second_request_plan = NotionRestRequestPlanner(page_registry_with_dated_page).compile_write_intent(append_intent)

        assert second_request_plan.blocked_operations == []
        assert [request.path for request in second_request_plan.requests] == [
            "/v1/pages/55555555555555555555555555555555/markdown",
            "/v1/pages/44444444444444444444444444444444/markdown",
        ]
        assert "Recent context." in second_request_plan.requests[0].body["replace_content"]["new_str"]
        assert "<mention-page" in second_request_plan.requests[1].body["replace_content"]["new_str"]

    def test_stages_synthesis_page_creation_then_refreshes_synthesis_and_root_pages(self):
        synthesis_notes = SynthesisNotesMetadata()
        synthesis_notes.page.notion_page_id = "66666666666666666666666666666666"
        create_intent = synthesis_notes.create_synthesis_page(
            SynthesisPageMetadata(
                synthesis_key="onnx_qdq",
                title="ONNX QDQ",
                summary="Reusable explanation.",
                sources=[
                    SynthesisSource(
                        source_type="Google doc",
                        label="Design notes",
                        external_url="https://example.invalid/doc",
                    )
                ],
                lines=["QDQ nodes preserve quantisation boundaries."],
            )
        )

        first_request_plan = NotionRestRequestPlanner(synthesis_notes.page_registry()).compile_write_intent(create_intent)

        assert len(first_request_plan.requests) == 1
        assert first_request_plan.requests[0].method == "POST"
        assert first_request_plan.requests[0].captures_page_key == "synthesis:onnx_qdq"
        assert "## Sources" in first_request_plan.requests[0].body["markdown"]

        page_registry_with_synthesis_page = synthesis_notes.page_registry().with_page_id(
            local_page_key="synthesis:onnx_qdq",
            notion_page_id="77777777777777777777777777777777",
        )
        second_request_plan = NotionRestRequestPlanner(page_registry_with_synthesis_page).compile_write_intent(create_intent)

        assert second_request_plan.blocked_operations == []
        assert [request.path for request in second_request_plan.requests] == [
            "/v1/pages/77777777777777777777777777777777/markdown",
            "/v1/pages/66666666666666666666666666666666/markdown",
        ]
        assert "Google doc: Design notes: https://example.invalid/doc" in second_request_plan.requests[0].body["replace_content"]["new_str"]
        assert (
            '<mention-page url="https://www.notion.so/77777777777777777777777777777777"/>'
            in second_request_plan.requests[1].body["replace_content"]["new_str"]
        )


class TestNotionRestRequestPlanSnapshot:
    def test_round_trips_request_plan_json_shape(self, tmp_path):
        output_path = tmp_path / "notion_rest_request_plan.json"
        request_plan = NotionRestRequestPlan(
            requests=[
                NotionRestRequestPlanner(
                    NotionPageRegistry(
                        pages={
                            "landing_page": NotionPageReference(
                                local_page_key="landing_page",
                                title=LANDING_PAGE_TITLE,
                                notion_page_id="11111111111111111111111111111111",
                            )
                        }
                    )
                ).compile_write_intent(
                    NotionWriteIntent(
                        operation_key="replace:landing_page",
                        operation_name="replace_page_children",
                        target_page_key="landing_page",
                        arguments={
                            "blocks": [
                                {"type": "paragraph", "text": "Body"},
                            ]
                        },
                    )
                ).requests[0]
            ]
        )

        request_plan.write_json(output_path)
        loaded_request_plan = NotionRestRequestPlan.from_snapshot(json.loads(output_path.read_text()))

        assert loaded_request_plan.to_snapshot() == request_plan.to_snapshot()


def _single_task_graph() -> TaskDependencyGraph:
    work_graph = TaskDependencyGraph()
    work_graph.landing_page.notion_page_id = "11111111111111111111111111111111"
    work_graph.add_task(
        TaskPageMetadata(
            task_id="ALOVYA-1",
            title="Root task",
            configured_priority=Priority.P1,
            status=TaskStatus.ACTIVE,
            notion_page_id="22222222222222222222222222222222",
        )
    )
    return work_graph
