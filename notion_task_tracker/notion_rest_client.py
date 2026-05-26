"""Notion REST client."""

from __future__ import annotations

import asyncio
import json
import os
import re
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from notion_task_tracker.commands import CommandResult
from notion_task_tracker.common import NotionPageRegistry, NotionWriteIntent, canonical_notion_page_id, notion_page_id_from_url
from notion_task_tracker.notion_client import CreatedTaskDatabasePage, NotionWriteExecutionResult
from notion_task_tracker.tasks.database import (
    TASK_DATABASE_DATA_SOURCE_ID,
    TASK_DATABASE_PARENT_PROPERTY,
    TASK_DATABASE_PRIORITY_PROPERTY,
    TASK_DATABASE_STATUS_PROPERTY,
    TASK_DATABASE_TICKET_ID_PROPERTY,
    TASK_DATABASE_TITLE_PROPERTY,
    task_database_data_source_url_from_tracker_state,
    task_database_query_for_tracker_state,
    task_database_view_url_from_tracker_state,
)


DEFAULT_NOTION_API_BASE_URL = "https://api.notion.com"
DEFAULT_NOTION_API_VERSION = "2026-03-11"
_DATE_MENTION_PATTERN = re.compile(r'<mention-date\s+[^>]*start="([^"]+)"[^>]*/>')
_PAGE_MENTION_PATTERN = re.compile(r'<mention-page\s+[^>]*url="([^"]+)"[^>]*/>')


