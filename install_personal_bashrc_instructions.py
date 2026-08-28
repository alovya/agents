from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path


def main() -> None:
    arguments = _parse_arguments()
    bashrc_path = Path("~/.bashrc").expanduser()
    owner_name = _resolve_owner_name(arguments.owner_name)
    custom_content = _build_custom_content(
        root_dir=arguments.root_dir.expanduser(),
        agents_repo_dir=arguments.agents_repo_dir.expanduser(),
        owner_name=owner_name,
    )

    if not bashrc_path.exists():
        print(f"Error: {bashrc_path} not found.", file=sys.stderr)
        sys.exit(1)

    existing_text = bashrc_path.read_text(encoding="utf-8")
    new_text = _replace_or_append_block(existing_text, custom_content, owner_name)

    if new_text == existing_text:
        print("bashrc is already up to date.")
        return

    if arguments.dry_run:
        print("Would rewrite bashrc with new block:")
        print(custom_content)
        return

    bashrc_path.write_text(new_text, encoding="utf-8")
    print(f"Updated {bashrc_path} successfully.")


def _parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Install bashrc setup.")
    parser.add_argument("--dry-run", action="store_true", help="Print planned changes without writing.")
    parser.add_argument(
        "--root-dir",
        type=Path,
        required=True,
        help="Workspace root directory used for generated paths.",
    )
    parser.add_argument(
        "--agents-repo-dir",
        type=Path,
        required=True,
        help="Agents repository directory.",
    )
    parser.add_argument(
        "--owner-name",
        default=None,
        help="Name used in generated bashrc block labels. Defaults to $USER.",
    )
    return parser.parse_args()


def _resolve_owner_name(owner_name: str | None) -> str:
    if owner_name:
        return owner_name

    user_name = os.environ.get("USER")
    if user_name:
        return user_name

    raise RuntimeError("Set USER or pass --owner-name.")


def _build_custom_content(root_dir: Path, agents_repo_dir: Path, owner_name: str) -> str:
    blocks = [
        _build_bash_convenience_block(root_dir, agents_repo_dir, owner_name),
        _build_python_block(root_dir, owner_name),
        _build_git_block(owner_name),
        _build_private_environment_variables_block(owner_name),
        _build_agent_environment_variables_block(root_dir, agents_repo_dir, owner_name),
        _build_agent_aliases_block(owner_name),
    ]
    return "\n\n".join(
        [_build_bashrc_marker_start(owner_name)] + blocks + [_build_bashrc_marker_end(owner_name)]
    )


def _build_bashrc_marker_start(owner_name: str) -> str:
    return f"# >>> {owner_name}'s bashrc instructions >>>"


def _build_bashrc_marker_end(owner_name: str) -> str:
    return f"# <<< {owner_name}'s bashrc instructions <<<"


def _build_bash_convenience_block(root_dir: Path, agents_repo_dir: Path, owner_name: str) -> str:
    return f"""\
# >>> {owner_name}'s bash convenience functionality >>>
alias src_bashrc='source $HOME/.bashrc'
alias ll='ls -l'
search_history() {{
    history | grep "$1"
}}

alias cd_wayvecode='cd {root_dir / "WayveCode"}'
alias cd_wayvecode2='cd {root_dir / "worktrees" / "WayveCode_2"}'
alias cd_wayvecode3='cd {root_dir / "worktrees" / "WayveCode_3"}'
alias cdagents='cd {agents_repo_dir}'
alias cdntt='cd {root_dir / "notion_task_tracker"}'
alias cdralph='cd {root_dir / "ralph_loops"}'

alias open_wayvecode='cd_wayvecode && code . && cd -'
alias open_wayvecode2='cd_wayvecode2 && code . && cd -'
alias open_wayvecode3='cd_wayvecode3 && code . && cd -'
alias open_agents='cdagents && code . && cd -'
alias open_ntt='cdntt && code . && cd -'
alias open_ralph='cdralph && code . && cd -'
# <<< {owner_name}'s bash convenience functionality <<<"""


def _build_python_block(root_dir: Path, owner_name: str) -> str:
    return f"""\
# >>> {owner_name}'s Python >>>
alias src_venv='source {root_dir / "venv" / "bin" / "activate"}'
# <<< {owner_name}'s Python <<<"""


def _build_git_block(owner_name: str) -> str:
    return f"""\
# >>> {owner_name}'s git >>>
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
# <<< {owner_name}'s git <<<"""


def _build_private_environment_variables_block(owner_name: str) -> str:
    return f"""\
# >>> {owner_name}'s private environment variables >>>
# Private environment variables for sensitive info that should only be securely shared, e.g. API access tokens.
if [ -f "$HOME/.private_env" ]; then
  source "$HOME/.private_env"
fi
# <<< {owner_name}'s private environment variables <<<"""


