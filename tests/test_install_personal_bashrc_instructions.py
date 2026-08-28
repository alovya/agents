import pytest
from pathlib import Path
import sys
import os

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import install_personal_bashrc_instructions as bashrc_module

def test_replace_or_append_block_scenario_1_replace_existing():
    owner_name = "tester"
    existing_text = f"""Some prior content
{bashrc_module._build_bashrc_marker_start(owner_name)}
Old content to be replaced
{bashrc_module._build_bashrc_marker_end(owner_name)}
Some trailing content"""

    custom_content = (
        f"{bashrc_module._build_bashrc_marker_start(owner_name)}\n"
        f"New content\n"
        f"{bashrc_module._build_bashrc_marker_end(owner_name)}"
    )

    result = bashrc_module._replace_or_append_block(existing_text, custom_content, owner_name)

    expected = f"""Some prior content
{bashrc_module._build_bashrc_marker_start(owner_name)}
New content
{bashrc_module._build_bashrc_marker_end(owner_name)}
Some trailing content"""
    assert result == expected


def test_replace_or_append_block_scenario_2_corrupted_markers():
    owner_name = "tester"
    existing_text = f"""Some prior content
{bashrc_module._build_bashrc_marker_start(owner_name)}
Old content to be replaced
Missing end marker"""

    custom_content = "anything"

    with pytest.raises(RuntimeError, match="mismatched bashrc block markers"):
        bashrc_module._replace_or_append_block(existing_text, custom_content, owner_name)


def test_replace_or_append_block_scenario_3_fallback_append():
    owner_name = "tester"
    existing_text = """Just some random text
without markers or histtimeformat"""

    custom_content = (
        f"{bashrc_module._build_bashrc_marker_start(owner_name)}\n"
        f"New content\n"
        f"{bashrc_module._build_bashrc_marker_end(owner_name)}"
    )

    result = bashrc_module._replace_or_append_block(existing_text, custom_content, owner_name)

    expected = f"""Just some random text
without markers or histtimeformat
{bashrc_module._build_bashrc_marker_start(owner_name)}
New content
{bashrc_module._build_bashrc_marker_end(owner_name)}
"""
    assert result == expected


def test_custom_content_uses_root_dir_for_generated_paths():
    custom_content = bashrc_module._build_custom_content(
        root_dir=Path("/opt/workspace"),
        agents_repo_dir=Path("/src/agents"),
        owner_name="tester",
    )

    assert 'alias cd_agents=\'cd /src/agents\'' in custom_content
    assert 'export CODEX_HOME="/opt/workspace/.codex"' in custom_content
    assert 'export AGENTS_REPO_ROOT="/src/agents"' in custom_content
    assert "$AGENTS_REPO_ROOT/AGENTS.md" in custom_content


def test_custom_content_defines_wayvecode_directory_and_open_aliases():
    custom_content = bashrc_module._build_custom_content(
        root_dir=Path("/opt/workspace"),
        agents_repo_dir=Path("/src/agents"),
        owner_name="tester",
    )

    assert "alias cd_wayvecode='cd /opt/workspace/WayveCode'" in custom_content
    assert "alias cd_wayvecode2='cd /opt/workspace/worktrees/WayveCode_2'" in custom_content
    assert "alias cd_wayvecode3='cd /opt/workspace/worktrees/WayveCode_3'" in custom_content
    assert "alias open_wayvecode='cd_wayvecode && code . && cd -'" in custom_content
    assert "alias open_wayvecode2='cd_wayvecode2 && code . && cd -'" in custom_content
    assert "alias open_wayvecode3='cd_wayvecode3 && code . && cd -'" in custom_content
    assert "alias cdwayve" not in custom_content


def test_custom_content_defines_tmux_workbench_directory_and_open_aliases():
    custom_content = bashrc_module._build_custom_content(
        root_dir=Path("/opt/workspace"),
        agents_repo_dir=Path("/src/agents"),
        owner_name="tester",
    )

    assert "alias cd_tmux_workbench='cd /opt/workspace/tmux_workbench'" in custom_content
    assert "alias open_tmux_workbench='cd_tmux_workbench && code . && cd -'" in custom_content


def test_custom_content_defines_underscore_directory_aliases_for_other_projects():
    custom_content = bashrc_module._build_custom_content(
        root_dir=Path("/opt/workspace"),
        agents_repo_dir=Path("/src/agents"),
        owner_name="tester",
    )

    assert "alias cd_agents='cd /src/agents'" in custom_content
    assert "alias cd_ntt='cd /opt/workspace/notion_task_tracker'" in custom_content
    assert "alias cd_ralph='cd /opt/workspace/ralph_loops'" in custom_content
    assert "alias open_agents='cd_agents && code . && cd -'" in custom_content
    assert "alias open_ntt='cd_ntt && code . && cd -'" in custom_content
    assert "alias open_ralph='cd_ralph && code . && cd -'" in custom_content
    assert "alias cdagents" not in custom_content
    assert "alias cdntt" not in custom_content
    assert "alias cdralph" not in custom_content


def test_custom_content_uses_owner_name_for_block_labels():
    custom_content = bashrc_module._build_custom_content(
        root_dir=Path("/workspace"),
        agents_repo_dir=Path("/workspace/agents"),
        owner_name="tester",
    )

    assert "# >>> tester's bashrc instructions >>>" in custom_content
    assert "# <<< tester's bashrc instructions <<<" in custom_content
    assert "# >>> tester's agent aliases >>>" in custom_content


def test_resolve_owner_name_uses_user_environment(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("USER", "shell-user")

    assert bashrc_module._resolve_owner_name(None) == "shell-user"


def test_resolve_owner_name_fails_without_name_or_user(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("USER", raising=False)

    with pytest.raises(RuntimeError, match="Set USER or pass --owner-name"):
        bashrc_module._resolve_owner_name(None)
