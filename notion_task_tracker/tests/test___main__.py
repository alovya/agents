import pytest

from notion_task_tracker.__main__ import main


def test_main_accepts_notion_transport_flag_when_command_path_is_present():
    with pytest.raises(FileNotFoundError):
        main(["--command-path", "/tmp/missing-command.json", "--notion-transport", "rest"])


def test_main_rejects_unknown_flag():
    with pytest.raises(SystemExit) as error:
        main(["--unknown-flag", "result.json"])

    assert error.value.code == 2
