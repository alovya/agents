"""Command-line entrypoint for command planning and task-page reconciliation."""

from __future__ import annotations

import argparse
import json

from collections.abc import Sequence

from notion_task_tracker.tasks.workflow import (
    DEFAULT_CREDENTIALS_PATH,
    DEFAULT_OUTPUT_PATH,
    DEFAULT_TRACKER_STATE_PATH,
    execute_command_file,
    reconcile_task_dependency_graph_from_notion,
)


def main(argv: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--command-path")
    parser.add_argument("--tracker-state-path")
    parser.add_argument("--output-path")
    parser.add_argument("--reconcile-from-notion", action="store_true")
    parser.add_argument("--credentials-path")
    parser.add_argument("--notion-transport", choices=["rest", "mcp"], default="rest")
    args = parser.parse_args(argv)

    try:
        _run_requested_cli_action(parser, args)
    except PermissionError as error:
        parser.exit(1, f"{error}\n")


def _run_requested_cli_action(parser: argparse.ArgumentParser, args: argparse.Namespace) -> None:
    if args.reconcile_from_notion:
        reconcile_summary = reconcile_task_dependency_graph_from_notion(
            credentials_path=args.credentials_path or DEFAULT_CREDENTIALS_PATH,
            tracker_state_path=args.tracker_state_path or DEFAULT_TRACKER_STATE_PATH,
            output_path=args.output_path or DEFAULT_OUTPUT_PATH,
            notion_client=args.notion_transport,
        )
        print(json.dumps(reconcile_summary.to_json_summary(), indent=2, sort_keys=True))
        return

    if not args.command_path:
        parser.error(
            "--command-path is required unless --reconcile-from-notion is set"
        )

    execution_summary = execute_command_file(
        command_path=args.command_path,
        tracker_state_path=args.tracker_state_path or DEFAULT_TRACKER_STATE_PATH,
        output_path=args.output_path or DEFAULT_OUTPUT_PATH,
        credentials_path=args.credentials_path or DEFAULT_CREDENTIALS_PATH,
        notion_client=args.notion_transport,
    )
    print(json.dumps(execution_summary.to_json_summary(), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
