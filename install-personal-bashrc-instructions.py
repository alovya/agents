from __future__ import annotations

import argparse
import shlex
import sys
from pathlib import Path

BASHRC_MARKER_START = "# >>> Agents bashrc instructions >>>"
BASHRC_MARKER_END = "# <<< Agents bashrc instructions <<<"

def main() -> None:
    parser = argparse.ArgumentParser(description="Install personal bashrc setup.")
    parser.add_argument("--dry-run", action="store_true", help="Print planned changes without writing.")
    args = parser.parse_args()

    bashrc_path = Path("~/.bashrc").expanduser()
    agents_repo_path = Path(__file__).resolve().parent
    
    if not bashrc_path.exists():
        print(f"Error: {bashrc_path} not found.", file=sys.stderr)
        sys.exit(1)

    existing_text = bashrc_path.read_text(encoding="utf-8")
    
    custom_content = _build_custom_content(agents_repo_path)
    new_text = _replace_or_append_block(existing_text, custom_content)

    if new_text == existing_text:
        print("bashrc is already up to date.")
        return

    if args.dry_run:
        print("Would rewrite bashrc with new block:")
        print(custom_content)
        return

    bashrc_path.write_text(new_text, encoding="utf-8")
    print(f"Updated {bashrc_path} successfully.")


def _build_custom_content(agents_repo_path: Path) -> str:
    agents_md_path = agents_repo_path / "AGENTS.md"
    system_instruction = (
        "System Instruction: Before doing anything, strictly follow the rules in "
        f"{agents_md_path}. "
    )
    quoted_system_instruction = shlex.quote(system_instruction)

    return f"""{BASHRC_MARKER_START}
if [ ! -d /workspace ]; then
  echo "ERROR: /workspace is required for CODEX_HOME, CLAUDE_CONFIG_DIR, and CURSOR_CONFIG_DIR." >&2
  return 1 2>/dev/null || exit 1
fi

# Convenience bash functionality
alias src_bashrc='source $HOME/.bashrc'
alias ll='ls -l'
search_history() {{
    history | grep "$1"
}}

# Environment variables derived from /workspace/agents/AGENTS.md contract
export CODEX_HOME="/workspace/.codex"
export CLAUDE_CONFIG_DIR="/workspace/.claude"
export CURSOR_CONFIG_DIR="/workspace/.cursor" # Store chats in /workspace since $HOME/ is slow on Coder VM.
export CURSOR_HOME="$HOME/.cursor" # Cursor only looks for skills in $HOME/.

# Python
alias src_venv='source /workspace/venv/bin/activate'

# git
if [ -f "$HOME/.git-completion.bash" ]; then
    source "$HOME/.git-completion.bash"
fi
alias gadd='git add'
alias gcommit='git commit -m'
alias gstatus='git status'
alias current_branch='git branch --show'
alias rebase_on_main='git fetch origin main && git rebase origin/main'
new_branch_from_main() {{
    git switch main && git pull && git checkout -b "$1"
}}

# Navigation
alias cdwayve='cd /workspace/WayveCode'
alias cdwayve2='cd /workspace/worktrees/WayveCode_2'
alias cdagents='cd /workspace/agents'
alias cdntt='cd /workspace/notion_task_tracker'
alias cdralph='cd /workspace/ralph'

# Prefer local Codex and Claude installs over Wayve repo wrappers.
export PATH="$CODEX_HOME/packages/standalone/current/bin:$HOME/.local/bin:$PATH"

# Private environment variables for sensitive info that should only be securely shared, e.g. API access tokens.
if [ -f "$HOME/.private_env" ]; then
  source "$HOME/.private_env"
fi

alias cor='codex resume'
alias clr='claude --resume'

export NVM_DIR="$HOME/.nvm"
[ -s "$NVM_DIR/nvm.sh" ] && \\. "$NVM_DIR/nvm.sh"  # This loads nvm
[ -s "$NVM_DIR/bash_completion" ] && \\. "$NVM_DIR/bash_completion"  # This loads nvm bash_completion

# cursor_cli: wrap `agent` so AGENTS.md rules are sent as prompt text (no --system flag).
# Pass flags and your task like plain `agent` — they run before the instruction, per CLI order.
# Examples:
#   cursor_cli
#   cursor_cli --force "fix the tests"
#   cursor_cli --print "summarise README"
# For subcommands (login, mcp, resume, …) use `agent` directly.
cursor_cli() {{
  local system_instruction={quoted_system_instruction}
  if [ "$#" -eq 0 ]; then
    agent "$system_instruction"
  else
    agent "$@" "$system_instruction"
  fi
}}
{BASHRC_MARKER_END}
"""


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

    if start_idx != -1 and end_idx != -1 and start_idx < end_idx:
        # Replace existing block
        before = "\n".join(lines[:start_idx])
        after = "\n".join(lines[end_idx + 1:])
        new_text = before + ("\n" if before else "") + custom_content + ("\n" if after else "") + after
        return new_text
    elif start_idx != -1 or end_idx != -1:
        # Corrupted markers
        raise RuntimeError("Found mismatched bashrc block markers. Please clean up ~/.bashrc manually.")
    
    # Append
    # First, let's strip everything after the HISTTIMEFORMAT line since the user said it was manually added.
    hist_idx = -1
    for i, line in enumerate(lines):
        if line.startswith('export HISTTIMEFORMAT="%F %T  "'):
            hist_idx = i
            break
            
    if hist_idx != -1:
        # Keep everything up to hist_idx inclusive.
        before = "\n".join(lines[:hist_idx + 1])
        new_text = before + "\n\n" + custom_content + "\n"
        return new_text
    
    # Fallback append
    new_text = existing_text + ("\n" if not existing_text.endswith("\n") else "") + custom_content + "\n"
    return new_text


if __name__ == "__main__":
    main()
