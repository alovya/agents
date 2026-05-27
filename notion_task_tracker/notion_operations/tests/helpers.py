from notion_task_tracker.apply_tracker_command import TrackerCommandResult
from notion_task_tracker.notion_operations.client import CreatedTaskDatabasePage, NotionWriteExecutionResult
from notion_task_tracker.notion_operations.mcp_client import (
    NotionMcpCallPlanner,
    NotionMcpToolCall,
    _notion_page_id_from_tool_result,
    _raise_if_call_plan_has_blocked_operations,
)
from notion_task_tracker.tasks.database import (
    task_database_data_source_url_from_tracker_state,
    task_database_query_for_tracker_state,
    task_database_view_url_from_tracker_state,
)


class FakeNotionClient:
    def __init__(
        self,
        results: list[dict] | None = None,
        database_rows: list[dict] | None = None,
        fetched_page_content_by_id: dict[str, str] | None = None,
    ):
        self.calls = []
        self.database_rows = list(database_rows or [])
        self.fetched_page_content_by_id = fetched_page_content_by_id or {}
        self.fetched_pages = []
        self.queries = []
        self.view_queries = []
        self.results = list(results or [])

    async def fetch_task_page_content(self, page_id: str):
        self.fetched_pages.append(page_id)
        return self.fetched_page_content_by_id.get(page_id, "")

    async def query_data_source(self, data_source_url: str, query: str):
        self.queries.append({"data_source_url": data_source_url, "query": query})
        return list(self.database_rows)

    async def query_database_view(self, view_url: str):
        self.view_queries.append(view_url)
        return list(self.database_rows)

    async def query_task_database_rows(self, tracker_state: dict):
        view_url = task_database_view_url_from_tracker_state(tracker_state)
        if view_url is not None:
            return await self.query_database_view(view_url)

        return await self.query_data_source(
            data_source_url=task_database_data_source_url_from_tracker_state(tracker_state),
            query=task_database_query_for_tracker_state(tracker_state),
        )

    async def create_task_database_page(
        self,
        data_source_id: str,
        properties: dict,
        content: str,
        operation_key: str,
    ):
        tool_result = await self.send_call(
            NotionMcpToolCall(
                operation_key=operation_key,
                tool_name="notion-create-pages",
                arguments={
                    "parent": {
                        "type": "data_source_id",
                        "data_source_id": data_source_id,
                    },
                    "pages": [
                        {
                            "properties": properties,
                            "content": content,
                        }
                    ],
                },
            )
        )
        return CreatedTaskDatabasePage(
            notion_page_id=_notion_page_id_from_tool_result(tool_result),
            operation_keys=[operation_key],
        )

    async def update_task_database_page_title(
        self,
        page_id: str,
        title_property: str,
        title: str,
        operation_key: str,
    ):
        await self.send_call(
            NotionMcpToolCall(
                operation_key=operation_key,
                tool_name="notion-update-page",
                arguments={
                    "page_id": page_id,
                    "command": "update_properties",
                    "properties": {
                        title_property: title,
                    },
                },
            )
        )
        return operation_key

    async def execute_command_result(self, command_result: TrackerCommandResult):
        if command_result.page_registry is None:
            raise ValueError("MCP write execution requires a page registry")

        call_plan = NotionMcpCallPlanner(command_result.page_registry).compile_write_intents(command_result.write_intents)
        completed_operation_keys = []
        captured_page_ids = {}
        for tool_call in call_plan.calls:
            tool_result = await self.send_call(tool_call)
            completed_operation_keys.append(tool_call.operation_key)
            if tool_call.captures_page_key is not None:
                captured_page_ids[tool_call.captures_page_key] = _notion_page_id_from_tool_result(tool_result)
        if call_plan.blocked_operations and not captured_page_ids:
            _raise_if_call_plan_has_blocked_operations(call_plan)
        return NotionWriteExecutionResult(
            completed_operation_keys=completed_operation_keys,
            captured_page_ids=captured_page_ids,
            blocked_operation_count=len(call_plan.blocked_operations),
        )

    async def send_call(self, tool_call: NotionMcpToolCall):
        self.calls.append(tool_call)
        if self.results:
            return self.results.pop(0)
        return {}
