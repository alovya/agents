from __future__ import annotations

import contextlib
import os
import shlex
import shutil
import subprocess
from pathlib import Path
from typing import TYPE_CHECKING, Iterator

if TYPE_CHECKING:
    from ralph.agent_backends import AgentBackend


WORKER_HOME_PATH = Path("/tmp/ralph-worker-home")
WORKER_TEMP_PATH = Path("/tmp/ralph-worker-tmp")
WORKER_AGENT_BINARY_PATH = Path("/tmp/ralph-agent-bin/agent")
DEFAULT_RALPH_HOME_PATH = Path("/workspace/.ralph")


def resolve_ralph_home_path() -> Path:
    configured_path = os.environ.get("RALPH_HOME")
    if configured_path:
        return Path(configured_path).expanduser().resolve()
    return DEFAULT_RALPH_HOME_PATH


def build_bwrap_agent_command(
    repo_path: Path,
    backend_config: "AgentBackend",
    python_venv_path: Path | None,
    allowed_bash_commands: list[str] | None = None,
) -> list[str]:
    from ralph.agent_backends import build_agent_command_tail

    bwrap_path = shutil.which("bwrap")
    if bwrap_path is None:
        raise RuntimeError("Ralph requires bubblewrap installed as `bwrap`.")

    host_agent_binary_path = _resolve_agent_binary_path(backend_config.command_name)

    command = [bwrap_path]
    command += ["--tmpfs", "/"]
    command += ["--dir", "/tmp"]
    command += _build_bwrap_runtime_mount_options()
    command += _build_bwrap_sandbox_mount_target_dir_options(WORKER_AGENT_BINARY_PATH, create_target_dir=False)
    command += ["--ro-bind", str(host_agent_binary_path), str(WORKER_AGENT_BINARY_PATH)]
    command += _build_bwrap_sandbox_mount_target_dir_options(repo_path)
    command += ["--bind", str(repo_path), str(repo_path)]
    command += ["--dev", "/dev"]

    command += _build_bwrap_agent_home_mount_options(backend_config.agent_state_dir)
    command += _build_bwrap_sandbox_mount_target_dir_options(WORKER_HOME_PATH)
    command += _build_bwrap_sandbox_mount_target_dir_options(WORKER_TEMP_PATH)

    if python_venv_path is not None:
        command += _build_bwrap_sandbox_mount_target_dir_options(python_venv_path)
        command += ["--ro-bind", str(python_venv_path), str(python_venv_path)]

    command += ["--clearenv"]
    command += _build_bwrap_worker_environment_options(
        agent_home_environment_variable=backend_config.agent_home_environment_variable,
        agent_state_dir=backend_config.agent_state_dir,
        python_venv_path=python_venv_path,
    )

    command += [str(WORKER_AGENT_BINARY_PATH)]
    command += build_agent_command_tail(
        backend_config=backend_config,
        repo_path=repo_path,
        allowed_bash_commands=allowed_bash_commands or [],
    )
    return command


def run_agent_visibility_smoke_test(
    repo_path: Path,
    agent_backend: str,
    agent_command: str | None,
    python_venv_path: Path | None,
) -> None:
    from ralph.agent_backends import extract_agent_result_text, select_agent_backend_config

    if not repo_path.is_dir():
        raise FileNotFoundError(f"Target repo does not exist: {repo_path}")
    reject_worker_visible_path_that_overlaps_hidden_state(
        path=repo_path,
        role="Target repo",
    )
    backend_config = select_agent_backend_config(
        agent_backend=agent_backend,
        agent_command=agent_command,
    )
    prompt = build_agent_visibility_smoke_test_prompt(
        repo_path=repo_path,
        backend_config=backend_config,
        python_venv_path=python_venv_path,
    )
    allowed_bash_commands = [_build_agent_visibility_smoke_test_agent_command(
        repo_path=repo_path,
        backend_config=backend_config,
        python_venv_path=python_venv_path,
    )]
    command = build_bwrap_agent_command(
        repo_path=repo_path,
        backend_config=backend_config,
        python_venv_path=python_venv_path,
        allowed_bash_commands=allowed_bash_commands,
    )
    completed_process = subprocess.run(
        command,
        input=prompt,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )
    if completed_process.returncode != 0:
        raise RuntimeError(f"Ralph agent sandbox smoke test failed:\n{completed_process.stdout}")
    output = extract_agent_result_text(
        backend_config=backend_config,
        raw_output=completed_process.stdout or "",
    )
    if _find_last_non_empty_line(output) != "RALPH_SANDBOX_OK":
        raise RuntimeError(f"Ralph agent sandbox smoke test did not prove isolation:\n{completed_process.stdout}")


