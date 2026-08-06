from __future__ import annotations

import os
import tomllib
from pathlib import Path
from typing import Any


def legacy_repo_for_executable(
    executable: Path, *, platform: str | None = None
) -> Path | None:
    if (platform or os.name) != "nt":
        return None

    executable = executable.resolve()
    scripts_dir = executable.parent
    venv_dir = scripts_dir.parent
    version_dir = venv_dir.parent
    if (
        executable.name.casefold() != "python.exe"
        or scripts_dir.name.casefold() != "scripts"
        or venv_dir.name.casefold() != "venv"
        or version_dir.parent.name.casefold() != "versions"
    ):
        return None

    command_path = version_dir / "app-builder.cmd"
    run_log = version_dir / "run.log"
    repo = version_dir / "repo"
    if not command_path.is_file() or not run_log.is_file() or not repo.is_dir():
        return None
    if not _is_legacy_command(command_path):
        return None
    if not _is_app_builder_1x_repo(repo):
        return None
    if version_dir not in repo.resolve().parents:
        return None
    return repo.resolve()


def _is_legacy_command(command_path: Path) -> bool:
    try:
        command = command_path.read_text(encoding="utf-8-sig").casefold()
    except OSError:
        return False
    normalized = command.replace("/", "\\")
    return (
        "%~dp0\\venv\\scripts\\python.exe" in normalized
        and "%~dp0repo\\app_builder\\main.py" in normalized
    )


def _is_app_builder_1x_repo(repo: Path) -> bool:
    pyproject_path = repo / "pyproject.toml"
    required = (
        repo / "app_builder" / "__init__.py",
        repo / "app_builder" / "__main__.py",
        repo / "app_builder" / "main.py",
        repo / "app_builder_meta" / "__init__.py",
    )
    if not pyproject_path.is_file() or not all(path.is_file() for path in required):
        return False
    try:
        with pyproject_path.open("rb") as pyproject_file:
            payload: Any = tomllib.load(pyproject_file)
    except (OSError, tomllib.TOMLDecodeError):
        return False
    project = payload.get("project")
    if not isinstance(project, dict):
        return False
    name = project.get("name")
    version = project.get("version")
    return (
        isinstance(name, str)
        and _identity_key(name) == "appbuilder"
        and isinstance(version, str)
        and version.startswith("1.")
    )


def _identity_key(value: str) -> str:
    return "".join(character for character in value.casefold() if character.isalnum())
