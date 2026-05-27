"""Write intents emitted by tracker metadata objects."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class NotionWriteIntent:
    """Notion write planner input."""

    operation_key: str
    operation_name: str
    target_page_key: str | None
    arguments: dict[str, Any]


class NotionPlanningError(ValueError):
    """Raised when a write intent cannot become an exact Notion call."""
