"""Plan Notion writes for synthesis notes."""

from __future__ import annotations

from notion_task_tracker.notion_operations.markdown import bullet, heading, join_markdown_blocks, page_mention, page_reference
from notion_task_tracker.notion_operations.page_registry import NotionPageRegistry
from notion_task_tracker.notion_operations.write_intent import NotionPlanningError, NotionWriteIntent
from notion_task_tracker.synthesis_pages import (
    SYNTHESIS_PAGE_SOURCES_HEADING,
    ExistingSynthesisPageMention,
    SynthesisNotesMetadata,
    SynthesisPageMetadata,
    SynthesisSource,
)
from notion_task_tracker.tracked_pages import TrackedPage, tracked_page_to_tracker_state


def page_registry_for_synthesis_notes(synthesis_notes: SynthesisNotesMetadata) -> NotionPageRegistry:
    return NotionPageRegistry.from_tracked_pages(_page_pointers_for_registry(synthesis_notes))


def synthesis_page_creation_write_intent(
    synthesis_notes: SynthesisNotesMetadata,
    synthesis_page: SynthesisPageMetadata,
) -> NotionWriteIntent:
    return NotionWriteIntent(
        operation_key=f"create_synthesis_page:{synthesis_page.local_page_key}",
        operation_name="create_synthesis_page",
        target_page_key=synthesis_notes.page.local_page_key,
        arguments={
            "page": tracked_page_to_tracker_state(_synthesis_page_pointer(synthesis_notes, synthesis_page)),
            "root_page_key": synthesis_notes.page.local_page_key,
            "root_page_markdown": render_synthesis_root_page_markdown(synthesis_notes),
            "markdown": render_synthesis_page_markdown(
                synthesis_page,
                page_registry_for_synthesis_notes(synthesis_notes),
            ),
        },
    )


def notion_write_plan_for_synthesis_notes(synthesis_notes: SynthesisNotesMetadata) -> list[NotionWriteIntent]:
    synthesis_notes.validate()
    return [
        *_missing_page_creation_intents(synthesis_notes),
        _root_page_refresh_intent(synthesis_notes),
        *_synthesis_page_refresh_intents(synthesis_notes),
    ]


def render_synthesis_root_page_markdown(synthesis_notes: SynthesisNotesMetadata) -> str:
    if not synthesis_notes.existing_page_mentions and not synthesis_notes.pages:
        return "No synthesis notes yet."

    page_registry = page_registry_for_synthesis_notes(synthesis_notes)
    markdown_blocks = []

    for existing_page_mention in sorted(
        synthesis_notes.existing_page_mentions.values(),
        key=lambda page: (page.display_order, page.mention_key),
    ):
        markdown_blocks.append(_render_existing_page_mention_markdown(existing_page_mention, page_registry))

    for synthesis_page in sorted(synthesis_notes.pages.values(), key=lambda page: page.synthesis_key):
        markdown_blocks.append(_synthesis_page_reference(synthesis_page, page_registry))

    return join_markdown_blocks(markdown_blocks)


def render_synthesis_page_markdown(
    synthesis_page: SynthesisPageMetadata,
    page_registry: NotionPageRegistry,
) -> str:
    markdown_blocks = [heading(2, SYNTHESIS_PAGE_SOURCES_HEADING)]

    if synthesis_page.sources:
        for source in synthesis_page.sources:
            markdown_blocks.append(_render_synthesis_source_markdown(source, page_registry))
    else:
        markdown_blocks.append("No sources recorded.")

    if synthesis_page.summary:
        markdown_blocks.append(synthesis_page.summary)

    for line in synthesis_page.lines:
        markdown_blocks.append(bullet(line))

    if not synthesis_page.summary and not synthesis_page.lines:
        markdown_blocks.append("No synthesis content yet.")

    return join_markdown_blocks(markdown_blocks)


def _missing_page_creation_intents(synthesis_notes: SynthesisNotesMetadata) -> list[NotionWriteIntent]:
    return [
        NotionWriteIntent(
            operation_key=f"create:{page.local_page_key}",
            operation_name="create_page",
            target_page_key=None,
            arguments={
                "local_page_key": page.local_page_key,
                "title": page.title,
                "parent_page_key": page.parent_page_key,
                "markdown": _page_creation_markdown(synthesis_notes, page.local_page_key),
            },
        )
        for page in _pages_that_should_exist(synthesis_notes)
        if page.notion_page_id is None
    ]


