from __future__ import annotations

import os
from pathlib import Path


def main() -> None:
    repo_root_path = Path(__file__).resolve().parents[1]
    codex_home_path = Path(os.environ.get("CODEX_HOME", Path.home() / ".codex"))

    _install_symlink(
        source_path=repo_root_path / "skills" / "notion_task",
        destination_path=codex_home_path / "skills" / "notion_task",
    )
    _install_symlink(
        source_path=repo_root_path / "AGENTS.md",
        destination_path=codex_home_path / "AGENTS.md",
    )
    _install_symlink(
        source_path=repo_root_path / "notion_task_tracker",
        destination_path=codex_home_path / "memories" / "notion_task_tracker",
    )


def _install_symlink(source_path: Path, destination_path: Path) -> None:
    if not source_path.exists():
        raise FileNotFoundError(f"Source path does not exist: {source_path}")

    destination_path.parent.mkdir(parents=True, exist_ok=True)
    if destination_path.is_symlink() and destination_path.resolve() == source_path.resolve():
        print(f"Already linked: {destination_path} -> {source_path}")
        return

    if destination_path.exists() or destination_path.is_symlink():
        backup_path = _next_backup_path(destination_path)
        destination_path.rename(backup_path)
        print(f"Backed up existing path: {destination_path} -> {backup_path}")

    destination_path.symlink_to(source_path, target_is_directory=source_path.is_dir())
    print(f"Linked: {destination_path} -> {source_path}")


def _next_backup_path(destination_path: Path) -> Path:
    candidate_path = destination_path.with_name(f"{destination_path.name}.bak")
    if not candidate_path.exists():
        return candidate_path

    index = 1
    while True:
        indexed_candidate_path = destination_path.with_name(f"{destination_path.name}.bak.{index}")
        if not indexed_candidate_path.exists():
            return indexed_candidate_path
        index += 1


if __name__ == "__main__":
    main()
