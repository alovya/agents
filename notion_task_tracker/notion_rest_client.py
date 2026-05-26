"""Notion REST transport client."""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from notion_task_tracker.notion_rest_requests import NotionRestRequest


DEFAULT_NOTION_API_BASE_URL = "https://api.notion.com"
DEFAULT_NOTION_API_VERSION = "2026-03-11"


class NotionRestClient:
    def __init__(self, access_token: str, base_url: str, notion_version: str) -> None:
        self.access_token = access_token
        self.base_url = base_url.rstrip("/")
        self.notion_version = notion_version

    @classmethod
    def from_credentials_path(cls, credentials_path: Path) -> "NotionRestClient":
        return cls(
            access_token=_notion_access_token_from_path(credentials_path),
            base_url=DEFAULT_NOTION_API_BASE_URL,
            notion_version=DEFAULT_NOTION_API_VERSION,
        )

    async def fetch_task_page_content(self, page_id: str) -> str:
        fetched_page = await self.fetch_page(page_id)
        if fetched_page["truncated"] or fetched_page["unknown_block_ids"]:
            raise ValueError(
                json.dumps(
                    {
                        "notion_page_id": page_id,
                        "truncated": fetched_page["truncated"],
                        "unknown_block_ids": fetched_page["unknown_block_ids"],
                    },
                    indent=2,
                    sort_keys=True,
                )
            )
        return _fetched_database_page_content(fetched_page)

    async def fetch_page(self, page_id: str) -> dict[str, Any]:
        page, markdown_page = await asyncio.gather(
            self._send_json("GET", f"/v1/pages/{page_id}", None),
            self._send_json("GET", f"/v1/pages/{page_id}/markdown", None),
        )
        return {
            "notion_page_id": page_id,
            "title": _page_title_from_rest_page(page),
            "markdown": markdown_page["markdown"],
            "truncated": markdown_page["truncated"],
            "unknown_block_ids": list(markdown_page.get("unknown_block_ids", [])),
        }

    async def send_request(self, rest_request: NotionRestRequest) -> dict[str, Any]:
        return await self._send_json(rest_request.method, rest_request.path, rest_request.body)

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


def _notion_access_token_from_path(credentials_path: Path) -> str:
    if os.environ.get("NOTION_API_KEY"):
        return os.environ["NOTION_API_KEY"]

    credentials = json.loads(credentials_path.read_text(encoding="utf-8"))
    notion_credentials = next(
        value
        for key, value in credentials.items()
        if key.startswith("Notion|")
    )
    return notion_credentials["access_token"]


def _page_title_from_rest_page(page: dict[str, Any]) -> str:
    title_property = page["properties"]["title"]
    title_items = title_property["title"] if isinstance(title_property, dict) else title_property
    return _plain_text_from_rich_text_items(title_items)


def _plain_text_from_rich_text_items(rich_text_items: list[dict[str, Any]]) -> str:
    return "".join(
        rich_text_item.get("plain_text", rich_text_item.get("text", {}).get("content", ""))
        for rich_text_item in rich_text_items
    )


def _fetched_database_page_content(fetched_page: dict[str, Any]) -> str:
    return "\n".join(
        [
            "<properties>",
            json.dumps({"title": fetched_page["title"]}),
            "</properties>",
            "<content>",
            fetched_page["markdown"],
            "</content>",
        ]
    )


def _notion_rest_error_message(method: str, path: str, status_code: int | None, error_text: str) -> str:
    return json.dumps(
        {
            "method": method,
            "path": path,
            "status_code": status_code,
            "error": error_text[:2000],
        },
        indent=2,
        sort_keys=True,
    )
