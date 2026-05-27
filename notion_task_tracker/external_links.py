"""External artefact links referenced by Notion pages."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class ExternalLink:
    """Link from an internal page to an external artefact."""

    label: str
    external_url: str


def external_link_to_tracker_state(link: ExternalLink) -> dict[str, Any]:
    return {
        "label": link.label,
        "external_url": link.external_url,
    }


def external_link_from_tracker_state(tracker_state: dict[str, Any]) -> ExternalLink:
    return ExternalLink(
        label=tracker_state["label"],
        external_url=tracker_state["external_url"],
    )