class NotionRestClient:
    def __init__(self, access_token: str, base_url: str, notion_version: str) -> None:
        self.access_token = access_token
        self.base_url = base_url.rstrip("/")
        self.notion_version = notion_version

    @classmethod
    def from_credentials_path(cls, credentials_path: Path) -> "NotionRestClient":
        return cls(
            access_token=_notion_rest_access_token_from_environment_or_path(credentials_path),
            base_url=DEFAULT_NOTION_API_BASE_URL,
            notion_version=DEFAULT_NOTION_API_VERSION,
        )

    async def fetch_task_page_content(self, page_id: str) -> str:
        page, blocks = await asyncio.gather(
            self.fetch_page(page_id),
            self.fetch_page_blocks(page_id),
        )
        return _fetched_database_page_content(page, blocks)

    async def fetch_page(self, page_id: str) -> dict[str, Any]:
        return await self._send_json("GET", f"/v1/pages/{page_id}", None)

    async def fetch_page_blocks(self, page_id: str) -> list[dict[str, Any]]:
        return await self._fetch_all_block_children(page_id)

    async def query_data_source(self, data_source_url: str, query: str) -> list[dict[str, Any]]:
        return await self.query_data_source_id(_data_source_id_from_url(data_source_url))

    async def query_database_view(self, view_url: str) -> list[dict[str, Any]]:
        return await self.query_data_source_id(TASK_DATABASE_DATA_SOURCE_ID)

    async def query_task_database_rows(self, tracker_state: dict[str, Any]) -> list[dict[str, Any]]:
        view_url = task_database_view_url_from_tracker_state(tracker_state)
        if view_url is not None:
            return await self.query_database_view(view_url)

        return await self.query_data_source(
            data_source_url=task_database_data_source_url_from_tracker_state(tracker_state),
            query=task_database_query_for_tracker_state(tracker_state),
        )

    async def query_data_source_id(self, data_source_id: str) -> list[dict[str, Any]]:
        rows = []
        next_cursor = None

        while True:
            body = {"page_size": 100}
            if next_cursor:
                body["start_cursor"] = next_cursor
            response = await self._send_json("POST", f"/v1/data_sources/{data_source_id}/query", body)
            rows.extend(_task_database_rows_from_rest_pages(response.get("results", [])))
            if not response.get("has_more"):
                return rows
            next_cursor = response.get("next_cursor")

    async def execute_write_intent(
        self,
        write_intent: NotionWriteIntent,
        page_registry: NotionPageRegistry,
    ) -> dict[str, Any]:
        if write_intent.operation_name == "create_page":
            return await self._execute_create_page_intent(write_intent, page_registry)
        if write_intent.operation_name == "replace_page_children":
            return await self._execute_replace_page_children_intent(write_intent, page_registry)
        if write_intent.operation_name == "update_page_properties":
            return await self._execute_update_page_properties_intent(write_intent, page_registry)
        if write_intent.operation_name == "update_timeline_log":
            return await self._execute_timeline_log_update_intent(write_intent, page_registry)
        if write_intent.operation_name == "append_miscellaneous_context":
            return await self._execute_miscellaneous_context_append_intent(write_intent, page_registry)
        if write_intent.operation_name == "create_synthesis_page":
            return await self._execute_synthesis_page_creation_intent(write_intent, page_registry)
        raise ValueError(f"Notion REST client cannot execute write intent {write_intent.operation_name!r}")

    async def create_database_page(
        self,
        data_source_id: str,
        properties: dict[str, Any],
        blocks: list[dict[str, Any]],
    ) -> dict[str, Any]:
        return await self.create_page(
            parent={"type": "data_source_id", "data_source_id": data_source_id},
            properties=properties,
            blocks=blocks,
        )

    async def create_task_database_page(
        self,
        data_source_id: str,
        properties: dict[str, Any],
        blocks: list[dict[str, Any]],
        content: str,
        operation_key: str,
    ) -> CreatedTaskDatabasePage:
        del content
        created_page = await self.create_database_page(
            data_source_id=data_source_id,
            properties=properties,
            blocks=blocks,
        )
        return CreatedTaskDatabasePage(
            notion_page_id=created_page["id"],
            operation_keys=[operation_key],
        )

    async def update_task_database_page_title(
        self,
        page_id: str,
        title_property: str,
        title: str,
        operation_key: str,
    ) -> str:
        await self.update_page_properties(
            page_id=page_id,
            properties={title_property or TASK_DATABASE_TITLE_PROPERTY: title},
        )
        return operation_key

    async def execute_command_result(self, command_result: CommandResult) -> NotionWriteExecutionResult:
        if command_result.page_registry is None:
            raise ValueError("REST write execution requires a page registry")

        completed_operation_keys = []
        captured_page_ids = {}
        for write_intent in command_result.write_intents:
            write_result = await self.execute_write_intent(write_intent, command_result.page_registry)
            completed_operation_keys.append(write_result["operation_key"])
            if write_result.get("captured_page_key") is not None:
                captured_page_ids[write_result["captured_page_key"]] = write_result["captured_page_id"]

        return NotionWriteExecutionResult(
            completed_operation_keys=completed_operation_keys,
            captured_page_ids=captured_page_ids,
        )

    async def _execute_create_page_intent(
        self,
        write_intent: NotionWriteIntent,
        page_registry: NotionPageRegistry,
    ) -> dict[str, Any]:
        arguments = write_intent.arguments
        created_page = await self.create_page(
            parent=_rest_parent_from_page_key(arguments.get("parent_page_key"), page_registry),
            properties={"title": arguments["title"]},
            blocks=arguments.get("blocks", []),
        )
        return _write_result(write_intent.operation_key, arguments["local_page_key"], created_page)

    async def _execute_replace_page_children_intent(
        self,
        write_intent: NotionWriteIntent,
        page_registry: NotionPageRegistry,
    ) -> dict[str, Any]:
        await self.replace_page_content(
            page_id=page_registry.page_id(_required_target_page_key(write_intent)),
            blocks=write_intent.arguments["blocks"],
        )
        return _write_result(write_intent.operation_key)

    async def _execute_update_page_properties_intent(
        self,
        write_intent: NotionWriteIntent,
        page_registry: NotionPageRegistry,
    ) -> dict[str, Any]:
        updated_page = await self.update_page_properties(
            page_id=page_registry.page_id(_required_target_page_key(write_intent)),
            properties=write_intent.arguments["properties"],
        )
        return _write_result(write_intent.operation_key, None, updated_page)

    async def _execute_timeline_log_update_intent(
        self,
        write_intent: NotionWriteIntent,
        page_registry: NotionPageRegistry,
    ) -> dict[str, Any]:
        page_id = page_registry.page_id(_required_target_page_key(write_intent))
        arguments = write_intent.arguments
        if "existing_blocks" in arguments:
            await self.insert_blocks_after_matching_block(
                page_id=page_id,
                anchor_block=arguments["existing_blocks"][0],
                blocks=arguments["append_blocks"],
            )
        else:
            await self.insert_blocks_after_matching_block(
                page_id=page_id,
                anchor_block={"type": "heading_2", "text": arguments["timeline_log_heading"]},
                blocks=arguments["blocks"],
            )
        return _write_result(write_intent.operation_key)

    async def _execute_miscellaneous_context_append_intent(
        self,
        write_intent: NotionWriteIntent,
        page_registry: NotionPageRegistry,
    ) -> dict[str, Any]:
        dated_page = write_intent.arguments["dated_page"]
        dated_page_key = dated_page["local_page_key"]
        if not _page_has_id(page_registry, dated_page_key):
            return await self._execute_create_page_intent(
                NotionWriteIntent(
                    operation_key=f"create:{dated_page_key}",
                    operation_name="create_page",
                    target_page_key=None,
                    arguments={
                        "local_page_key": dated_page_key,
                        "title": dated_page["title"],
                        "parent_page_key": dated_page.get("parent_page_key"),
                        "blocks": write_intent.arguments["dated_page_blocks"],
                    },
                ),
                page_registry,
            )

        await self.replace_page_content(page_registry.page_id(dated_page_key), write_intent.arguments["dated_page_blocks"])
        if write_intent.arguments.get("root_page_blocks") is not None:
            await self.replace_page_content(
                page_registry.page_id(write_intent.arguments["root_page_key"]),
                write_intent.arguments["root_page_blocks"],
            )
        return _write_result(write_intent.operation_key)

    async def _execute_synthesis_page_creation_intent(
        self,
        write_intent: NotionWriteIntent,
        page_registry: NotionPageRegistry,
    ) -> dict[str, Any]:
        synthesis_page = write_intent.arguments["page"]
        synthesis_page_key = synthesis_page["local_page_key"]
        if not _page_has_id(page_registry, synthesis_page_key):
            return await self._execute_create_page_intent(
                NotionWriteIntent(
                    operation_key=f"create:{synthesis_page_key}",
                    operation_name="create_page",
                    target_page_key=None,
                    arguments={
                        "local_page_key": synthesis_page_key,
                        "title": synthesis_page["title"],
                        "parent_page_key": synthesis_page.get("parent_page_key"),
                        "blocks": write_intent.arguments["blocks"],
                    },
                ),
                page_registry,
            )

        await self.replace_page_content(page_registry.page_id(synthesis_page_key), write_intent.arguments["blocks"])
        if write_intent.arguments.get("root_page_blocks") is not None:
            await self.replace_page_content(
                page_registry.page_id(write_intent.arguments["root_page_key"]),
                write_intent.arguments["root_page_blocks"],
            )
        return _write_result(write_intent.operation_key)

    async def create_page(
        self,
        parent: dict[str, Any],
        properties: dict[str, Any],
        blocks: list[dict[str, Any]],
    ) -> dict[str, Any]:
        return await self._send_json(
            "POST",
            "/v1/pages",
            {
                "parent": parent,
                "properties": _rest_database_properties(properties),
                "children": _rest_blocks_from_tracker_blocks(blocks),
            },
        )

    async def update_page_properties(self, page_id: str, properties: dict[str, Any]) -> dict[str, Any]:
        return await self._send_json(
            "PATCH",
            f"/v1/pages/{page_id}",
            {"properties": _rest_database_properties(properties)},
        )

    async def replace_page_content(self, page_id: str, blocks: list[dict[str, Any]]) -> None:
        existing_blocks = await self._fetch_all_block_children(page_id)
        for block in existing_blocks:
            await self._archive_block(block["id"])
        await self._append_blocks(page_id, _rest_blocks_from_tracker_blocks(blocks))

    async def insert_blocks_after_matching_block(
        self,
        page_id: str,
        anchor_block: dict[str, Any],
        blocks: list[dict[str, Any]],
    ) -> None:
        page_blocks = await self._fetch_all_block_children(page_id)
        matching_block = _find_matching_top_level_block(page_blocks, anchor_block)
        if matching_block is None:
            raise ValueError(f"Could not find Notion block matching {anchor_block!r}")
        await self._append_blocks(
            page_id,
            _rest_blocks_from_tracker_blocks(blocks),
            position={"type": "after_block", "after_block": {"id": matching_block["id"]}},
        )

    async def _archive_block(self, block_id: str) -> None:
        await self._send_json("PATCH", f"/v1/blocks/{block_id}", {"in_trash": True})

    async def _append_blocks(
        self,
        parent_block_id: str,
        blocks: list[dict[str, Any]],
        position: dict[str, Any] | None = None,
    ) -> None:
        for block_chunk in _chunks(blocks, 100):
            body = {"children": block_chunk}
            if position is not None:
                body["position"] = position
            await self._send_json("PATCH", f"/v1/blocks/{parent_block_id}/children", body)
            position = None

    async def _fetch_all_block_children(self, block_id: str) -> list[dict[str, Any]]:
        blocks = []
        next_cursor = None

        while True:
            path = f"/v1/blocks/{block_id}/children?page_size=100"
            if next_cursor:
                path = f"{path}&start_cursor={next_cursor}"
            response = await self._send_json("GET", path, None)
            blocks.extend(response.get("results", []))
            if not response.get("has_more"):
                return blocks
            next_cursor = response.get("next_cursor")

    async def _send_json(self, method: str, path: str, body: dict[str, Any] | None) -> dict[str, Any]:
        return await asyncio.to_thread(self._send_json_sync, method, path, body)

    def _send_json_sync(self, method: str, path: str, body: dict[str, Any] | None) -> dict[str, Any]:
        request_body = None if body is None else json.dumps(body).encode("utf-8")
        request = Request(
            url=f"{self.base_url}{path}",
            data=request_body,
            method=method,
            headers=self._headers(body is not None),
        )

        try:
            with urlopen(request, timeout=60) as response:
                response_text = response.read().decode("utf-8")
        except HTTPError as error:
            error_text = error.read().decode("utf-8")
            raise ValueError(_notion_rest_error_message(method, path, error.code, error_text)) from error
        except URLError as error:
            raise ValueError(_notion_rest_error_message(method, path, None, str(error))) from error

        if not response_text:
            return {}

        return json.loads(response_text)

    def _headers(self, has_body: bool) -> dict[str, str]:
        headers = {
            "Authorization": f"Bearer {self.access_token}",
            "Notion-Version": self.notion_version,
        }
        if has_body:
            headers["Content-Type"] = "application/json"
        return headers


