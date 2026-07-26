from __future__ import annotations

import argparse
import sys
from pathlib import Path

BASHRC_MARKER_START = "# >>> Alovya's bashrc instructions >>>"
BASHRC_MARKER_END = "# <<< Alovya's bashrc instructions <<<"

BASH_CONVENIENCE_BLOCK = """\
# >>> Alovya's bash convenience functionality >>>
alias src_bashrc='source $HOME/.bashrc'
alias ll='ls -l'
alias cdwayve='cd /workspace/WayveCode'
alias cdwayve2='cd /workspace/worktrees/WayveCode_2'
alias cdagents='cd /workspace/agents'
alias cdntt='cd /workspace/notion_task_tracker'
alias cdralph='cd /workspace/ralph'
search_history() {
    history | grep "$1"
}
# <<< Alovya's bash convenience functionality <<<"""

PYTHON_BLOCK = """\
# >>> Alovya's Python >>>
alias src_venv='source /workspace/venv/bin/activate'
# <<< Alovya's Python <<<"""

GIT_BLOCK = """\
# >>> Alovya's git >>>
if [ -f "$HOME/.git-completion.bash" ]; then
    source "$HOME/.git-completion.bash"
fi
alias gadd='git add'
alias gcommit='git commit -m'
alias gstatus='git status'
alias current_branch='git branch --show'
alias rebase_on_main='git fetch origin main && git rebase origin/main'
new_branch_from_main() {
    git switch main && git pull && git checkout -b "$1"
}
# <<< Alovya's git <<<"""

PRIVATE_ENVIRONMENT_VARIABLES_BLOCK = """\
# >>> Alovya's private environment variables >>>
# Private environment variables for sensitive info that should only be securely shared, e.g. API access tokens.
if [ -f "$HOME/.private_env" ]; then
  source "$HOME/.private_env"
fi
# <<< Alovya's private environment variables <<<"""

AGENT_ENVIRONMENT_VARIABLES_BLOCK = """\
# >>> Alovya's agent environment variables >>>
if [ ! -d /workspace ]; then
  echo "ERROR: /workspace is required for CODEX_HOME, CLAUDE_CONFIG_DIR, and CURSOR_CONFIG_DIR." >&2
  return 1 2>/dev/null || exit 1
fi

export CODEX_HOME="/workspace/.codex"
export CLAUDE_CONFIG_DIR="/workspace/.claude"
export CURSOR_CONFIG_DIR="/workspace/.cursor" # Store chats in /workspace since $HOME/ is slow on Coder VM.
export CURSOR_HOME="$HOME/.cursor" # Cursor only looks for skills in $HOME/.

# Prefer local Codex and Claude installs over Wayve repo wrappers.
export PATH="$CODEX_HOME/packages/standalone/current/bin:$HOME/.local/bin:$PATH"
# <<< Alovya's agent environment variables <<<"""

AGENT_ALIASES_BLOCK = """\
# >>> Alovya's agent aliases >>>
alias cor='codex resume'
alias clr='claude --resume'
alias cur='agent resume'

# cursor_cli: wrap `agent` so AGENTS.md rules are sent as prompt text.
# Pass flags and your task like plain `agent` — they run before the instruction, per CLI order.
# Examples:
#   cursor_cli
#   cursor_cli --force "fix the tests"
#   cursor_cli --print "summarise README"
# For subcommands (login, mcp, resume, …) use `agent` directly.
cursor_cli() {
  local system_instruction="System Instruction: Before doing anything, strictly follow the rules in /workspace/agents/AGENTS.md. "
  if [ "$#" -eq 0 ]; then
    agent "$system_instruction"
  else
    agent "$@" "$system_instruction"
  fi
}
# <<< Alovya's agent aliases <<<"""

ALL_BLOCKS = [
    # General personal configuration
    BASH_CONVENIENCE_BLOCK,
    PYTHON_BLOCK,
    GIT_BLOCK,
    PRIVATE_ENVIRONMENT_VARIABLES_BLOCK,

    # Agent-specific configuration
    AGENT_ENVIRONMENT_VARIABLES_BLOCK,
    AGENT_ALIASES_BLOCK,
]

CUSTOM_CONTENT = "\n\n".join([BASHRC_MARKER_START] + ALL_BLOCKS + [BASHRC_MARKER_END])

def main() -> None:
    parser = argparse.ArgumentParser(description="Install personal bashrc setup.")
    parser.add_argument("--dry-run", action="store_true", help="Print planned changes without writing.")
    args = parser.parse_args()

    bashrc_path = Path("~/.bashrc").expanduser()
    
    if not bashrc_path.exists():
        print(f"Error: {bashrc_path} not found.", file=sys.stderr)
        sys.exit(1)

    existing_text = bashrc_path.read_text(encoding="utf-8")
    
    # Check if all blocks are already present in exact form (with relaxed newlines between them)
    # The simplest way is to replace the old block entirely, but if the text is identical, it will naturally return early.
    new_text = _replace_or_append_block(existing_text, CUSTOM_CONTENT)

    if new_text == existing_text:
        print("bashrc is already up to date.")
        return

    if args.dry_run:
        print("Would rewrite bashrc with new block:")
        print(CUSTOM_CONTENT)
        return

    bashrc_path.write_text(new_text, encoding="utf-8")
    print(f"Updated {bashrc_path} successfully.")


def _replace_or_append_block(existing_text: str, custom_content: str) -> str:
    lines = existing_text.splitlines()
    
    start_idx = -1
    end_idx = -1
    for i, line in enumerate(lines):
        if line.strip() == BASHRC_MARKER_START:
            start_idx = i
        elif line.strip() == BASHRC_MARKER_END:
            end_idx = i
            break

    # Scenario 1: The markers already exist in the file.
    # Replace everything between and including the markers with our new custom_content.
    if start_idx != -1 and end_idx != -1 and start_idx < end_idx:
        before = "\n".join(lines[:start_idx])
        after = "\n".join(lines[end_idx + 1:])
        return before + ("\n" if before else "") + custom_content + ("\n" if after else "") + after
        
    # Scenario 2: Corrupted markers (one exists but not the other, or they are out of order).
    if start_idx != -1 or end_idx != -1:
        raise RuntimeError("Found mismatched bashrc block markers. Please clean up ~/.bashrc manually.")
    
    # Scenario 3: Markers do not exist. Append to the very end of the file.
    return existing_text + ("\n" if not existing_text.endswith("\n") else "") + custom_content + "\n"


if __name__ == "__main__":
    main()