def build_agent_visibility_smoke_test_prompt(
    repo_path: Path,
    backend_config: "AgentBackend",
    python_venv_path: Path | None,
) -> str:
    shell_command = _build_agent_visibility_smoke_test_agent_command(
        repo_path=repo_path,
        backend_config=backend_config,
        python_venv_path=python_venv_path,
    )
    return "\n".join(
        [
            "Run exactly this shell command:",
            shell_command,
            "Then answer only the final line it prints.",
        ]
    )


def _build_agent_visibility_smoke_test_agent_command(
    repo_path: Path,
    backend_config: "AgentBackend",
    python_venv_path: Path | None,
) -> str:
    shell_command = _build_agent_visibility_smoke_test_shell_command(
        repo_path=repo_path,
        backend_config=backend_config,
        python_venv_path=python_venv_path,
    )
    return f"bash -lc {quote_shell_value(shell_command)}"


def _build_agent_visibility_smoke_test_shell_command(
    repo_path: Path,
    backend_config: "AgentBackend",
    python_venv_path: Path | None,
) -> str:
    hidden_paths = _remove_paths_that_overlap_explicit_mounts(
        hidden_paths=build_sensitive_paths_that_workers_must_not_see(),
        explicitly_visible_paths=build_explicit_worker_mount_paths(
            repo_path=repo_path,
            agent_state_dir=backend_config.agent_state_dir,
            python_venv_path=python_venv_path,
        ),
    )
    command_parts = ["set -eu"]
    command_parts += _build_shell_assertions_that_paths_are_hidden(hidden_paths)
    command_parts += _build_shell_assertions_that_environment_variables_are_absent(
        build_credential_environment_variables_that_workers_must_not_receive()
    )
    command_parts += _build_shell_assertions_that_unselected_backend_environment_variables_are_absent(
        selected_agent_home_environment_variable=backend_config.agent_home_environment_variable,
    )
    command_parts += _build_shell_assertions_that_worker_environment_matches_bwrap_setenv_options(
        _build_backend_state_environment_variables_to_verify_exactly(
            agent_home_environment_variable=backend_config.agent_home_environment_variable,
            agent_state_dir=backend_config.agent_state_dir,
            python_venv_path=python_venv_path,
        )
    )
    command_parts += _build_shell_assertions_that_repo_is_writable(repo_path)
    if python_venv_path is not None:
        command_parts += _build_shell_assertions_that_python_venv_is_read_only(python_venv_path)
    command_parts += ["echo RALPH_SANDBOX_OK"]
    return " && ".join(command_parts)


def build_explicit_worker_mount_paths(
    repo_path: Path,
    agent_state_dir: Path,
    python_venv_path: Path | None,
) -> list[Path]:
    explicitly_visible_paths = [repo_path, agent_state_dir]
    if python_venv_path is not None:
        explicitly_visible_paths.append(python_venv_path)
    return explicitly_visible_paths


def build_sensitive_paths_that_workers_must_not_see() -> list[Path]:
    return [
        resolve_ralph_home_path(),
        Path.home() / ".ralph",
        Path.home() / ".notion-task-tracker",
        Path.home() / ".ssh",
        Path.home() / ".aws",
        Path.home() / ".azure",
        Path.home() / ".claude",
        Path.home() / ".config",
        Path.home() / ".cache",
        Path.home() / ".docker",
        Path.home() / ".gnupg",
        Path.home() / ".kube",
        Path.home() / ".local" / "share",
        Path.home() / ".local" / "state",
        Path("/workspace/.notion-task-tracker"),
        Path("/workspace/.ssh"),
        Path("/workspace/.aws"),
        Path("/workspace/.azure"),
        Path("/workspace/.claude"),
        Path("/workspace/.config"),
        Path("/workspace/.cache"),
        Path("/workspace/.codex"),
        Path("/workspace/.docker"),
        Path("/workspace/.gnupg"),
        Path("/workspace/.kube"),
    ]