def _notion_rest_access_token_from_environment_or_path(credentials_path: Path) -> str:
    access_token = os.environ.get("NOTION_API_KEY")
    if access_token:
        return access_token

    credentials = json.loads(credentials_path.read_text(encoding="utf-8"))
    credential_tokens = [
        value.get("access_token")
        for key, value in credentials.items()
        if key.startswith("Notion|") and isinstance(value, dict)
    ]
    for credential_token in credential_tokens:
        if isinstance(credential_token, str) and credential_token.startswith("ntn_"):
            return credential_token

    raise PermissionError("Set NOTION_API_KEY to the ntn_ Notion integration token before using the REST client.")


def _task_database_rows_from_rest_pages(pages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        _task_database_row_from_rest_page(page)
        for page in pages
    ]


def _task_database_row_from_rest_page(page: dict[str, Any]) -> dict[str, Any]:
    properties = page.get("properties", {})
    return {
        TASK_DATABASE_TITLE_PROPERTY: _plain_property_value(properties.get(TASK_DATABASE_TITLE_PROPERTY)),
        TASK_DATABASE_TICKET_ID_PROPERTY: _plain_property_value(properties.get(TASK_DATABASE_TICKET_ID_PROPERTY)),
        TASK_DATABASE_PRIORITY_PROPERTY: _plain_property_value(properties.get(TASK_DATABASE_PRIORITY_PROPERTY)),
        TASK_DATABASE_STATUS_PROPERTY: _plain_property_value(properties.get(TASK_DATABASE_STATUS_PROPERTY)),
        TASK_DATABASE_PARENT_PROPERTY: json.dumps(_relation_urls_from_property(properties.get(TASK_DATABASE_PARENT_PROPERTY))),
        "url": page.get("url") or f"https://www.notion.so/{canonical_notion_page_id(page['id'])}",
    }


