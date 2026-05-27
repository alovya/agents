"""Synthesis notes metadata and flat subpage planning."""

from __future__ import annotations

from dataclasses import dataclass, field
from html.parser import HTMLParser
from typing import Any

from notion_task_tracker.errors import NotionPlanningError
from notion_task_tracker.fixed_pages import (
    SYNTHESIS_NOTES_PAGE_LOCAL_KEY,
    SYNTHESIS_NOTES_PAGE_TITLE,
)
from notion_task_tracker.notion_ids import canonical_notion_page_id, notion_page_id_from_url
from notion_task_tracker.tracked_pages import (
    TrackedPage,
    fixed_tracked_page_from_tracker_state,
    tracked_page_to_tracker_state,
    validate_fixed_tracked_page,
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

    page: TrackedPage = field(
        default_factory=lambda: TrackedPage(
            local_page_key=SYNTHESIS_NOTES_PAGE_LOCAL_KEY,
            title=SYNTHESIS_NOTES_PAGE_TITLE,
        )
    )
    existing_page_mentions: dict[str, ExistingSynthesisPageMention] = field(default_factory=dict)
    pages: dict[str, SynthesisPageMetadata] = field(default_factory=dict)

    @classmethod
    def from_tracker_state(cls, tracker_state: dict[str, Any]) -> SynthesisNotesMetadata:
        synthesis_notes = cls(
            page=fixed_tracked_page_from_tracker_state(
                tracker_state["page"],
                local_page_key=SYNTHESIS_NOTES_PAGE_LOCAL_KEY,
                title=SYNTHESIS_NOTES_PAGE_TITLE,
            )
        )
        synthesis_notes.pages = {
            synthesis_key: _synthesis_page_from_tracker_state(page_state)
            for synthesis_key, page_state in tracker_state.get("pages", {}).items()
        }
        synthesis_notes.existing_page_mentions = {
            mention_key: _synthesis_existing_page_mention_from_tracker_state(page_state)
            for mention_key, page_state in tracker_state.get("existing_page_mentions", {}).items()
        }
        synthesis_notes.validate()
        return synthesis_notes

    def create_synthesis_page(self, synthesis_page: SynthesisPageMetadata) -> SynthesisPageMetadata:
        self.pages[synthesis_page.synthesis_key] = synthesis_page
        self.validate()
        return synthesis_page

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

    def validate(self) -> None:
        validate_fixed_tracked_page(
            page=self.page,
            expected_local_page_key=SYNTHESIS_NOTES_PAGE_LOCAL_KEY,
            expected_title=SYNTHESIS_NOTES_PAGE_TITLE,
        )
        self._validate_page_keys_match_page_values()
        self._validate_root_block_types()

    def to_tracker_state(self) -> dict[str, Any]:
        return {
            "page": tracked_page_to_tracker_state(self.page),
            "existing_page_mentions": {
                mention_key: _synthesis_existing_page_mention_to_tracker_state(existing_page_mention)
                for mention_key, existing_page_mention in sorted(self.existing_page_mentions.items())
            },
            "pages": {
                synthesis_key: _synthesis_page_to_tracker_state(synthesis_page)
                for synthesis_key, synthesis_page in sorted(self.pages.items())
            },
        }

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


def _synthesis_page_to_tracker_state(synthesis_page: SynthesisPageMetadata) -> dict[str, Any]:
    return {
        "synthesis_key": synthesis_page.synthesis_key,
        "title": synthesis_page.title,
        "summary": synthesis_page.summary,
        "lines": list(synthesis_page.lines),
        "sources": [
            _synthesis_source_to_tracker_state(source)
            for source in synthesis_page.sources
        ],
        "notion_page_id": synthesis_page.notion_page_id,
    }


def _synthesis_source_to_tracker_state(source: SynthesisSource) -> dict[str, Any]:
    return {
        "source_type": source.source_type,
        "label": source.label,
        "page_key": source.page_key,
        "external_url": source.external_url,
    }


def _synthesis_existing_page_mention_to_tracker_state(existing_page_mention: ExistingSynthesisPageMention) -> dict[str, Any]:
    return {
        "mention_key": existing_page_mention.mention_key,
        "title": existing_page_mention.title,
        "notion_page_id": existing_page_mention.notion_page_id,
        "display_order": existing_page_mention.display_order,
        "root_block_type": existing_page_mention.root_block_type,
    }


def _synthesis_page_from_tracker_state(tracker_state: dict[str, Any]) -> SynthesisPageMetadata:
    return SynthesisPageMetadata(
        synthesis_key=tracker_state["synthesis_key"],
        title=tracker_state["title"],
        summary=tracker_state.get("summary", ""),
        lines=list(tracker_state.get("lines", [])),
        sources=[
            _synthesis_source_from_tracker_state(source_state)
            for source_state in tracker_state.get("sources", [])
        ],
        notion_page_id=tracker_state.get("notion_page_id"),
    )


def _synthesis_existing_page_mention_from_tracker_state(tracker_state: dict[str, Any]) -> ExistingSynthesisPageMention:
    return ExistingSynthesisPageMention(
        mention_key=tracker_state["mention_key"],
        title=tracker_state["title"],
        notion_page_id=tracker_state["notion_page_id"],
        display_order=tracker_state.get("display_order", 0),
        root_block_type=tracker_state.get("root_block_type", SYNTHESIS_ROOT_PAGE_MENTION_BLOCK),
    )


def _synthesis_source_from_tracker_state(tracker_state: dict[str, Any]) -> SynthesisSource:
    return SynthesisSource(
        source_type=tracker_state["source_type"],
        label=tracker_state["label"],
        page_key=tracker_state.get("page_key"),
        external_url=tracker_state.get("external_url"),
    )