def _root_page_refresh_intent(synthesis_notes: SynthesisNotesMetadata) -> NotionWriteIntent:
    return NotionWriteIntent(
        operation_key="replace:synthesis_notes",
        operation_name="replace_page_markdown",
        target_page_key=synthesis_notes.page.local_page_key,
        arguments={"markdown": render_synthesis_root_page_markdown(synthesis_notes)},
    )


def _synthesis_page_refresh_intents(synthesis_notes: SynthesisNotesMetadata) -> list[NotionWriteIntent]:
    page_registry = page_registry_for_synthesis_notes(synthesis_notes)
    return [
        NotionWriteIntent(
            operation_key=f"replace:{synthesis_page.local_page_key}",
            operation_name="replace_page_markdown",
            target_page_key=synthesis_page.local_page_key,
            arguments={"markdown": render_synthesis_page_markdown(synthesis_page, page_registry)},
        )
        for synthesis_page in sorted(synthesis_notes.pages.values(), key=lambda page: page.synthesis_key)
    ]


def _pages_that_should_exist(synthesis_notes: SynthesisNotesMetadata) -> list[TrackedPage]:
    return [
        synthesis_notes.page,
        *[
            _synthesis_page_pointer(synthesis_notes, synthesis_page)
            for synthesis_page in synthesis_notes.pages.values()
        ],
    ]


def _page_pointers_for_registry(synthesis_notes: SynthesisNotesMetadata) -> list[TrackedPage]:
    pages = _pages_that_should_exist(synthesis_notes)
    for existing_page_mention in synthesis_notes.existing_page_mentions.values():
        pages.append(_synthesis_existing_page_mention_pointer(existing_page_mention))
    return pages


def _page_creation_markdown(synthesis_notes: SynthesisNotesMetadata, local_page_key: str) -> str:
    if local_page_key == synthesis_notes.page.local_page_key:
        return render_synthesis_root_page_markdown(synthesis_notes)

    synthesis_key = local_page_key.removeprefix("synthesis:")
    return render_synthesis_page_markdown(
        synthesis_notes.pages[synthesis_key],
        page_registry_for_synthesis_notes(synthesis_notes),
    )


def _synthesis_page_pointer(
    synthesis_notes: SynthesisNotesMetadata,
    synthesis_page: SynthesisPageMetadata,
) -> TrackedPage:
    return TrackedPage(
        local_page_key=synthesis_page.local_page_key,
        title=synthesis_page.title,
        notion_page_id=synthesis_page.notion_page_id,
        parent_page_key=synthesis_notes.page.local_page_key,
    )


def _synthesis_existing_page_mention_pointer(existing_page_mention: ExistingSynthesisPageMention) -> TrackedPage:
    return TrackedPage(
        local_page_key=existing_page_mention.local_page_key,
        title=existing_page_mention.title,
        notion_page_id=existing_page_mention.notion_page_id,
    )


def _synthesis_page_reference(
    synthesis_page: SynthesisPageMetadata,
    page_registry: NotionPageRegistry,
) -> str:
    if synthesis_page.notion_page_id is None:
        return synthesis_page.title

    return page_mention(synthesis_page.local_page_key, page_registry)


def _render_existing_page_mention_markdown(
    existing_page_mention: ExistingSynthesisPageMention,
    page_registry: NotionPageRegistry,
) -> str:
    return page_reference(
        page_key=existing_page_mention.local_page_key,
        root_block_type=existing_page_mention.root_block_type,
        page_registry=page_registry,
    )


def _render_synthesis_source_markdown(source: SynthesisSource, page_registry: NotionPageRegistry) -> str:
    text = f"{source.source_type}: {source.label}"

    if source.page_key is not None:
        try:
            return bullet(f"{text}: {page_mention(source.page_key, page_registry)}")
        except NotionPlanningError:
            return bullet(text)

    if source.external_url is not None:
        text = f"{text}: {source.external_url}"

    return bullet(text)
