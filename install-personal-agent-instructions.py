from __future__ import annotations

import argparse
import os
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class SkillDirectory:
    name: str
    source_path: Path


@dataclass(frozen=True)
class AgentVendor:
    display_name: str
    home_env_var: str
    cli_arg_home: str
    cli_arg_only: str
    instructions_filename: str | None


AGENT_VENDORS = [
    AgentVendor(
        display_name="Codex",
        home_env_var="CODEX_HOME",
        cli_arg_home="--codex-home",
        cli_arg_only="--codex-only",
        instructions_filename="AGENTS.md",
    ),
    AgentVendor(
        display_name="Claude",
        home_env_var="CLAUDE_CONFIG_DIR",
        cli_arg_home="--claude-config-dir",
        cli_arg_only="--claude-only",
        instructions_filename="CLAUDE.md",
    ),
    AgentVendor(
        display_name="Cursor",
        home_env_var="CURSOR_HOME",
        cli_arg_home="--cursor-home",
        cli_arg_only="--cursor-only",
        instructions_filename=None,  # Cursor instructions are managed in ~/.bashrc, not via file link
    ),
]


@dataclass(frozen=True)
class AgentHome:
    vendor: AgentVendor
    home_path: Path


@dataclass(frozen=True)
class SkillInstallTarget:
    vendor: AgentVendor
    skills_path: Path


@dataclass(frozen=True)
class AgentInstructionsLink:
    vendor: AgentVendor
    source_path: Path
    destination_path: Path


