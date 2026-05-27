"""Parse task page body content fetched from Notion."""

from __future__ import annotations

import re

from notion_task_tracker.tasks.task import (
    MENTION_DATE_START_PATTERN,
    PROPERTIES_BLOCK_PATTERN,
    TASK_PAGE_TIMELINE_LOG_HEADING,
)


def timeline_entries_from_fetched_task_page_content(fetched_page_content: str) -> list[dict[str, str]]:
    timeline_content = _timeline_log_content_from_fetched_task_page_content(fetched_page_content)
    if timeline_content is None:
        return []

    timeline_entries = []
    seen_entry_dates = set()
    for heading in _markdown_headings_from_content(timeline_content):
        entry_date = _entry_date_from_timeline_heading(heading)
        if entry_date is None or entry_date in seen_entry_dates:
            continue

        timeline_entries.append({
            "entry_date": entry_date,
            "heading": heading,
        })
        seen_entry_dates.add(entry_date)

    return timeline_entries


def fetched_task_page_has_usable_timeline_log(
    fetched_page_content: str,
    timeline_entries: list[dict[str, str]],
) -> bool:
    return _timeline_log_content_from_fetched_task_page_content(fetched_page_content) is not None and bool(timeline_entries)


def initialised_task_timeline_markdown(
    entry_date: str,
    timeline_section_markdown: str,
    fetched_page_content: str,
) -> str:
    del entry_date
    existing_body_content = body_content_to_subsume_under_initial_timeline_date(fetched_page_content)
    return _join_markdown_blocks([
        f"## {TASK_PAGE_TIMELINE_LOG_HEADING}",
        timeline_section_markdown,
        existing_body_content,
    ])


def timeline_entry_for_date(entry_date: str) -> dict[str, str]:
    return {
        "entry_date": entry_date,
        "heading": f'<mention-date start="{entry_date}"/>',
    }


def body_content_to_subsume_under_initial_timeline_date(fetched_page_content: str) -> str:
    body_content = _body_content_from_fetched_task_page_content(fetched_page_content)
    existing_timeline_content = _timeline_log_content_from_body_content(body_content)
    if existing_timeline_content is None:
        return body_content.strip()

    return _content_below_first_markdown_heading(existing_timeline_content).strip()


def _body_content_from_fetched_task_page_content(fetched_page_content: str) -> str:
    content_match = re.search(r"<content>\s*(?P<content>.*?)\s*</content>", fetched_page_content, re.DOTALL)
    if content_match is not None:
        return content_match.group("content").strip()

    content_without_properties = PROPERTIES_BLOCK_PATTERN.sub("", fetched_page_content)
    content_without_page_tags = re.sub(r"(?m)^\s*</?page[^>]*>\s*$", "", content_without_properties)
    return content_without_page_tags.strip()


def _timeline_log_content_from_fetched_task_page_content(fetched_page_content: str) -> str | None:
    return _timeline_log_content_from_body_content(_body_content_from_fetched_task_page_content(fetched_page_content))


def _timeline_log_content_from_body_content(body_content: str) -> str | None:
    timeline_heading_match = re.search(
        rf"(?m)^##\s+{re.escape(TASK_PAGE_TIMELINE_LOG_HEADING)}\s*$",
        body_content,
    )
    if timeline_heading_match is None:
        return None

    return body_content[timeline_heading_match.start():]


def _content_below_first_markdown_heading(content: str) -> str:
    lines = content.splitlines()
    if not lines:
        return ""

    return "\n".join(lines[1:])


def _markdown_headings_from_content(content: str) -> list[str]:
    headings = []
    for line in content.splitlines():
        heading_match = re.match(r"\s*#{1,6}\s+(?P<heading>.+?)\s*$", line)
        if heading_match is None:
            continue

        headings.append(heading_match.group("heading"))
    return headings


def _entry_date_from_timeline_heading(heading: str) -> str | None:
    mention_date_match = MENTION_DATE_START_PATTERN.search(heading)
    if mention_date_match is not None:
        return mention_date_match.group(1)

    plain_date_match = re.fullmatch(r"\d{4}-\d{2}-\d{2}", heading)
    if plain_date_match is not None:
        return plain_date_match.group(0)

    return None


def _join_markdown_blocks(blocks: list[str]) -> str:
    return "\n".join(block.rstrip() for block in blocks if block.strip())