def build_credential_environment_variables_that_workers_must_not_receive() -> list[str]:
    return [
        "NOTION_API_KEY",
        "OPENAI_API_KEY",
        "SSH_AUTH_SOCK",
        "AWS_ACCESS_KEY_ID",
        "AWS_SECRET_ACCESS_KEY",
        "AZURE_TOKEN",
        "GITHUB_TOKEN",
    ]


def _build_agent_home_environment_variables() -> list[str]:
    return ["CODEX_HOME", "CLAUDE_CONFIG_DIR"]


def _build_shell_assertions_that_unselected_backend_environment_variables_are_absent(
    selected_agent_home_environment_variable: str,
) -> list[str]:
    return _build_shell_assertions_that_environment_variables_are_absent(
        [
            variable_name
            for variable_name in _build_agent_home_environment_variables()
            if variable_name != selected_agent_home_environment_variable
        ]
    )


def _remove_paths_that_overlap_explicit_mounts(
    hidden_paths: list[Path],
    explicitly_visible_paths: list[Path],
) -> list[Path]:
    return [
        hidden_path
        for hidden_path in hidden_paths
        if not any(
            paths_overlap(left_path=hidden_path, right_path=visible_path)
            for visible_path in explicitly_visible_paths
        )
    ]


def paths_overlap(left_path: Path, right_path: Path) -> bool:
    resolved_left_path = left_path.resolve()
    resolved_right_path = right_path.resolve()
    return (
        paths_resolve_to_same_location(left_path=resolved_left_path, right_path=resolved_right_path)
        or resolved_left_path.is_relative_to(resolved_right_path)
        or resolved_right_path.is_relative_to(resolved_left_path)
    )


def paths_resolve_to_same_location(left_path: Path, right_path: Path) -> bool:
    return left_path.resolve() == right_path.resolve()


def _build_shell_assertions_that_paths_are_hidden(paths: list[Path]) -> list[str]:
    return [
        f"test ! -e {quote_shell_path(path)} || {{ echo RALPH_SANDBOX_LEAKED_PATH {quote_shell_path(path)}; exit 1; }}"
        for path in paths
    ]


def _build_shell_assertions_that_environment_variables_are_absent(variable_names: list[str]) -> list[str]:
    return [
        f"test -z \"${{{variable_name}:-}}\" || {{ echo RALPH_SANDBOX_LEAKED_VARIABLE {variable_name}; exit 1; }}"
        for variable_name in variable_names
    ]


def _build_shell_assertions_that_worker_environment_matches_bwrap_setenv_options(
    environment_variables: list[tuple[str, str]],
) -> list[str]:
    return [
        (
            f"test \"${{{variable_name}-}}\" = {quote_shell_value(value)} || "
            f"{{ echo RALPH_SANDBOX_ENV_MISMATCH {variable_name}; exit 1; }}"
        )
        for variable_name, value in environment_variables
    ]


def _build_backend_state_environment_variables_to_verify_exactly(
    agent_home_environment_variable: str,
    agent_state_dir: Path,
    python_venv_path: Path | None,
) -> list[tuple[str, str]]:
    environment_variables = [(agent_home_environment_variable, str(agent_state_dir))]
    if python_venv_path is not None:
        environment_variables.append(("VIRTUAL_ENV", str(python_venv_path)))
    return environment_variables


def _build_shell_assertions_that_repo_is_writable(repo_path: Path) -> list[str]:
    probe_path = repo_path / ".ralph-sandbox-write-test-dir"
    return [
        f"mkdir {quote_shell_path(probe_path)}",
        f"rmdir {quote_shell_path(probe_path)}",
    ]


def _build_shell_assertions_that_python_venv_is_read_only(python_venv_path: Path) -> list[str]:
    return [
        f"test -d {quote_shell_path(python_venv_path)}",
        _build_shell_assertion_that_mount_point_is_read_only(python_venv_path),
        f"test \"$VIRTUAL_ENV\" = {quote_shell_value(python_venv_path)}",
    ]


