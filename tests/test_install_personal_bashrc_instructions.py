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

    assert 'alias cdagents=\'cd /src/agents\'' in custom_content
    assert 'export CODEX_HOME="/opt/workspace/.codex"' in custom_content
    assert 'export AGENTS_REPO_ROOT="/src/agents"' in custom_content
    assert "$AGENTS_REPO_ROOT/AGENTS.md" in custom_content


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
