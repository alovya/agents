"""External artefact links referenced by Notion pages."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class ExternalLink:
    """Link from an internal page to an external artefact."""

    label: str
    external_url: str


def external_link_to_snapshot(link: ExternalLink) -> dict[str, Any]:
    return {
        "label": link.label,
        "external_url": link.external_url,
    }


def external_link_from_snapshot(snapshot: dict[str, Any]) -> ExternalLink:
    return ExternalLink(
        label=snapshot["label"],
        external_url=snapshot["external_url"],
    )
