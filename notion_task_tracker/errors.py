"""Shared tracker exceptions."""


class NotionPlanningError(ValueError):
    """Raised when tracker state cannot produce a valid Notion operation."""
