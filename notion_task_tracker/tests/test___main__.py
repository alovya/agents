import pytest

from notion_task_tracker.__main__ import main


def test_main_rejects_unknown_flag():
    with pytest.raises(SystemExit) as error:
        main(["--unknown-flag", "result.json"])

    assert error.value.code == 2
