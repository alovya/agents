"""Synthesis notes metadata and flat subpage planning."""

from __future__ import annotations

from dataclasses import dataclass, field
from html.parser import HTMLParser
from typing import Any

from notion_task_tracker.common import (
    SYNTHESIS_NOTES_PAGE_LOCAL_KEY,
    SYNTHESIS_NOTES_PAGE_TITLE,
    NotionPageRegistry,
    NotionPlanningError,
    NotionWriteIntent,
    PagePointer,
    canonical_notion_page_id,
    child_page_block,
    fixed_page_pointer_from_snapshot,
    heading_block,
    linked_metadata_bullet_block,
    metadata_bullet_block,
    notion_page_id_from_url,
    page_mention_block,
    page_pointer_to_snapshot,
    paragraph_block,
    validate_fixed_page_pointer,
)


SYNTHESIS_PAGE_SOURCES_HEADING = "Sources"
SYNTHESIS_ROOT_CHILD_PAGE_BLOCK = "child_page"
SYNTHESIS_ROOT_PAGE_MENTION_BLOCK = "page_mention"
SYNTHESIS_ROOT_REFERENCE_BLOCK_TYPES = {
    SYNTHESIS_ROOT_CHILD_PAGE_BLOCK,
    SYNTHESIS_ROOT_PAGE_MENTION_BLOCK,
}


@dataclass
class SynthesisSource:
    """A cited source behind a synthesis page."""

    source_type: str
    label: str
    page_key: str | None = None
    external_url: str | None = None


@dataclass
class SynthesisPageMetadata:
    """Reusable concept page independent of tasks."""

    synthesis_key: str
    title: str
    summary: str = ""
    lines: list[str] = field(default_factory=list)
    sources: list[SynthesisSource] = field(default_factory=list)
    notion_page_id: str | None = None

    @property
    def local_page_key(self) -> str:
        return f"synthesis:{self.synthesis_key}"


@dataclass
class ExistingSynthesisPageMention:
    """Existing Notion page mentioned on the root but not owned."""

    mention_key: str
    title: str
    notion_page_id: str
    display_order: int = 0
    root_block_type: str = SYNTHESIS_ROOT_PAGE_MENTION_BLOCK

    @property
    def local_page_key(self) -> str:
        return f"existing_synthesis:{self.mention_key}"


@dataclass(frozen=True)
class SynthesisRootPageMention:
    """Page mention parsed from the synthesis root page body."""

    notion_page_id: str
    title: str | None = None
    root_block_type: str = SYNTHESIS_ROOT_PAGE_MENTION_BLOCK


