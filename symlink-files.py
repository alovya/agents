from __future__ import annotations

import argparse
import os
import shutil
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


@dataclass(frozen=True)
class AgentInstructionsLink:
    agent_name: str
    source_path: Path
    destination_path: Path


def main() -> None:
    arguments = _parse_arguments()
    agents_repo_path = Path(__file__).resolve().parent
    skill_directories = _find_skill_directories(agents_repo_path)
    install_targets = _build_skill_install_targets(arguments)
    instruction_links = _build_agent_instructions_links(
        arguments=arguments,
        agents_repo_path=agents_repo_path,
    )

    if not skill_directories:
        print(f"No skills found under {agents_repo_path}")

    for skill_directory in skill_directories:
        for install_target in install_targets:
            _install_skill_directory(
                skill_directory=skill_directory,
                install_target=install_target,
                dry_run=arguments.dry_run,
                force=arguments.force,
            )

    for instruction_link in instruction_links:
        _install_agent_instructions_link(
            instruction_link=instruction_link,
            dry_run=arguments.dry_run,
            force=arguments.force,
        )


def _parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Symlink every ~/agents skill directory into local agent skill locations."
    )
    parser.add_argument("--dry-run", action="store_true", help="Print planned links without changing files.")
    parser.add_argument(
        "--force",
        action="store_true",
        help="Replace existing copied files or directories with symlinks.",
    )
    parser.add_argument(
        "--codex-home",
        default=os.environ.get("CODEX_HOME"),
        help="Codex home directory. Defaults to CODEX_HOME and errors if unset.",
    )
    parser.add_argument(
        "--claude-home",
        default=os.environ.get("CLAUDE_CONFIG_DIR"),
        help="Claude config directory. Defaults to CLAUDE_CONFIG_DIR and errors if unset.",
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
    skill_directories = []
    for skill_file_path in sorted(agents_repo_path.rglob("SKILL.md")):
        if not _is_user_skill_file(agents_repo_path, skill_file_path):
            continue
        skill_source_path = skill_file_path.parent
        if skill_source_path.name == "skill":
            skill_name = skill_source_path.parent.name
        else:
            skill_name = skill_source_path.name
        skill_directories.append(SkillDirectory(name=skill_name, source_path=skill_source_path))
    _raise_for_duplicate_skill_names(skill_directories)
    return skill_directories


def _is_user_skill_file(agents_repo_path: Path, skill_file_path: Path) -> bool:
    relative_parts = skill_file_path.relative_to(agents_repo_path).parts
    return not any(part.startswith(".") for part in relative_parts)


def _raise_for_duplicate_skill_names(skill_directories: list[SkillDirectory]) -> None:
    skill_paths_by_name: dict[str, list[Path]] = {}
    for skill_directory in skill_directories:
        skill_paths_by_name.setdefault(skill_directory.name, []).append(skill_directory.source_path)

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

    _require_agent_home_paths(arguments)

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


def _require_agent_home_paths(arguments: argparse.Namespace) -> None:
    if not arguments.claude_only and not arguments.codex_home:
        raise RuntimeError("CODEX_HOME must be set or --codex-home must be provided.")
    if not arguments.codex_only and not arguments.claude_home:
        raise RuntimeError("CLAUDE_CONFIG_DIR must be set or --claude-home must be provided.")


def _build_agent_instructions_links(
    arguments: argparse.Namespace,
    agents_repo_path: Path,
) -> list[AgentInstructionsLink]:
    instruction_links: list[AgentInstructionsLink] = []

    if not arguments.claude_only:
        instruction_links.append(
            AgentInstructionsLink(
                agent_name="Codex",
                source_path=agents_repo_path / "AGENTS.md",
                destination_path=Path(arguments.codex_home).expanduser() / "AGENTS.md",
            )
        )
    if not arguments.codex_only:
        instruction_links.append(
            AgentInstructionsLink(
                agent_name="Claude",
                source_path=agents_repo_path / "AGENTS.md",
                destination_path=Path(arguments.claude_home).expanduser() / "AGENTS.md",
            )
        )

    return instruction_links


def _install_skill_directory(
    skill_directory: SkillDirectory,
    install_target: SkillInstallTarget,
    dry_run: bool,
    force: bool,
) -> None:
    destination_path = install_target.skills_path / skill_directory.name
    if destination_path.is_symlink() and destination_path.resolve() == skill_directory.source_path.resolve():
        print(f"{install_target.agent_name}: already linked {destination_path} -> {skill_directory.source_path}")
        return

    if destination_path.exists() or destination_path.is_symlink():
        if force:
            _replace_existing_path_with_link(
                destination_path=destination_path,
                source_path=skill_directory.source_path,
                agent_name=install_target.agent_name,
                dry_run=dry_run,
                target_is_directory=True,
            )
            return
        raise FileExistsError(
            f"{install_target.agent_name}: refusing to replace existing path: {destination_path}"
        )

    if dry_run:
        print(f"{install_target.agent_name}: would link {destination_path} -> {skill_directory.source_path}")
        return

    install_target.skills_path.mkdir(parents=True, exist_ok=True)
    destination_path.symlink_to(skill_directory.source_path, target_is_directory=True)
    print(f"{install_target.agent_name}: linked {destination_path} -> {skill_directory.source_path}")


def _install_agent_instructions_link(
    instruction_link: AgentInstructionsLink,
    dry_run: bool,
    force: bool,
) -> None:
    if (
        instruction_link.destination_path.is_symlink()
        and instruction_link.destination_path.resolve() == instruction_link.source_path.resolve()
    ):
        print(
            f"{instruction_link.agent_name}: already linked "
            f"{instruction_link.destination_path} -> {instruction_link.source_path}"
        )
        return

    if instruction_link.destination_path.exists() or instruction_link.destination_path.is_symlink():
        if force:
            _replace_existing_path_with_link(
                destination_path=instruction_link.destination_path,
                source_path=instruction_link.source_path,
                agent_name=instruction_link.agent_name,
                dry_run=dry_run,
                target_is_directory=False,
            )
            return
        if (
            instruction_link.destination_path.read_text(encoding="utf-8")
            != instruction_link.source_path.read_text(encoding="utf-8")
        ):
            raise FileExistsError(
                f"{instruction_link.agent_name}: refusing to replace differing file: "
                f"{instruction_link.destination_path}"
            )
        if dry_run:
            print(
                f"{instruction_link.agent_name}: would replace identical file with link "
                f"{instruction_link.destination_path} -> {instruction_link.source_path}"
            )
            return
        instruction_link.destination_path.unlink()

    if dry_run:
        print(
            f"{instruction_link.agent_name}: would link "
            f"{instruction_link.destination_path} -> {instruction_link.source_path}"
        )
        return

    instruction_link.destination_path.parent.mkdir(parents=True, exist_ok=True)
    instruction_link.destination_path.symlink_to(instruction_link.source_path)
    print(
        f"{instruction_link.agent_name}: linked "
        f"{instruction_link.destination_path} -> {instruction_link.source_path}"
    )


def _replace_existing_path_with_link(
    destination_path: Path,
    source_path: Path,
    agent_name: str,
    dry_run: bool,
    target_is_directory: bool,
) -> None:
    if dry_run:
        print(f"{agent_name}: would replace {destination_path} with link -> {source_path}")
        return

    _remove_existing_destination_path(destination_path)
    destination_path.parent.mkdir(parents=True, exist_ok=True)
    destination_path.symlink_to(source_path, target_is_directory=target_is_directory)
    print(f"{agent_name}: replaced {destination_path} with link -> {source_path}")


def _remove_existing_destination_path(destination_path: Path) -> None:
    if destination_path.is_symlink() or destination_path.is_file():
        destination_path.unlink()
        return

    if destination_path.is_dir():
        shutil.rmtree(destination_path)
        return

    raise FileNotFoundError(destination_path)


if __name__ == "__main__":
    main()