def _rest_database_properties(properties: dict[str, Any]) -> dict[str, Any]:
    rest_properties = {}
    for property_name, property_value in properties.items():
        if property_name in {"title", TASK_DATABASE_TITLE_PROPERTY}:
            rest_properties[property_name] = {"title": _rich_text_items(str(property_value))}
        elif property_name == TASK_DATABASE_PRIORITY_PROPERTY:
            rest_properties[property_name] = {"select": {"name": str(property_value)}}
        elif property_name == TASK_DATABASE_STATUS_PROPERTY:
            rest_properties[property_name] = {"select": {"name": str(property_value)}}
        elif property_name == TASK_DATABASE_PARENT_PROPERTY:
            rest_properties[property_name] = {"relation": _relation_items_from_property_value(property_value)}
        else:
            rest_properties[property_name] = property_value
    return rest_properties


def _plain_property_value(property_value: dict[str, Any] | None) -> str:
    if not property_value:
        return ""

    property_type = property_value.get("type")
    value = property_value.get(property_type)
    if property_type == "title":
        return _plain_text_from_rich_text_items(value)
    if property_type == "rich_text":
        return _plain_text_from_rich_text_items(value)
    if property_type in {"select", "status"}:
        return "" if value is None else str(value.get("name", ""))
    if property_type == "unique_id":
        return str(value.get("number", ""))
    if property_type == "number":
        return "" if value is None else str(value)
    if property_type == "url":
        return "" if value is None else str(value)
    if property_type == "relation":
        return json.dumps(_relation_urls_from_property(property_value))

    return "" if value is None else str(value)