@dataclass
class SynthesisNotesMetadata:
    """Root page and flat synthesis subpages."""

    page: PagePointer = field(
        default_factory=lambda: PagePointer(
            local_page_key=SYNTHESIS_NOTES_PAGE_LOCAL_KEY,
            title=SYNTHESIS_NOTES_PAGE_TITLE,
        )
    )
    existing_page_mentions: dict[str, ExistingSynthesisPageMention] = field(default_factory=dict)
    pages: dict[str, SynthesisPageMetadata] = field(default_factory=dict)

    @classmethod
    def from_snapshot(cls, snapshot: dict[str, Any]) -> SynthesisNotesMetadata:
        synthesis_notes = cls(
            page=fixed_page_pointer_from_snapshot(
                snapshot["page"],
                local_page_key=SYNTHESIS_NOTES_PAGE_LOCAL_KEY,
                title=SYNTHESIS_NOTES_PAGE_TITLE,
            )
        )
        synthesis_notes.pages = {
            synthesis_key: _synthesis_page_from_snapshot(page_snapshot)
            for synthesis_key, page_snapshot in snapshot.get("pages", {}).items()
        }
        synthesis_notes.existing_page_mentions = {
            mention_key: _synthesis_existing_page_mention_from_snapshot(page_snapshot)
            for mention_key, page_snapshot in snapshot.get("existing_page_mentions", {}).items()
        }
        synthesis_notes.validate()
        return synthesis_notes

    def create_synthesis_page(self, synthesis_page: SynthesisPageMetadata) -> NotionWriteIntent:
        self.pages[synthesis_page.synthesis_key] = synthesis_page
        self.validate()
        return self._plan_synthesis_page_creation(synthesis_page)

    def reconcile_root_page_mentions_from_content(
        self,
        root_page_content: str,
        page_titles_by_id: dict[str, str] | None = None,
    ) -> None:
        root_page_mentions = parse_synthesis_root_page_mentions(root_page_content)
        self.reconcile_root_page_mentions(
            root_page_mentions=root_page_mentions,
            page_titles_by_id=page_titles_by_id or {},
        )

    def reconcile_root_page_mentions(
        self,
        root_page_mentions: list[SynthesisRootPageMention],
        page_titles_by_id: dict[str, str] | None = None,
    ) -> None:
        title_lookup = self._known_titles_by_notion_page_id()
        title_lookup.update(_canonical_title_lookup(page_titles_by_id or {}))

        managed_page_ids = self._managed_synthesis_page_ids()
        reconciled_existing_page_mentions = {}

        for display_order, root_page_mention in enumerate(root_page_mentions):
            notion_page_id = canonical_notion_page_id(root_page_mention.notion_page_id)

            if notion_page_id in managed_page_ids:
                continue

            title = _title_for_root_page_mention(
                root_page_mention=root_page_mention,
                title_lookup=title_lookup,
            )
            mention_key = _mention_key_from_notion_page_id(notion_page_id)

            if mention_key in reconciled_existing_page_mentions:
                raise NotionPlanningError(
                    f"Synthesis root mentions page {notion_page_id!r} more than once"
                )

            reconciled_existing_page_mentions[mention_key] = ExistingSynthesisPageMention(
                mention_key=mention_key,
                title=title,
                notion_page_id=notion_page_id,
                display_order=display_order,
                root_block_type=root_page_mention.root_block_type,
            )

        self.existing_page_mentions = reconciled_existing_page_mentions
        self.validate()

    def build_notion_write_plan(self) -> list[NotionWriteIntent]:
        self.validate()

        write_intents = []
        write_intents.extend(self._plan_missing_page_creation())
        write_intents.append(self._plan_root_page_refresh())
        write_intents.extend(self._plan_synthesis_page_refreshes())
        return write_intents

    def validate(self) -> None:
        validate_fixed_page_pointer(
            page=self.page,
            expected_local_page_key=SYNTHESIS_NOTES_PAGE_LOCAL_KEY,
            expected_title=SYNTHESIS_NOTES_PAGE_TITLE,
        )
        self._validate_page_keys_match_page_values()
        self._validate_root_block_types()

    def to_snapshot(self) -> dict[str, Any]:
        return {
            "page": page_pointer_to_snapshot(self.page),
            "existing_page_mentions": {
                mention_key: _synthesis_existing_page_mention_to_snapshot(existing_page_mention)
                for mention_key, existing_page_mention in sorted(self.existing_page_mentions.items())
            },
            "pages": {
                synthesis_key: _synthesis_page_to_snapshot(synthesis_page)
                for synthesis_key, synthesis_page in sorted(self.pages.items())
            },
        }

    def page_registry(self) -> NotionPageRegistry:
        self.validate()
        return NotionPageRegistry.from_page_pointers(self._page_pointers_for_registry())

    def _plan_synthesis_page_creation(self, synthesis_page: SynthesisPageMetadata) -> NotionWriteIntent:
        return NotionWriteIntent(
            operation_key=f"create_synthesis_page:{synthesis_page.local_page_key}",
            operation_name="create_synthesis_page",
            target_page_key=self.page.local_page_key,
            arguments={
                "page": _synthesis_page_pointer_to_snapshot(self.page, synthesis_page),
                "root_page_key": self.page.local_page_key,
                "root_page_child_block": _render_synthesis_page_mention_block(synthesis_page),
                "blocks": _render_synthesis_page_blocks(synthesis_page),
                "root_page_blocks": self._render_root_page_blocks(),
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
            operation_key="replace:synthesis_notes",
            operation_name="replace_page_children",
            target_page_key=self.page.local_page_key,
            arguments={
                "blocks": self._render_root_page_blocks(),
            },
        )

    def _plan_synthesis_page_refreshes(self) -> list[NotionWriteIntent]:
        return [
            NotionWriteIntent(
                operation_key=f"replace:{synthesis_page.local_page_key}",
                operation_name="replace_page_children",
                target_page_key=synthesis_page.local_page_key,
                arguments={
                    "blocks": _render_synthesis_page_blocks(synthesis_page),
                },
            )
            for synthesis_page in sorted(self.pages.values(), key=lambda page: page.synthesis_key)
        ]

    def _pages_that_should_exist(self) -> list[PagePointer]:
        pages = [self.page]

        for synthesis_page in self.pages.values():
            pages.append(_synthesis_page_pointer(self.page, synthesis_page))

        return pages

    def _page_pointers_for_registry(self) -> list[PagePointer]:
        pages = self._pages_that_should_exist()

        for existing_page_mention in self.existing_page_mentions.values():
            pages.append(_synthesis_existing_page_mention_pointer(existing_page_mention))

        return pages

    def _render_root_page_blocks(self) -> list[dict[str, Any]]:
        if not self.existing_page_mentions and not self.pages:
            return [paragraph_block(text="No synthesis notes yet.")]

        blocks = []

        for existing_page_mention in sorted(
            self.existing_page_mentions.values(),
            key=lambda page: (page.display_order, page.mention_key),
        ):
            blocks.append(_render_existing_page_mention_block(existing_page_mention))

        for synthesis_page in sorted(self.pages.values(), key=lambda page: page.synthesis_key):
            blocks.append(_render_synthesis_page_mention_block(synthesis_page))

        return blocks

    def _page_creation_blocks(self, local_page_key: str) -> list[dict[str, Any]]:
        if local_page_key == self.page.local_page_key:
            return self._render_root_page_blocks()

        synthesis_key = local_page_key.removeprefix("synthesis:")
        return _render_synthesis_page_blocks(self.pages[synthesis_key])

    def _validate_page_keys_match_page_values(self) -> None:
        for synthesis_key, synthesis_page in self.pages.items():
            if synthesis_key != synthesis_page.synthesis_key:
                raise ValueError(
                    f"Synthesis page dictionary key {synthesis_key!r} "
                    f"does not match page {synthesis_page.synthesis_key!r}"
                )

    def _validate_root_block_types(self) -> None:
        for existing_page_mention in self.existing_page_mentions.values():
            if existing_page_mention.root_block_type not in SYNTHESIS_ROOT_REFERENCE_BLOCK_TYPES:
                raise ValueError(
                    f"Existing synthesis root block type {existing_page_mention.root_block_type!r} "
                    f"must be one of {sorted(SYNTHESIS_ROOT_REFERENCE_BLOCK_TYPES)!r}"
                )

        for mention_key, existing_page_mention in self.existing_page_mentions.items():
            if mention_key != existing_page_mention.mention_key:
                raise ValueError(
                    f"Existing synthesis page mention dictionary key {mention_key!r} "
                    f"does not match page {existing_page_mention.mention_key!r}"
                )

    def _known_titles_by_notion_page_id(self) -> dict[str, str]:
        titles_by_page_id = {}

        for existing_page_mention in self.existing_page_mentions.values():
            page_id = canonical_notion_page_id(existing_page_mention.notion_page_id)
            titles_by_page_id[page_id] = existing_page_mention.title

        for synthesis_page in self.pages.values():
            if synthesis_page.notion_page_id is not None:
                page_id = canonical_notion_page_id(synthesis_page.notion_page_id)
                titles_by_page_id[page_id] = synthesis_page.title

        return titles_by_page_id

    def _managed_synthesis_page_ids(self) -> set[str]:
        return {
            canonical_notion_page_id(synthesis_page.notion_page_id)
            for synthesis_page in self.pages.values()
            if synthesis_page.notion_page_id is not None
        }


def parse_synthesis_root_page_mentions(root_page_content: str) -> list[SynthesisRootPageMention]:
    parser = _SynthesisRootPageMentionParser(
        parse_only_content_tag="<content>" in root_page_content,
    )
    parser.feed(root_page_content)
    parser.close()
    return parser.page_mentions


class _SynthesisRootPageMentionParser(HTMLParser):
    def __init__(self, parse_only_content_tag: bool):
        super().__init__()
        self.parse_only_content_tag = parse_only_content_tag
        self._inside_content_tag = False
        self.page_mentions: list[SynthesisRootPageMention] = []
        self._open_page_mention_url: str | None = None
        self._open_page_mention_title_parts: list[str] = []
        self._open_page_mention_block_type: str | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "content":
            self._inside_content_tag = True
            return

        if not self._should_parse_page_references() or tag not in {"mention-page", "page"}:
            return

        attrs_by_name = dict(attrs)
        self._open_page_mention_url = attrs_by_name.get("url")
        self._open_page_mention_title_parts = []
        self._open_page_mention_block_type = _root_block_type_from_tag(tag)

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if not self._should_parse_page_references() or tag not in {"mention-page", "page"}:
            return

        attrs_by_name = dict(attrs)
        self._append_page_mention(
            notion_url=attrs_by_name.get("url"),
            title=None,
            root_block_type=_root_block_type_from_tag(tag),
        )

    def handle_data(self, data: str) -> None:
        if self._open_page_mention_url is not None:
            self._open_page_mention_title_parts.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag == "content":
            self._inside_content_tag = False
            return

        if not self._should_parse_page_references() or tag not in {"mention-page", "page"}:
            return

        title = "".join(self._open_page_mention_title_parts).strip() or None
        self._append_page_mention(
            notion_url=self._open_page_mention_url,
            title=title,
            root_block_type=self._open_page_mention_block_type,
        )
        self._open_page_mention_url = None
        self._open_page_mention_title_parts = []
        self._open_page_mention_block_type = None

    def _should_parse_page_references(self) -> bool:
        return self._inside_content_tag or not self.parse_only_content_tag

    def _append_page_mention(
        self,
        notion_url: str | None,
        title: str | None,
        root_block_type: str | None,
    ) -> None:
        if notion_url is None:
            raise NotionPlanningError("Synthesis root contains a page mention without a URL")

        if root_block_type is None:
            raise NotionPlanningError("Synthesis root contains a page mention without a block type")

        self.page_mentions.append(
            SynthesisRootPageMention(
                notion_page_id=notion_page_id_from_url(notion_url),
                title=title,
                root_block_type=root_block_type,
            )
        )


def _canonical_title_lookup(page_titles_by_id: dict[str, str]) -> dict[str, str]:
    return {
        canonical_notion_page_id(notion_page_id): title
        for notion_page_id, title in page_titles_by_id.items()
    }


def _title_for_root_page_mention(
    root_page_mention: SynthesisRootPageMention,
    title_lookup: dict[str, str],
) -> str:
    notion_page_id = canonical_notion_page_id(root_page_mention.notion_page_id)

    if root_page_mention.title:
        return root_page_mention.title

    if notion_page_id in title_lookup:
        return title_lookup[notion_page_id]

    raise NotionPlanningError(
        f"Fetched synthesis root mentions page {notion_page_id!r} without a known title"
    )


def _mention_key_from_notion_page_id(notion_page_id: str) -> str:
    return canonical_notion_page_id(notion_page_id)


def _root_block_type_from_tag(tag: str) -> str:
    if tag == "page":
        return SYNTHESIS_ROOT_CHILD_PAGE_BLOCK

    if tag == "mention-page":
        return SYNTHESIS_ROOT_PAGE_MENTION_BLOCK

    raise NotionPlanningError(f"Unsupported synthesis root page-reference tag {tag!r}")


def _synthesis_page_pointer(
    root_page: PagePointer,
    synthesis_page: SynthesisPageMetadata,
) -> PagePointer:
    return PagePointer(
        local_page_key=synthesis_page.local_page_key,
        title=synthesis_page.title,
        notion_page_id=synthesis_page.notion_page_id,
        parent_page_key=root_page.local_page_key,
    )


def _synthesis_page_pointer_to_snapshot(
    root_page: PagePointer,
    synthesis_page: SynthesisPageMetadata,
) -> dict[str, Any]:
    return page_pointer_to_snapshot(_synthesis_page_pointer(root_page, synthesis_page))


def _synthesis_existing_page_mention_pointer(existing_page_mention: ExistingSynthesisPageMention) -> PagePointer:
    return PagePointer(
        local_page_key=existing_page_mention.local_page_key,
        title=existing_page_mention.title,
        notion_page_id=existing_page_mention.notion_page_id,
    )


def _render_synthesis_page_mention_block(synthesis_page: SynthesisPageMetadata) -> dict[str, Any]:
    return page_mention_block(synthesis_page.local_page_key)


def _render_existing_page_mention_block(existing_page_mention: ExistingSynthesisPageMention) -> dict[str, Any]:
    if existing_page_mention.root_block_type == SYNTHESIS_ROOT_CHILD_PAGE_BLOCK:
        return child_page_block(existing_page_mention.local_page_key)

    if existing_page_mention.root_block_type == SYNTHESIS_ROOT_PAGE_MENTION_BLOCK:
        return page_mention_block(existing_page_mention.local_page_key)

    raise NotionPlanningError(
        f"Unsupported synthesis root block type {existing_page_mention.root_block_type!r}"
    )


def _render_synthesis_page_blocks(synthesis_page: SynthesisPageMetadata) -> list[dict[str, Any]]:
    blocks = [heading_block(level=2, text=SYNTHESIS_PAGE_SOURCES_HEADING)]

    if synthesis_page.sources:
        for source in synthesis_page.sources:
            blocks.append(_render_synthesis_source_block(source))
    else:
        blocks.append(paragraph_block(text="No sources recorded."))

    if synthesis_page.summary:
        blocks.append(paragraph_block(text=synthesis_page.summary))

    for line in synthesis_page.lines:
        blocks.append(
            {
                "type": "bulleted_list_item",
                "depth": 0,
                "text": line,
            }
        )

    if not synthesis_page.summary and not synthesis_page.lines:
        blocks.append(paragraph_block(text="No synthesis content yet."))

    return blocks


def _render_synthesis_source_block(source: SynthesisSource) -> dict[str, Any]:
    text = f"{source.source_type}: {source.label}"

    if source.page_key is not None:
        return linked_metadata_bullet_block(text=text, page_key=source.page_key)

    if source.external_url is not None:
        text = f"{text}: {source.external_url}"

    return metadata_bullet_block(text=text)


def _synthesis_page_to_snapshot(synthesis_page: SynthesisPageMetadata) -> dict[str, Any]:
    return {
        "synthesis_key": synthesis_page.synthesis_key,
        "title": synthesis_page.title,
        "summary": synthesis_page.summary,
        "lines": list(synthesis_page.lines),
        "sources": [
            _synthesis_source_to_snapshot(source)
            for source in synthesis_page.sources
        ],
        "notion_page_id": synthesis_page.notion_page_id,
    }


def _synthesis_source_to_snapshot(source: SynthesisSource) -> dict[str, Any]:
    return {
        "source_type": source.source_type,
        "label": source.label,
        "page_key": source.page_key,
        "external_url": source.external_url,
    }


def _synthesis_existing_page_mention_to_snapshot(existing_page_mention: ExistingSynthesisPageMention) -> dict[str, Any]:
    return {
        "mention_key": existing_page_mention.mention_key,
        "title": existing_page_mention.title,
        "notion_page_id": existing_page_mention.notion_page_id,
        "display_order": existing_page_mention.display_order,
        "root_block_type": existing_page_mention.root_block_type,
    }


def _synthesis_page_from_snapshot(snapshot: dict[str, Any]) -> SynthesisPageMetadata:
    return SynthesisPageMetadata(
        synthesis_key=snapshot["synthesis_key"],
        title=snapshot["title"],
        summary=snapshot.get("summary", ""),
        lines=list(snapshot.get("lines", [])),
        sources=[
            _synthesis_source_from_snapshot(source_snapshot)
            for source_snapshot in snapshot.get("sources", [])
        ],
        notion_page_id=snapshot.get("notion_page_id"),
    )


def _synthesis_existing_page_mention_from_snapshot(snapshot: dict[str, Any]) -> ExistingSynthesisPageMention:
    return ExistingSynthesisPageMention(
        mention_key=snapshot["mention_key"],
        title=snapshot["title"],
        notion_page_id=snapshot["notion_page_id"],
        display_order=snapshot.get("display_order", 0),
        root_block_type=snapshot.get("root_block_type", SYNTHESIS_ROOT_PAGE_MENTION_BLOCK),
    )


def _synthesis_source_from_snapshot(snapshot: dict[str, Any]) -> SynthesisSource:
    return SynthesisSource(
        source_type=snapshot["source_type"],
        label=snapshot["label"],
        page_key=snapshot.get("page_key"),
        external_url=snapshot.get("external_url"),
    )