def _build_shell_assertion_that_mount_point_is_read_only(mount_path: Path) -> str:
    quoted_mount_path = quote_shell_value(mount_path)
    return (
        "ralph_found_read_only_mount=0; "
        "while read -r _ _ _ _ ralph_mount_path ralph_mount_options _; do "
        f"if test \"$ralph_mount_path\" = {quoted_mount_path}; then "
        "case \",$ralph_mount_options,\" in "
        "*,ro,*) ralph_found_read_only_mount=1 ;; "
        "*) echo RALPH_SANDBOX_WRITABLE_VENV; exit 1 ;; "
        "esac; "
        "fi; "
        "done < /proc/self/mountinfo; "
        "test \"$ralph_found_read_only_mount\" = 1"
    )


def quote_shell_path(path: Path) -> str:
    return shlex.quote(str(path))


def quote_shell_value(value: Path | str) -> str:
    return shlex.quote(str(value))


def _build_bwrap_worker_environment_options(
    agent_home_environment_variable: str,
    agent_state_dir: Path,
    python_venv_path: Path | None,
) -> list[str]:
    environment_variables = [
        ("HOME", str(WORKER_HOME_PATH)),
        ("TMPDIR", str(WORKER_TEMP_PATH)),
        (agent_home_environment_variable, str(agent_state_dir)),
        ("XDG_CONFIG_HOME", str(WORKER_HOME_PATH / ".config")),
        ("XDG_CACHE_HOME", str(WORKER_HOME_PATH / ".cache")),
        ("XDG_DATA_HOME", str(WORKER_HOME_PATH / ".local" / "share")),
        ("AZURE_CONFIG_DIR", str(WORKER_HOME_PATH / ".azure")),
        ("DOCKER_CONFIG", str(WORKER_HOME_PATH / ".docker")),
        ("GNUPGHOME", str(WORKER_HOME_PATH / ".gnupg")),
        ("KUBECONFIG", str(WORKER_HOME_PATH / ".kube" / "config")),
        ("SSL_CERT_FILE", "/etc/ssl/certs/ca-certificates.crt"),
        ("PATH", _build_agent_path_value(python_venv_path)),
    ]

    if python_venv_path is not None:
        environment_variables.append(("VIRTUAL_ENV", str(python_venv_path)))

    options: list[str] = []
    for variable_name, value in environment_variables:
        options += ["--setenv", variable_name, value]
    return options


def _build_bwrap_runtime_mount_options() -> list[str]:
    options = ["--proc", "/proc"]
    options += _build_bwrap_host_os_runtime_mount_options()
    options += _build_bwrap_minimal_host_etc_file_mount_options()
    return options


def _build_bwrap_minimal_host_etc_file_mount_options() -> list[str]:
    options: list[str] = []
    options += _build_bwrap_read_only_file_mount_options(
        host_path=Path("/etc/hosts"),
        sandbox_path=Path("/etc/hosts"),
    )
    options += _build_bwrap_read_only_file_mount_options(
        host_path=Path("/etc/resolv.conf").resolve(),
        sandbox_path=Path("/etc/resolv.conf"),
    )
    options += _build_bwrap_read_only_file_mount_options(
        host_path=Path("/etc/nsswitch.conf"),
        sandbox_path=Path("/etc/nsswitch.conf"),
    )
    options += _build_bwrap_read_only_file_mount_options(
        host_path=Path("/etc/os-release"),
        sandbox_path=Path("/etc/os-release"),
    )
    options += _build_bwrap_read_only_file_mount_options(
        host_path=Path("/etc/ld.so.cache"),
        sandbox_path=Path("/etc/ld.so.cache"),
    )
    options += _build_bwrap_read_only_file_mount_options(
        host_path=Path("/etc/ssl/certs/ca-certificates.crt"),
        sandbox_path=Path("/etc/ssl/certs/ca-certificates.crt"),
    )
    return options


def _build_bwrap_host_os_runtime_mount_options() -> list[str]:
    options = _build_bwrap_read_only_dir_mount_options(
        host_path=Path("/usr"),
        sandbox_path=Path("/usr"),
    )
    for compatibility_path in [Path("/bin"), Path("/lib"), Path("/lib64"), Path("/sbin")]:
        options += _build_bwrap_host_os_compatibility_mount_options(compatibility_path)
    return options


