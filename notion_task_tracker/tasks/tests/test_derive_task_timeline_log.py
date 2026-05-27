from notion_task_tracker.tasks.tests.build_task_command_fixtures import build_tracker_state_with_root_task
from notion_task_tracker.tasks.derive_task_timeline_log import (
    derive_task_timeline_log_from_fetched_page_content,
    record_known_task_timeline_dates,
)


def test_record_known_task_timeline_dates_remembers_manual_date_before_logging():
    tracker_state = build_tracker_state_with_root_task()

    updated_tracker_state = record_known_task_timeline_dates(
        task_id="ALOVYA-1",
        tracker_state=tracker_state,
        timeline_entries=[
            {
                "entry_date": "2026-05-26",
                "heading": '<mention-date start="2026-05-26"/>',
            }
        ],
    )

    assert updated_tracker_state["tasks"]["ALOVYA-1"]["timeline_entries"] == [
        {
            "entry_date": "2026-05-26",
            "heading": '<mention-date start="2026-05-26"/>',
            "lines": [],
        }
    ]


def test_derive_task_timeline_log_from_fetched_page_content_records_missing_timeline_log():
    tracker_state = build_tracker_state_with_root_task()

    derived_timeline_log = derive_task_timeline_log_from_fetched_page_content(
        task_id="ALOVYA-1",
        entry_date="2026-05-26",
        tracker_state=tracker_state,
        fetched_page_content="\n".join(
            [
                "<page>",
                "<properties>",
                '{"Ticket ID":"1","Ticket page":"Root task"}',
                "</properties>",
                "Loose notes written before the tracker touched the page.",
                "</page>",
            ]
        ),
    )

    assert not derived_timeline_log.has_usable_timeline_log
    assert derived_timeline_log.tracker_state["tasks"]["ALOVYA-1"]["timeline_entries"] == [
        {
            "entry_date": "2026-05-26",
            "heading": '<mention-date start="2026-05-26"/>',
            "lines": [],
        }
    ]


def test_derive_task_timeline_log_from_fetched_page_content_records_empty_timeline_log():
    tracker_state = build_tracker_state_with_root_task()

    derived_timeline_log = derive_task_timeline_log_from_fetched_page_content(
        task_id="ALOVYA-1",
        entry_date="2026-05-26",
        tracker_state=tracker_state,
        fetched_page_content="\n".join(
            [
                "## Timeline log",
                "Loose notes already under the heading.",
            ]
        ),
    )

    assert not derived_timeline_log.has_usable_timeline_log
    assert derived_timeline_log.tracker_state["tasks"]["ALOVYA-1"]["timeline_entries"][0]["entry_date"] == "2026-05-26"


def test_derive_task_timeline_log_from_fetched_page_content_keeps_usable_timeline_log():
    tracker_state = build_tracker_state_with_root_task()

    derived_timeline_log = derive_task_timeline_log_from_fetched_page_content(
        task_id="ALOVYA-1",
        entry_date="2026-05-26",
        tracker_state=tracker_state,
        fetched_page_content="\n".join(
            [
                "## Timeline log",
                '### <mention-date start="2026-05-25"/>',
                "- Existing log.",
            ]
        ),
    )

    assert derived_timeline_log.has_usable_timeline_log
    assert derived_timeline_log.tracker_state["tasks"]["ALOVYA-1"]["timeline_entries"] == [
        {
            "entry_date": "2026-05-25",
            "heading": '<mention-date start="2026-05-25"/>',
            "lines": [],
        }
    ]
