import pytest
from pathlib import Path
import sys
import os

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import install_personal_bashrc_instructions as bashrc_module

def test_replace_or_append_block_scenario_1_replace_existing():
    existing_text = f"""Some prior content
{bashrc_module.BASHRC_MARKER_START}
Old content to be replaced
{bashrc_module.BASHRC_MARKER_END}
Some trailing content"""
    
    custom_content = f"{bashrc_module.BASHRC_MARKER_START}\nNew content\n{bashrc_module.BASHRC_MARKER_END}"
    
    result = bashrc_module._replace_or_append_block(existing_text, custom_content)
    
    expected = f"""Some prior content
{bashrc_module.BASHRC_MARKER_START}
New content
{bashrc_module.BASHRC_MARKER_END}
Some trailing content"""
    assert result == expected

def test_replace_or_append_block_scenario_2_corrupted_markers():
    existing_text = f"""Some prior content
{bashrc_module.BASHRC_MARKER_START}
Old content to be replaced
Missing end marker"""
    
    custom_content = "anything"
    
    with pytest.raises(RuntimeError, match="mismatched bashrc block markers"):
        bashrc_module._replace_or_append_block(existing_text, custom_content)

def test_replace_or_append_block_scenario_3_fallback_append():
    existing_text = """Just some random text
without markers or histtimeformat"""
    
    custom_content = f"{bashrc_module.BASHRC_MARKER_START}\nNew content\n{bashrc_module.BASHRC_MARKER_END}"
    
    result = bashrc_module._replace_or_append_block(existing_text, custom_content)
    
    expected = f"""Just some random text
without markers or histtimeformat
{bashrc_module.BASHRC_MARKER_START}
New content
{bashrc_module.BASHRC_MARKER_END}
"""
    assert result == expected
