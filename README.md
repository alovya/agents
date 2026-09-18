# Personal agent setup

This repository contains personal shell configuration, agent instructions, and reusable skills. The `behavioural-graph-explorer` subproject is documented separately in [`behavioural-graph-explorer/README.md`](behavioural-graph-explorer/README.md).

## Install

Run the installers from this repository, in this order.

### 1. Install the bashrc configuration

The first installer adds a managed block to `~/.bashrc`. It defines the agent home variables, including `CODEX_HOME`, `CLAUDE_CONFIG_DIR`, `CURSOR_HOME`, and `PI_CODING_AGENT_DIR`, that the next installer uses.

Replace the example paths with the paths on your machine:

```bash
cd /path/to/agents
python3 install_personal_bashrc_instructions.py \
  --root-dir /workspace \
  --agents-repo-dir /path/to/agents
```

Use `--owner-name NAME` when the generated block should not use `$USER`. To inspect the change without writing it, add `--dry-run`.

Load the new configuration before continuing:

```bash
source ~/.bashrc
```

Starting a new shell has the same effect.

### 2. Install agent instructions and skills

The second installer reads the agent home variables from the shell and links this repository's skills into each configured agent. It also links `AGENTS.md` into Codex and Pi, and `CLAUDE.md` into Claude. Cursor receives the skills but does not receive an instruction-file link.

```bash
python3 install_personal_agent_instructions.py \
  --agents-repo-dir /path/to/agents
```

Use `--dry-run` to preview the links. Use `--force` to replace existing files or directories with the required links. To install for one agent only, use its corresponding option, such as `--pi-only` or `--codex-only`.

An agent is skipped when its home variable is unset. You can provide a home explicitly instead, for example:

```bash
python3 install_personal_agent_instructions.py \
  --agents-repo-dir /path/to/agents \
  --pi-coding-agent-dir /path/to/pi/agent \
  --pi-only
```

## Verify the setup

Run the Python tests from the repository root:

```bash
pytest
```

The installers are safe to run again. The bashrc installer replaces only its own marked block, and the agent installer reports links that are already up to date.

## Repository layout

- `AGENTS.md` — shared agent instructions.
- `skills/` — reusable skills discovered by the agent installer.
- `install_personal_bashrc_instructions.py` — installs the shell environment and aliases.
- `install_personal_agent_instructions.py` — installs skill and instruction-file links.
- `behavioural-graph-explorer/` — the `bgexp` viewer; see its [README](behavioural-graph-explorer/README.md).
