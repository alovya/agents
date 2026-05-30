from __future__ import annotations

import argparse
import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class SkillDirectory:
    name: str
    source_path: Path


@dataclass(frozen=True)
class SkillInstallTarget:
    agent_name: str
    skills_path: Path


def main() -> None:
    arguments = _parse_arguments()
    agents_repo_path = Path(__file__).resolve().parent
    skill_directories = _find_skill_directories(agents_repo_path)
    install_targets = _build_skill_install_targets(arguments)

    if not skill_directories:
        print(f"No skills found under {agents_repo_path}")
        return

    for skill_directory in skill_directories:
        for install_target in install_targets:
            _install_skill_directory(
                skill_directory=skill_directory,
                install_target=install_target,
                dry_run=arguments.dry_run,
            )


def _parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Symlink every ~/agents skill directory into local agent skill locations."
    )
    parser.add_argument("--dry-run", action="store_true", help="Print planned links without changing files.")
    parser.add_argument(
        "--codex-home",
        default=os.environ.get("CODEX_HOME", Path.home() / ".codex"),
        help="Codex home directory. Defaults to CODEX_HOME or ~/.codex.",
    )
    parser.add_argument(
        "--claude-home",
        default=Path.home() / ".claude",
        help="Claude home directory. Defaults to ~/.claude.",
    )
    parser.add_argument(
        "--codex-only",
        action="store_true",
        help="Install only Codex skill links.",
    )
    parser.add_argument(
        "--claude-only",
        action="store_true",
        help="Install only Claude skill links.",
    )
    return parser.parse_args()


def _find_skill_directories(agents_repo_path: Path) -> list[SkillDirectory]:
    skill_source_paths = sorted(
        skill_file_path.parent
        for skill_file_path in agents_repo_path.rglob("SKILL.md")
        if _is_user_skill_file(agents_repo_path, skill_file_path)
    )
    _raise_for_duplicate_skill_names(skill_source_paths)
    return [
        SkillDirectory(name=skill_source_path.name, source_path=skill_source_path)
        for skill_source_path in skill_source_paths
    ]


def _is_user_skill_file(agents_repo_path: Path, skill_file_path: Path) -> bool:
    relative_parts = skill_file_path.relative_to(agents_repo_path).parts
    return not any(part.startswith(".") for part in relative_parts)


def _raise_for_duplicate_skill_names(skill_source_paths: list[Path]) -> None:
    skill_paths_by_name: dict[str, list[Path]] = {}
    for skill_source_path in skill_source_paths:
        skill_paths_by_name.setdefault(skill_source_path.name, []).append(skill_source_path)

    duplicate_skill_paths = {
        skill_name: paths for skill_name, paths in skill_paths_by_name.items() if len(paths) > 1
    }
    if duplicate_skill_paths:
        details = "\n".join(
            f"{skill_name}: {', '.join(str(path) for path in paths)}"
            for skill_name, paths in sorted(duplicate_skill_paths.items())
        )
        raise RuntimeError(f"Duplicate skill directory names would collide:\n{details}")


def _build_skill_install_targets(arguments: argparse.Namespace) -> list[SkillInstallTarget]:
    if arguments.codex_only and arguments.claude_only:
        raise RuntimeError("Choose at most one of --codex-only and --claude-only.")

    install_targets: list[SkillInstallTarget] = []
    if not arguments.claude_only:
        install_targets.append(
            SkillInstallTarget(
                agent_name="Codex",
                skills_path=Path(arguments.codex_home).expanduser() / "skills",
            )
        )
    if not arguments.codex_only:
        install_targets.append(
            SkillInstallTarget(
                agent_name="Claude",
                skills_path=Path(arguments.claude_home).expanduser() / "skills",
            )
        )
    return install_targets


def _install_skill_directory(
    skill_directory: SkillDirectory,
    install_target: SkillInstallTarget,
    dry_run: bool,
) -> None:
    destination_path = install_target.skills_path / skill_directory.name
    if destination_path.is_symlink() and destination_path.resolve() == skill_directory.source_path.resolve():
        print(f"{install_target.agent_name}: already linked {destination_path} -> {skill_directory.source_path}")
        return

    if destination_path.exists() or destination_path.is_symlink():
        raise FileExistsError(
            f"{install_target.agent_name}: refusing to replace existing path: {destination_path}"
        )

    if dry_run:
        print(f"{install_target.agent_name}: would link {destination_path} -> {skill_directory.source_path}")
        return

    install_target.skills_path.mkdir(parents=True, exist_ok=True)
    destination_path.symlink_to(skill_directory.source_path, target_is_directory=True)
    print(f"{install_target.agent_name}: linked {destination_path} -> {skill_directory.source_path}")


if __name__ == "__main__":
    main()
