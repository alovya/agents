"""Compile write intents into serialisable Notion MCP tool calls."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from notion_task_tracker.common import (
    NotionPageRegistry,
    NotionMcpCallPlanningError,
    NotionWriteIntent,
    write_json_snapshot,
)
from notion_task_tracker.notion_enhanced_markdown import NotionMarkdownRenderer


@dataclass(frozen=True)
class NotionMcpToolCall:
    """One exact Notion MCP tool call plus local bookkeeping metadata."""

    operation_key: str
    tool_name: str
    arguments: dict[str, Any]
    captures_page_key: str | None = None

    @classmethod
    def from_snapshot(cls, snapshot: dict[str, Any]) -> "NotionMcpToolCall":
        return cls(
            operation_key=snapshot["operation_key"],
            tool_name=snapshot["tool_name"],
            arguments=dict(snapshot["arguments"]),
            captures_page_key=snapshot.get("captures_page_key"),
        )

    def to_snapshot(self) -> dict[str, Any]:
        return {
            "operation_key": self.operation_key,
            "tool_name": self.tool_name,
            "arguments": self.arguments,
            "captures_page_key": self.captures_page_key,
        }


@dataclass(frozen=True)
class BlockedNotionMcpOperation:
    """Intent that needs page ids or richer intent arguments before planning."""

    operation_key: str
    reason: str

    @classmethod
    def from_snapshot(cls, snapshot: dict[str, Any]) -> "BlockedNotionMcpOperation":
        return cls(
            operation_key=snapshot["operation_key"],
            reason=snapshot["reason"],
        )

    def to_snapshot(self) -> dict[str, Any]:
        return {
            "operation_key": self.operation_key,
            "reason": self.reason,
        }


@dataclass
class NotionMcpCallPlan:
    """Ordered MCP tool calls and any deterministic blockers."""

    calls: list[NotionMcpToolCall] = field(default_factory=list)
    blocked_operations: list[BlockedNotionMcpOperation] = field(default_factory=list)

    @classmethod
    def from_snapshot(cls, snapshot: dict[str, Any]) -> "NotionMcpCallPlan":
        return cls(
            calls=[
                NotionMcpToolCall.from_snapshot(call_snapshot)
                for call_snapshot in snapshot.get("calls", [])
            ],
            blocked_operations=[
                BlockedNotionMcpOperation.from_snapshot(blocked_snapshot)
                for blocked_snapshot in snapshot.get("blocked_operations", [])
            ],
        )

    def write_json(self, output_path: str | Path) -> None:
        write_json_snapshot(self.to_snapshot(), output_path)

    def to_snapshot(self) -> dict[str, Any]:
        return {
            "calls": [
                call.to_snapshot()
                for call in self.calls
            ],
            "blocked_operations": [
                blocked_operation.to_snapshot()
                for blocked_operation in self.blocked_operations
            ],
        }


class NotionMcpCallPlanner:
    """Turns abstract write intents into exact Notion MCP tool calls."""

    def __init__(self, page_registry: NotionPageRegistry):
        self.page_registry = page_registry
        self.markdown_renderer = NotionMarkdownRenderer(page_registry)

    def compile_write_intents(self, write_intents: list[NotionWriteIntent]) -> NotionMcpCallPlan:
        call_plan = NotionMcpCallPlan()

        for write_intent in write_intents:
            intent_call_plan = self.compile_write_intent(write_intent)
            call_plan.calls.extend(intent_call_plan.calls)
            call_plan.blocked_operations.extend(intent_call_plan.blocked_operations)

        return call_plan

    def compile_write_intent(self, write_intent: NotionWriteIntent) -> NotionMcpCallPlan:
        try:
            return self._compile_supported_write_intent(write_intent)
        except KeyError as error:
            return self._blocked_plan(
                write_intent.operation_key,
                f"Intent is missing required argument {error.args[0]!r}",
            )
        except NotionMcpCallPlanningError as error:
            return self._blocked_plan(write_intent.operation_key, str(error))

    def _compile_supported_write_intent(self, write_intent: NotionWriteIntent) -> NotionMcpCallPlan:
        if write_intent.operation_name == "create_page":
            return self._compile_create_page_intent(write_intent)

        if write_intent.operation_name == "replace_page_children":
            return self._compile_replace_page_children_intent(write_intent)

        if write_intent.operation_name == "update_page_properties":
            return self._compile_update_page_properties_intent(write_intent)

        if write_intent.operation_name == "update_timeline_log":
            return self._compile_timeline_log_update_intent(write_intent)

        if write_intent.operation_name == "append_miscellaneous_context":
            return self._compile_miscellaneous_context_append_intent(write_intent)

        if write_intent.operation_name == "create_synthesis_page":
            return self._compile_synthesis_page_creation_intent(write_intent)

        return self._blocked_plan(
            write_intent.operation_key,
            f"Unsupported write-intent operation {write_intent.operation_name!r}",
        )

    def _compile_create_page_intent(self, write_intent: NotionWriteIntent) -> NotionMcpCallPlan:
        arguments = write_intent.arguments
        return self._plan_create_page(
            operation_key=write_intent.operation_key,
            local_page_key=arguments["local_page_key"],
            title=arguments["title"],
            parent_page_key=arguments.get("parent_page_key"),
            blocks=arguments.get("blocks"),
        )

    def _compile_replace_page_children_intent(self, write_intent: NotionWriteIntent) -> NotionMcpCallPlan:
        target_page_key = self._required_target_page_key(write_intent)
        return self._plan_replace_page_content(
            operation_key=write_intent.operation_key,
            target_page_key=target_page_key,
            blocks=write_intent.arguments["blocks"],
        )

    def _compile_update_page_properties_intent(self, write_intent: NotionWriteIntent) -> NotionMcpCallPlan:
        try:
            page_id = self.page_registry.page_id(self._required_target_page_key(write_intent))
        except NotionMcpCallPlanningError as error:
            return self._blocked_plan(write_intent.operation_key, str(error))

        return NotionMcpCallPlan(
            calls=[
                NotionMcpToolCall(
                    operation_key=write_intent.operation_key,
                    tool_name="notion-update-page",
                    arguments={
                        "page_id": page_id,
                        "command": "update_properties",
                        "properties": _notion_mcp_page_properties(write_intent.arguments["properties"]),
                    },
                )
            ]
        )

    def _compile_timeline_log_update_intent(self, write_intent: NotionWriteIntent) -> NotionMcpCallPlan:
        if "existing_blocks" in write_intent.arguments:
            return self._plan_insert_after_existing_timeline_heading(
                operation_key=write_intent.operation_key,
                target_page_key=self._required_target_page_key(write_intent),
                timeline_heading=write_intent.arguments["existing_timeline_heading"],
                append_blocks=self._required_blocks(write_intent, "append_blocks"),
            )

        return self._plan_prepend_timeline_entry(
            operation_key=write_intent.operation_key,
            target_page_key=self._required_target_page_key(write_intent),
            timeline_log_heading=write_intent.arguments["timeline_log_heading"],
            blocks=self._required_blocks(write_intent, "blocks"),
        )

    def _compile_miscellaneous_context_append_intent(self, write_intent: NotionWriteIntent) -> NotionMcpCallPlan:
        dated_page = write_intent.arguments["dated_page"]
        dated_page_key = dated_page["local_page_key"]

        if not self._page_has_id(dated_page_key):
            return self._plan_miscellaneous_page_creation_before_refresh(write_intent, dated_page)

        return self._plan_target_and_root_replacement(
            operation_key=write_intent.operation_key,
            target_page_key=dated_page_key,
            target_blocks=self._required_blocks(write_intent, "dated_page_blocks"),
            root_page_key=write_intent.arguments["root_page_key"],
            root_blocks=write_intent.arguments.get("root_page_blocks"),
        )

    def _compile_synthesis_page_creation_intent(self, write_intent: NotionWriteIntent) -> NotionMcpCallPlan:
        synthesis_page = write_intent.arguments["page"]
        synthesis_page_key = synthesis_page["local_page_key"]

        if not self._page_has_id(synthesis_page_key):
            return self._plan_synthesis_page_creation_before_root_refresh(write_intent, synthesis_page)

        return self._plan_target_and_root_replacement(
            operation_key=write_intent.operation_key,
            target_page_key=synthesis_page_key,
            target_blocks=self._required_blocks(write_intent, "blocks"),
            root_page_key=write_intent.arguments["root_page_key"],
            root_blocks=write_intent.arguments.get("root_page_blocks"),
        )

    def _plan_miscellaneous_page_creation_before_refresh(
        self,
        write_intent: NotionWriteIntent,
        dated_page: dict[str, Any],
    ) -> NotionMcpCallPlan:
        create_plan = self._plan_create_page(
            operation_key=f"create:{dated_page['local_page_key']}",
            local_page_key=dated_page["local_page_key"],
            title=dated_page["title"],
            parent_page_key=dated_page.get("parent_page_key"),
            blocks=write_intent.arguments["dated_page_blocks"],
        )
        create_plan.blocked_operations.append(
            BlockedNotionMcpOperation(
                operation_key=write_intent.operation_key,
                reason=(
                    f"Capture page id for {dated_page['local_page_key']!r}, "
                    "then rerun this intent to refresh the dated page and root page"
                ),
            )
        )
        return create_plan

    def _plan_synthesis_page_creation_before_root_refresh(
        self,
        write_intent: NotionWriteIntent,
        synthesis_page: dict[str, Any],
    ) -> NotionMcpCallPlan:
        create_plan = self._plan_create_page(
            operation_key=f"create:{synthesis_page['local_page_key']}",
            local_page_key=synthesis_page["local_page_key"],
            title=synthesis_page["title"],
            parent_page_key=synthesis_page.get("parent_page_key"),
            blocks=write_intent.arguments["blocks"],
        )
        create_plan.blocked_operations.append(
            BlockedNotionMcpOperation(
                operation_key=write_intent.operation_key,
                reason=(
                    f"Capture page id for {synthesis_page['local_page_key']!r}, "
                    "then rerun this intent to refresh the synthesis root page"
                ),
            )
        )
        return create_plan

    def _plan_target_and_root_replacement(
        self,
        operation_key: str,
        target_page_key: str,
        target_blocks: list[dict[str, Any]],
        root_page_key: str,
        root_blocks: list[dict[str, Any]] | None,
    ) -> NotionMcpCallPlan:
        call_plan = self._plan_replace_page_content(
            operation_key=f"replace:{target_page_key}:{operation_key}",
            target_page_key=target_page_key,
            blocks=target_blocks,
        )

        if root_blocks is not None:
            root_plan = self._plan_replace_page_content(
                operation_key=f"replace:{root_page_key}:{operation_key}",
                target_page_key=root_page_key,
                blocks=root_blocks,
            )
            call_plan.calls.extend(root_plan.calls)
            call_plan.blocked_operations.extend(root_plan.blocked_operations)

        return call_plan

    def _plan_create_page(
        self,
        operation_key: str,
        local_page_key: str,
        title: str,
        parent_page_key: str | None,
        blocks: list[dict[str, Any]] | None,
    ) -> NotionMcpCallPlan:
        try:
            arguments = self._create_page_arguments(title, parent_page_key, blocks)
        except NotionMcpCallPlanningError as error:
            return self._blocked_plan(operation_key, str(error))

        return NotionMcpCallPlan(
            calls=[
                NotionMcpToolCall(
                    operation_key=operation_key,
                    tool_name="notion-create-pages",
                    arguments=arguments,
                    captures_page_key=local_page_key,
                )
            ]
        )

    def _create_page_arguments(
        self,
        title: str,
        parent_page_key: str | None,
        blocks: list[dict[str, Any]] | None,
    ) -> dict[str, Any]:
        page = {
            "properties": {
                "title": title,
            },
            "content": self.markdown_renderer.render_blocks(blocks or []),
        }
        arguments = {"pages": [page]}

        if parent_page_key is not None:
            arguments["parent"] = {
                "page_id": self.page_registry.page_id(parent_page_key),
                "type": "page_id",
            }

        return arguments

    def _plan_replace_page_content(
        self,
        operation_key: str,
        target_page_key: str,
        blocks: list[dict[str, Any]],
    ) -> NotionMcpCallPlan:
        try:
            page_id = self.page_registry.page_id(target_page_key)
            content = self.markdown_renderer.render_blocks(blocks)
        except NotionMcpCallPlanningError as error:
            return self._blocked_plan(operation_key, str(error))

        return NotionMcpCallPlan(
            calls=[
                NotionMcpToolCall(
                    operation_key=operation_key,
                    tool_name="notion-update-page",
                    arguments={
                        "page_id": page_id,
                        "command": "replace_content",
                        "new_str": content,
                    },
                )
            ]
        )

    def _plan_prepend_timeline_entry(
        self,
        operation_key: str,
        target_page_key: str,
        timeline_log_heading: str,
        blocks: list[dict[str, Any]],
    ) -> NotionMcpCallPlan:
        try:
            page_id = self.page_registry.page_id(target_page_key)
            heading_content = self.markdown_renderer.render_blocks([
                {"type": "heading_2", "text": timeline_log_heading}
            ])
            content = self.markdown_renderer.render_blocks(blocks)
        except NotionMcpCallPlanningError as error:
            return self._blocked_plan(operation_key, str(error))

        return NotionMcpCallPlan(
            calls=[
                NotionMcpToolCall(
                    operation_key=operation_key,
                    tool_name="notion-update-page",
                    arguments={
                        "page_id": page_id,
                        "command": "update_content",
                        "content_updates": [
                            {
                                "old_str": heading_content,
                                "new_str": f"{heading_content}\n{content}",
                            }
                        ],
                    },
                )
            ]
        )

    def _plan_insert_after_existing_timeline_heading(
        self,
        operation_key: str,
        target_page_key: str,
        timeline_heading: str,
        append_blocks: list[dict[str, Any]],
    ) -> NotionMcpCallPlan:
        try:
            page_id = self.page_registry.page_id(target_page_key)
            heading_content = self.markdown_renderer.render_blocks([{"type": "heading_3", "text": timeline_heading}])
            appended_content = self.markdown_renderer.render_blocks(append_blocks)
        except NotionMcpCallPlanningError as error:
            return self._blocked_plan(operation_key, str(error))

        return NotionMcpCallPlan(
            calls=[
                NotionMcpToolCall(
                    operation_key=operation_key,
                    tool_name="notion-update-page",
                    arguments={
                        "page_id": page_id,
                        "command": "update_content",
                        "content_updates": [
                            {
                                "old_str": heading_content,
                                "new_str": f"{heading_content}\n{appended_content}",
                            }
                        ],
                    },
                )
            ]
        )

    def _page_has_id(self, local_page_key: str) -> bool:
        try:
            self.page_registry.page_id(local_page_key)
        except NotionMcpCallPlanningError:
            return False

        return True

    def _required_target_page_key(self, write_intent: NotionWriteIntent) -> str:
        if write_intent.target_page_key is None:
            raise NotionMcpCallPlanningError(f"Intent {write_intent.operation_key!r} has no target page key")

        return write_intent.target_page_key

    def _required_blocks(self, write_intent: NotionWriteIntent, argument_key: str) -> list[dict[str, Any]]:
        if argument_key not in write_intent.arguments:
            raise NotionMcpCallPlanningError(
                f"Intent {write_intent.operation_key!r} has no {argument_key!r} blocks"
            )

        return write_intent.arguments[argument_key]

    def _blocked_plan(self, operation_key: str, reason: str) -> NotionMcpCallPlan:
        return NotionMcpCallPlan(
            blocked_operations=[
                BlockedNotionMcpOperation(
                    operation_key=operation_key,
                    reason=reason,
                )
            ]
        )


def _notion_mcp_page_properties(properties: dict[str, Any]) -> dict[str, Any]:
    if "title" in properties:
        return {
            **properties,
            "title": properties["title"],
        }

    return dict(properties)
