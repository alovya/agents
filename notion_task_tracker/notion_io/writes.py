"""Write intents emitted by tracker metadata objects."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from notion_task_tracker.errors import NotionPlanningError


@dataclass(frozen=True)
class NotionWriteIntent:
    """Notion write planner input."""

    operation_key: str
    operation_name: str
    target_page_key: str | None
    arguments: dict[str, Any]
