import json

from notion_task_tracker.notion_operations.client import notion_client_from_credentials_path
from notion_task_tracker.notion_operations.mcp_client import NotionMcpClient
from notion_task_tracker.notion_operations.rest_client import NotionRestClient


def test_notion_client_from_credentials_path_defaults_to_rest(monkeypatch, tmp_path):
    credentials_path = tmp_path / ".credentials.json"
    credentials_path.write_text("{}", encoding="utf-8")
    monkeypatch.setenv("NOTION_API_KEY", "ntn_test")

    notion_client = notion_client_from_credentials_path(credentials_path)

    assert isinstance(notion_client, NotionRestClient)


def test_notion_client_from_credentials_path_keeps_mcp_fallback(tmp_path):
    credentials_path = tmp_path / ".credentials.json"
    credentials_path.write_text(
        json.dumps(
            {
                "Notion|workspace": {
                    "access_token": "mcp-token",
                    "server_url": "https://mcp.notion.test/mcp",
                }
            }
        ),
        encoding="utf-8",
    )

    notion_client = notion_client_from_credentials_path(credentials_path, "mcp")

    assert isinstance(notion_client, NotionMcpClient)