def main() -> None:
    arguments = _parse_arguments()
    agents_repo_path = Path(__file__).resolve().parent
    skill_directories = _find_skill_directories(agents_repo_path)
    agent_homes = _find_configured_agent_homes(arguments)
    install_targets = _build_skill_install_targets(agent_homes)
    instruction_links = _build_agent_instructions_links(
        agent_homes=agent_homes,
        agents_repo_path=agents_repo_path,
    )

    if not skill_directories:
        print(f"No skills found under {agents_repo_path}")

    for agent_home in agent_homes:
        print(f"\n=== {agent_home.vendor.display_name} ===")
        # Find target and link for this agent
        install_target = next(t for t in install_targets if t.vendor.display_name == agent_home.vendor.display_name)
        
        for skill_directory in skill_directories:
            _install_skill_directory(
                skill_directory=skill_directory,
                install_target=install_target,
                dry_run=arguments.dry_run,
                force=arguments.force,
            )
            
        if agent_home.vendor.instructions_filename is not None:
            instruction_link = next(l for l in instruction_links if l.vendor.display_name == agent_home.vendor.display_name)
            _install_agent_instructions_link(
                instruction_link=instruction_link,
                dry_run=arguments.dry_run,
                force=arguments.force,
            )
        else:
            pass # Instructions handled externally (e.g. cursor_cli alias in bashrc)


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
    for vendor in AGENT_VENDORS:
        parser.add_argument(
            vendor.cli_arg_home,
            default=os.environ.get(vendor.home_env_var),
            help=f"{vendor.display_name} home directory. Defaults to {vendor.home_env_var}; skips if unset.",
        )
        parser.add_argument(
            vendor.cli_arg_only,
            action="store_true",
            help=f"Install only {vendor.display_name} skill links.",
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


def _find_configured_agent_homes(arguments: argparse.Namespace) -> list[AgentHome]:
    only_flags = sum([getattr(arguments, vendor.cli_arg_only.lstrip("-").replace("-", "_")) for vendor in AGENT_VENDORS])
    if only_flags > 1:
        flag_names = ", ".join(v.cli_arg_only for v in AGENT_VENDORS)
        raise RuntimeError(f"Choose at most one of {flag_names}.")

    configured_agent_homes = []
    for vendor in AGENT_VENDORS:
        is_only_target = getattr(arguments, vendor.cli_arg_only.lstrip("-").replace("-", "_"))
        if only_flags > 0 and not is_only_target:
            continue
            
        home_path = getattr(arguments, vendor.cli_arg_home.lstrip("-").replace("-", "_"))
        if not home_path:
            print(
                f"Warning: skipping {vendor.display_name} because {vendor.home_env_var} is unset "
                f"and {vendor.cli_arg_home} was not provided.",
                file=sys.stderr,
            )
            continue
        configured_agent_homes.append(
            AgentHome(vendor=vendor, home_path=Path(home_path).expanduser())
        )

    return configured_agent_homes


def _build_skill_install_targets(agent_homes: list[AgentHome]) -> list[SkillInstallTarget]:
    return [
        SkillInstallTarget(
            vendor=agent_home.vendor,
            skills_path=agent_home.home_path / "skills",
        )
        for agent_home in agent_homes
    ]


def _build_agent_instructions_links(
    agent_homes: list[AgentHome],
    agents_repo_path: Path,
) -> list[AgentInstructionsLink]:
    return [
        AgentInstructionsLink(
            vendor=agent_home.vendor,
            source_path=agents_repo_path / "AGENTS.md",
            destination_path=agent_home.home_path / agent_home.vendor.instructions_filename,
        )
        for agent_home in agent_homes
        if agent_home.vendor.instructions_filename is not None
    ]


def _install_skill_directory(
    skill_directory: SkillDirectory,
    install_target: SkillInstallTarget,
    dry_run: bool,
    force: bool,
) -> None:
    destination_path = install_target.skills_path / skill_directory.name
    if destination_path.is_symlink() and destination_path.resolve() == skill_directory.source_path.resolve():
        print(f"  already linked {destination_path} -> {skill_directory.source_path}")
        return

    if destination_path.exists() or destination_path.is_symlink():
        if force:
            _replace_existing_path_with_link(
                destination_path=destination_path,
                source_path=skill_directory.source_path,
                agent_name=install_target.vendor.display_name,
                dry_run=dry_run,
                target_is_directory=True,
            )
            return
        raise FileExistsError(
            f"  refusing to replace existing path: {destination_path}"
        )

    if dry_run:
        print(f"  would link {destination_path} -> {skill_directory.source_path}")
        return

    install_target.skills_path.mkdir(parents=True, exist_ok=True)
    destination_path.symlink_to(skill_directory.source_path, target_is_directory=True)
    print(f"  linked {destination_path} -> {skill_directory.source_path}")


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
            f"  already linked "
            f"{instruction_link.destination_path} -> {instruction_link.source_path}"
        )
        return

    if instruction_link.destination_path.exists() or instruction_link.destination_path.is_symlink():
        if force:
            _replace_existing_path_with_link(
                destination_path=instruction_link.destination_path,
                source_path=instruction_link.source_path,
                agent_name=instruction_link.vendor.display_name,
                dry_run=dry_run,
                target_is_directory=False,
            )
            return
        if (
            instruction_link.destination_path.read_text(encoding="utf-8")
            != instruction_link.source_path.read_text(encoding="utf-8")
        ):
            raise FileExistsError(
                f"  refusing to replace differing file: "
                f"{instruction_link.destination_path}"
            )
        if dry_run:
            print(
                f"{instruction_link.vendor.display_name}: would replace identical file with link "
                f"{instruction_link.destination_path} -> {instruction_link.source_path}"
            )
            return
        instruction_link.destination_path.unlink()

    if dry_run:
        print(
            f"  would link "
            f"{instruction_link.destination_path} -> {instruction_link.source_path}"
        )
        return

    instruction_link.destination_path.parent.mkdir(parents=True, exist_ok=True)
    instruction_link.destination_path.symlink_to(instruction_link.source_path)
    print(
        f"{instruction_link.vendor.display_name}: linked "
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
        print(f"  would replace {destination_path} with link -> {source_path}")
        return

    _remove_existing_destination_path(destination_path)
    destination_path.parent.mkdir(parents=True, exist_ok=True)
    destination_path.symlink_to(source_path, target_is_directory=target_is_directory)
    print(f"  replaced {destination_path} with link -> {source_path}")


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