def _build_bwrap_host_os_compatibility_mount_options(compatibility_path: Path) -> list[str]:
    if compatibility_path.is_symlink():
        return ["--symlink", os.readlink(compatibility_path), str(compatibility_path)]
    return _build_bwrap_read_only_dir_mount_options(
        host_path=compatibility_path,
        sandbox_path=compatibility_path,
    )


def _build_bwrap_agent_home_mount_options(agent_state_dir: Path) -> list[str]:
    options = _build_bwrap_sandbox_mount_target_dir_options(agent_state_dir)
    options += ["--bind", str(agent_state_dir), str(agent_state_dir)]
    if (agent_state_dir / ".tmp").is_dir():
        options += ["--tmpfs", str(agent_state_dir / ".tmp")]
    return options


def _build_bwrap_read_only_file_mount_options(host_path: Path, sandbox_path: Path) -> list[str]:
    if not host_path.is_file():
        return []

    options = _build_bwrap_sandbox_mount_target_dir_options(sandbox_path, create_target_dir=False)
    options += ["--ro-bind", str(host_path), str(sandbox_path)]
    return options


def _build_bwrap_read_only_dir_mount_options(host_path: Path, sandbox_path: Path) -> list[str]:
    if not host_path.is_dir():
        return []

    options = _build_bwrap_sandbox_mount_target_dir_options(sandbox_path)
    options += ["--ro-bind", str(host_path), str(sandbox_path)]
    return options


def _build_bwrap_sandbox_mount_target_dir_options(path: Path, *, create_target_dir: bool = True) -> list[str]:
    path_parts = path.resolve().parts[1:]
    if not create_target_dir:
        path_parts = path_parts[:-1]

    options: list[str] = []
    current_path = Path("/")
    for part in path_parts:
        current_path = current_path / part
        options.extend(["--dir", str(current_path)])
    return options


def _resolve_agent_binary_path(agent_command: str) -> Path:
    resolved_command = shutil.which(agent_command)
    if resolved_command is None:
        raise RuntimeError(f"Agent command not found: {agent_command}")
    return Path(resolved_command).resolve()


def _build_agent_path_value(python_venv_path: Path | None) -> str:
    path_entries = []
    if python_venv_path is not None:
        path_entries.append(str(python_venv_path / "bin"))
    path_entries.extend(
        [
            "/usr/local/sbin",
            "/usr/local/bin",
            "/usr/sbin",
            "/usr/bin",
            "/sbin",
            "/bin",
        ]
    )
    return ":".join(
        path_entries
    )


def _find_last_non_empty_line(text: str) -> str:
    for line in reversed(text.splitlines()):
        if line.strip():
            return line.strip()
    return ""


def resolve_python_venv_path(python_venv: str | None) -> Path | None:
    if python_venv is None:
        python_venv = os.environ.get("VIRTUAL_ENV")
    if python_venv is None:
        return None

    python_venv_path = Path(python_venv).expanduser().resolve()
    if not python_venv_path.is_dir():
        raise FileNotFoundError(f"Python venv does not exist: {python_venv_path}")
    if not (python_venv_path / "bin" / "python").is_file():
        raise FileNotFoundError(f"Python venv is missing bin/python: {python_venv_path}")
    reject_worker_visible_path_that_overlaps_hidden_state(
        path=python_venv_path,
        role="Python venv",
    )
    return python_venv_path


def reject_worker_visible_path_that_overlaps_hidden_state(path: Path, role: str) -> None:
    for sensitive_path in build_sensitive_paths_that_workers_must_not_see():
        if paths_overlap(left_path=path, right_path=sensitive_path):
            raise ValueError(
                f"{role} must not overlap worker-hidden sensitive state: "
                f"{path} overlaps {sensitive_path}"
            )


@contextlib.contextmanager
def backend_permission_setup(
    backend_config: "AgentBackend",
    allowed_bash_commands: list[str],
    task_path: Path | None,
) -> Iterator[None]:
    from ralph.codex_backend import codex_permission_setup

    if backend_config.backend_name == "codex" and task_path is not None:
        with codex_permission_setup(
            backend_config=backend_config,
            allowed_bash_commands=allowed_bash_commands,
            task_path=task_path,
        ):
            yield
    else:
        with _claude_permission_setup():
            yield


@contextlib.contextmanager
def _claude_permission_setup() -> Iterator[None]:
    yield
