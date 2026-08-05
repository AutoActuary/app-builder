from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path, PureWindowsPath

from .schema import AppBuilderConfig

_WINDOWS_RESERVED_NAMES = {
    "aux",
    "con",
    "nul",
    "prn",
    *(f"com{number}" for number in range(1, 10)),
    *(f"lpt{number}" for number in range(1, 10)),
}
_EXACT_PYTHON_VERSION = re.compile(r"^[0-9]+\.[0-9]+\.[0-9]+$")
_ENV_REFERENCE = re.compile(r"%([^%]+)%")


def validate_build_configuration(
    project_root: Path,
    config: AppBuilderConfig,
    *,
    version: str,
) -> None:
    _validate_windows_name(config.installer.name, label="installer.name")
    _validate_release_version(project_root, version)
    _validate_project_directory(
        project_root, config.installer.dist, label="installer.dist"
    )
    _validate_install_directory(config.installer.install_directory)
    _validate_python_version(config.python_bundled, label="python_bundled")
    _validate_python_version(config.python_venv, label="python_venv")
    if config.python_bundled is not None:
        _validate_project_directory(
            project_root, config.python_bundled.path, label="python_bundled.path"
        )
    if config.python_venv is not None:
        _validate_project_directory(
            project_root, config.python_venv.path, label="python_venv.path"
        )
    _validate_hook_commands(config)


def _validate_windows_name(value: str, *, label: str) -> None:
    if not value or value.strip() != value:
        raise ValueError(f"{label} must be a non-empty, trimmed Windows name.")
    if any(ord(character) < 32 or character in '<>:"/\\|?*' for character in value):
        raise ValueError(
            f"{label} contains characters that are invalid in Windows filenames."
        )
    if value.endswith((" ", ".")):
        raise ValueError(f"{label} must not end with a space or period.")
    if value.split(".", 1)[0].casefold() in _WINDOWS_RESERVED_NAMES:
        raise ValueError(f"{label} is a reserved Windows device name.")
    if not any(character.isalnum() for character in value):
        raise ValueError(f"{label} must contain at least one letter or number.")


def _validate_release_version(project_root: Path, version: str) -> None:
    if (
        not version
        or version.strip() != version
        or any(character.isspace() for character in version)
    ):
        raise ValueError(f"Release version is invalid: {version!r}.")
    result = subprocess.run(
        ["git", "check-ref-format", f"refs/tags/{version}"],
        cwd=project_root,
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise ValueError(f"Release version is not a valid Git tag name: {version!r}.")
    _validate_windows_name(version, label="release version")


def _validate_project_directory(project_root: Path, value: str, *, label: str) -> None:
    path = Path(value)
    if (
        not value.strip()
        or path.is_absolute()
        or ".." in path.parts
        or path == Path(".")
    ):
        raise ValueError(f"{label} must be a project-relative subdirectory.")
    try:
        (project_root / path).resolve().relative_to(project_root.resolve())
    except ValueError as error:
        raise ValueError(f"{label} must resolve inside the project.") from error


def _validate_install_directory(value: str) -> None:
    if not value or value.strip() != value:
        raise ValueError(
            "installer.install_directory must be a non-empty, trimmed path."
        )
    windows_path = PureWindowsPath(value)
    references = [name.casefold() for name in _ENV_REFERENCE.findall(value)]
    if references:
        if len(references) != 1 or not value.casefold().startswith(
            f"%{references[0]}%\\"
        ):
            raise ValueError(
                "installer.install_directory must use one leading percent-style environment variable."
            )
        if references[0] not in {"localappdata", "appdata", "userprofile"}:
            raise ValueError(
                "installer.install_directory may be rooted only below %LOCALAPPDATA%, "
                "%APPDATA%, or %USERPROFILE%."
            )
        if len(windows_path.parts) < 2:
            raise ValueError(
                "installer.install_directory must name an application subdirectory."
            )
        return

    if not windows_path.is_absolute():
        raise ValueError(
            "installer.install_directory must be absolute or begin with %LOCALAPPDATA%, "
            "%APPDATA%, or %USERPROFILE%."
        )
    if len(windows_path.parts) <= 1:
        raise ValueError(
            "installer.install_directory must not be a drive or filesystem root."
        )

    resolved = os.path.normcase(os.path.abspath(os.path.expandvars(value)))
    user_roots = {
        os.path.normcase(os.path.abspath(path))
        for path in (
            os.environ.get("LOCALAPPDATA", ""),
            os.environ.get("APPDATA", ""),
            os.environ.get("USERPROFILE", ""),
        )
        if path
    }
    protected_roots = {
        os.path.normcase(os.path.abspath(path))
        for path in (
            os.environ.get("WINDIR", ""),
            os.environ.get("ProgramFiles", ""),
            os.environ.get("ProgramFiles(x86)", ""),
        )
        if path
    }
    if resolved in user_roots:
        raise ValueError(
            "installer.install_directory must name an application subdirectory."
        )
    for protected_root in protected_roots:
        try:
            is_protected = (
                os.path.commonpath((resolved, protected_root)) == protected_root
            )
        except ValueError:
            continue
        if is_protected:
            raise ValueError(
                "installer.install_directory must not be inside a protected Windows directory."
            )


def _validate_python_version(options: object | None, *, label: str) -> None:
    if options is None:
        return
    version = getattr(options, "python_version", None)
    if not isinstance(version, str) or _EXACT_PYTHON_VERSION.fullmatch(version) is None:
        raise ValueError(
            f"{label}.python_version must pin an exact major.minor.patch version."
        )


def _validate_hook_commands(config: AppBuilderConfig) -> None:
    hook_groups = (
        (
            "build_hooks",
            (
                ("pre_process", config.build_hooks.pre_process),
                ("pre_python_bundled", config.build_hooks.pre_python_bundled),
                ("post_python_bundled", config.build_hooks.post_python_bundled),
                ("pre_python_venv", config.build_hooks.pre_python_venv),
                ("post_python_venv", config.build_hooks.post_python_venv),
                ("pre_dist", config.build_hooks.pre_dist),
                ("post_dist", config.build_hooks.post_dist),
                ("pre_github_release", config.build_hooks.pre_github_release),
                ("post_github_release", config.build_hooks.post_github_release),
            ),
        ),
        (
            "installer.bootstrap_hooks",
            (("pre_extract", config.installer.bootstrap_hooks.pre_extract),),
        ),
        (
            "installer.install_hooks",
            (
                ("pre_install", config.installer.install_hooks.pre_install),
                ("post_install", config.installer.install_hooks.post_install),
                ("pre_uninstall", config.installer.install_hooks.pre_uninstall),
                ("post_uninstall", config.installer.install_hooks.post_uninstall),
            ),
        ),
    )
    for group_name, command_fields in hook_groups:
        for field_name, commands in command_fields:
            for index, command in enumerate(commands):
                if not command or not command[0].strip():
                    raise ValueError(
                        f"{group_name}.{field_name}[{index}] must contain a non-empty argv[0]."
                    )