def _build_agent_environment_variables_block(root_dir: Path, agents_repo_dir: Path, owner_name: str) -> str:
    return f"""\
# >>> {owner_name}'s agent environment variables >>>
if [ ! -d {root_dir} ]; then
  echo "ERROR: {root_dir} is required for CODEX_HOME, CLAUDE_CONFIG_DIR, and CURSOR_CONFIG_DIR." >&2
  return 1 2>/dev/null || exit 1
fi

export CODEX_HOME="{root_dir / '.codex'}"
export CLAUDE_CONFIG_DIR="{root_dir / '.claude'}"
export CURSOR_CONFIG_DIR="{root_dir / '.cursor'}" # Store chats in {root_dir} since $HOME/ is slow on Coder VM.
export CURSOR_HOME="$HOME/.cursor" # Cursor only looks for skills in $HOME/.
export AGENTS_REPO_ROOT="{agents_repo_dir}"

# Prefer local Codex and Claude installs over Wayve repo wrappers.
export PATH="$CODEX_HOME/packages/standalone/current/bin:$HOME/.local/bin:$PATH"
# <<< {owner_name}'s agent environment variables <<<"""


def _build_agent_aliases_block(owner_name: str) -> str:
    return f"""\
# >>> {owner_name}'s agent aliases >>>
alias cor='codex resume'
alias clr='claude --resume'
alias cur='agent resume'

# The interactive-only instruction supplement, layered on top of the shared AGENTS.md
# by the wrappers below. Ralph and other headless callers run the CLIs as direct binary
# calls (no shell), so they never expand these wrappers and only see the shared AGENTS.md.
INTERACTIVE_AGENT_INSTRUCTIONS_PATH="$AGENTS_REPO_ROOT/AGENTS.interactive.md"

# claude_cli: append the interactive supplement to claude's system prompt.
# The shared AGENTS.md is already read from CLAUDE_CONFIG_DIR. Use bare `claude` for subcommands.
claude_cli() {{
  claude --append-system-prompt-file "$INTERACTIVE_AGENT_INSTRUCTIONS_PATH" "$@"
}}

# codex_cli: send the interactive supplement to codex as prompt text.
# Codex has no append flag; the shared AGENTS.md is already read from CODEX_HOME. Use bare `codex` for subcommands.
codex_cli() {{
  local system_instruction="System Instruction: Also strictly follow the interactive rules in $INTERACTIVE_AGENT_INSTRUCTIONS_PATH. "
  if [ "$#" -eq 0 ]; then
    codex "$system_instruction"
  else
    codex "$@" "$system_instruction"
  fi
}}

# cursor_cli: wrap `agent` so AGENTS.md rules are sent as prompt text.
# Pass flags and your task like plain `agent` — they run before the instruction, per CLI order.
# Examples:
#   cursor_cli
#   cursor_cli --force "fix the tests"
#   cursor_cli --print "summarise README"
# For subcommands (login, mcp, resume, …) use `agent` directly.
cursor_cli() {{
  local system_instruction="System Instruction: Before doing anything, strictly follow the rules in $AGENTS_REPO_ROOT/AGENTS.md and the interactive rules in $INTERACTIVE_AGENT_INSTRUCTIONS_PATH. "
  if [ "$#" -eq 0 ]; then
    agent "$system_instruction"
  else
    agent "$@" "$system_instruction"
  fi
}}
# <<< {owner_name}'s agent aliases <<<"""


def _replace_or_append_block(existing_text: str, custom_content: str, owner_name: str) -> str:
    lines = existing_text.splitlines()
    marker_start = _build_bashrc_marker_start(owner_name)
    marker_end = _build_bashrc_marker_end(owner_name)

    start_idx = -1
    end_idx = -1
    for i, line in enumerate(lines):
        if line.strip() == marker_start:
            start_idx = i
        elif line.strip() == marker_end:
            end_idx = i
            break

    # Scenario 1: The markers already exist in the file.
    # Replace everything between and including the markers with our new custom_content.
    if start_idx != -1 and end_idx != -1 and start_idx < end_idx:
        before = "\n".join(lines[:start_idx])
        after = "\n".join(lines[end_idx + 1:])
        return before + ("\n" if before else "") + custom_content + ("\n" if after else "") + after

    # Scenario 2: Corrupted markers: one exists but not the other, or they are out of order.
    if start_idx != -1 or end_idx != -1:
        raise RuntimeError("Found mismatched bashrc block markers. Please clean up ~/.bashrc manually.")

    # Scenario 3: Markers do not exist. Append to the very end of the file.
    return existing_text + ("\n" if not existing_text.endswith("\n") else "") + custom_content + "\n"


if __name__ == "__main__":
    main()