def _relation_urls_from_property(property_value: dict[str, Any] | None) -> list[str]:
    if not property_value or property_value.get("type") != "relation":
        return []

    return [
        f"https://www.notion.so/{canonical_notion_page_id(relation['id'])}"
        for relation in property_value.get("relation", [])
    ]


def _relation_items_from_property_value(property_value: Any) -> list[dict[str, str]]:
    if property_value in {None, ""}:
        return []

    page_urls = json.loads(property_value) if isinstance(property_value, str) else list(property_value)
    return [
        {"id": notion_page_id_from_url(page_url)}
        for page_url in page_urls
    ]


def _fetched_database_page_content(page: dict[str, Any], blocks: list[dict[str, Any]]) -> str:
    return "\n".join(
        [
            "<page>",
            "<properties>",
            json.dumps(_task_database_row_from_rest_page(page)),
            "</properties>",
            "<content>",
            _markdown_from_rest_blocks(blocks),
            "</content>",
            "</page>",
        ]
    )


def _rest_blocks_from_tracker_blocks(blocks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    root_blocks: list[dict[str, Any]] = []
    bullet_stack: list[dict[str, Any]] = []

    for block in blocks:
        rest_block = _rest_block_from_tracker_block(block)
        if block.get("type") != "bulleted_list_item":
            root_blocks.append(rest_block)
            bullet_stack = []
            continue

        depth = int(block.get("depth", 0))
        if depth == 0 or not bullet_stack:
            root_blocks.append(rest_block)
            bullet_stack = [rest_block]
            continue

        parent_block = bullet_stack[min(depth - 1, len(bullet_stack) - 1)]
        parent_block[parent_block["type"]].setdefault("children", []).append(rest_block)
        bullet_stack = bullet_stack[:depth] + [rest_block]

    return root_blocks


def _rest_block_from_tracker_block(block: dict[str, Any]) -> dict[str, Any]:
    block_type = block["type"]
    if block_type.startswith("heading_"):
        return _rest_heading_block(block)
    if block_type == "paragraph":
        return _rest_rich_text_block("paragraph", block["text"], {})
    if block_type == "bulleted_list_item":
        return _rest_rich_text_block(
            "bulleted_list_item",
            _landing_text_with_page_mention(block),
            {"color": block.get("color", "default")},
        )
    if block_type == "toggle":
        return _rest_toggle_block(block)
    if block_type == "page_mention":
        return _rest_rich_text_block("paragraph", _page_mention_text(block), {})
    if block_type == "child_page":
        return _rest_rich_text_block("paragraph", _page_mention_text(block), {})
    raise ValueError(f"Unsupported tracker block type {block_type!r}")


def _rest_heading_block(block: dict[str, Any]) -> dict[str, Any]:
    block_type = block["type"]
    return {
        "object": "block",
        "type": block_type,
        block_type: {
            "rich_text": _rich_text_items(block["text"]),
            "is_toggleable": False,
        },
    }


def _rest_toggle_block(block: dict[str, Any]) -> dict[str, Any]:
    return {
        "object": "block",
        "type": "toggle",
        "toggle": {
            "rich_text": _rich_text_items(block["text"]),
            "children": _rest_blocks_from_tracker_blocks(block.get("children", [])),
        },
    }


def _rest_rich_text_block(block_type: str, text: str, extra_fields: dict[str, Any]) -> dict[str, Any]:
    return {
        "object": "block",
        "type": block_type,
        block_type: {
            "rich_text": _rich_text_items(text),
            **extra_fields,
        },
    }


def _landing_text_with_page_mention(block: dict[str, Any]) -> str:
    text = block["text"]
    if "page_key" not in block:
        return text

    return _page_mention_text(block)


def _page_mention_text(block: dict[str, Any]) -> str:
    page_url = block.get("page_url")
    if page_url is not None:
        return f'<mention-page url="{page_url}"/>'

    page_key = block["page_key"]
    return f"<mention-page page_key=\"{page_key}\"/>"


def _rich_text_items(text: str) -> list[dict[str, Any]]:
    rich_text_items = []
    remaining_text = text

    while remaining_text:
        mention_match = _first_mention_match(remaining_text)
        if mention_match is None:
            rich_text_items.append(_text_item(remaining_text))
            break

        if mention_match.start() > 0:
            rich_text_items.append(_text_item(remaining_text[:mention_match.start()]))
        rich_text_items.append(_mention_item_from_match(mention_match))
        remaining_text = remaining_text[mention_match.end():]

    return rich_text_items or [_text_item("")]


def _first_mention_match(text: str) -> re.Match[str] | None:
    matches = [
        match
        for match in [_DATE_MENTION_PATTERN.search(text), _PAGE_MENTION_PATTERN.search(text)]
        if match is not None
    ]
    if not matches:
        return None
    return min(matches, key=lambda match: match.start())


def _mention_item_from_match(match: re.Match[str]) -> dict[str, Any]:
    if match.re is _DATE_MENTION_PATTERN:
        return {
            "type": "mention",
            "mention": {
                "type": "date",
                "date": {"start": match.group(1)},
            },
        }

    return {
        "type": "mention",
        "mention": {
            "type": "page",
            "page": {"id": notion_page_id_from_url(match.group(1))},
        },
    }


def _text_item(text: str) -> dict[str, Any]:
    return {
        "type": "text",
        "text": {"content": text},
    }


def _markdown_from_rest_blocks(blocks: list[dict[str, Any]]) -> str:
    return "\n".join(
        line
        for block in blocks
        for line in _markdown_lines_from_rest_block(block)
    )


def _markdown_lines_from_rest_block(block: dict[str, Any]) -> list[str]:
    block_type = block.get("type")
    if block_type in {"heading_1", "heading_2", "heading_3"}:
        level = int(block_type.removeprefix("heading_"))
        return [f"{'#' * level} {_plain_text_from_block(block)}"]
    if block_type == "paragraph":
        return [_plain_text_from_block(block)]
    if block_type == "bulleted_list_item":
        return [f"- {_plain_text_from_block(block)}"]
    if block_type == "toggle":
        return [
            "<details>",
            f"<summary>{_plain_text_from_block(block)}</summary>",
            "</details>",
        ]
    return []


def _plain_text_from_block(block: dict[str, Any]) -> str:
    block_type = block["type"]
    return _plain_text_from_rich_text_items(block[block_type].get("rich_text", []))


def _plain_text_from_rich_text_items(rich_text_items: list[dict[str, Any]]) -> str:
    return "".join(_plain_text_from_rich_text_item(rich_text_item) for rich_text_item in rich_text_items)


def _plain_text_from_rich_text_item(rich_text_item: dict[str, Any]) -> str:
    if rich_text_item.get("type") == "mention":
        return _plain_text_from_mention(rich_text_item["mention"])
    if "plain_text" in rich_text_item:
        return str(rich_text_item["plain_text"])
    return str(rich_text_item.get("text", {}).get("content", ""))


def _plain_text_from_mention(mention: dict[str, Any]) -> str:
    if mention.get("type") == "date":
        return f'<mention-date start="{mention["date"]["start"]}"/>'
    if mention.get("type") == "page":
        page_id = canonical_notion_page_id(mention["page"]["id"])
        return f'<mention-page url="https://www.notion.so/{page_id}"/>'
    return ""


def _rest_parent_from_page_key(
    parent_page_key: str | None,
    page_registry: NotionPageRegistry,
) -> dict[str, str]:
    if parent_page_key is None:
        raise ValueError("REST page creation requires a parent page key")

    return {
        "type": "page_id",
        "page_id": page_registry.page_id(parent_page_key),
    }


def _required_target_page_key(write_intent: NotionWriteIntent) -> str:
    if write_intent.target_page_key is None:
        raise ValueError(f"Write intent {write_intent.operation_key!r} has no target page key")

    return write_intent.target_page_key


def _page_has_id(page_registry: NotionPageRegistry, page_key: str) -> bool:
    try:
        page_registry.page_id(page_key)
    except ValueError:
        return False

    return True


def _find_matching_top_level_block(
    blocks: list[dict[str, Any]],
    tracker_block: dict[str, Any],
) -> dict[str, Any] | None:
    for block in blocks:
        if _block_matches_tracker_block(block, tracker_block):
            return block
    return None


def _block_matches_tracker_block(rest_block: dict[str, Any], tracker_block: dict[str, Any]) -> bool:
    return (
        rest_block.get("type") == tracker_block["type"]
        and _plain_text_from_block(rest_block) == tracker_block["text"]
    )


def _data_source_id_from_url(data_source_url: str) -> str:
    if data_source_url.startswith("collection://"):
        return data_source_url.removeprefix("collection://")
    return data_source_url.rsplit("/", 1)[-1]


def _write_result(
    operation_key: str,
    captured_page_key: str | None = None,
    page: dict[str, Any] | None = None,
) -> dict[str, Any]:
    result = {"operation_key": operation_key}
    if captured_page_key is not None:
        if page is None:
            raise ValueError(f"Write {operation_key!r} captured a page key but returned no page")
        result["captured_page_key"] = captured_page_key
        result["captured_page_id"] = canonical_notion_page_id(page["id"])
    return result


def _chunks(items: list[dict[str, Any]], chunk_size: int) -> list[list[dict[str, Any]]]:
    return [
        items[index:index + chunk_size]
        for index in range(0, len(items), chunk_size)
    ]


def _notion_rest_error_message(method: str, path: str, status_code: int | None, error_text: str) -> str:
    permission_hint = _notion_rest_permission_hint(status_code)
    return json.dumps(
        {
            "method": method,
            "path": path,
            "status_code": status_code,
            "error": error_text[:2000],
            "permission_hint": permission_hint,
        },
        indent=2,
        sort_keys=True,
    )


def _notion_rest_permission_hint(status_code: int | None) -> str | None:
    if status_code == 401:
        return "Check that NOTION_API_KEY contains a valid ntn_ integration token."
    if status_code == 403:
        return "Check that the Notion integration can access the page or data source and has read, update, and insert-content capability."
    if status_code == 404:
        return "Check that the target page, block, or data source is shared with the Notion integration."
    return None
