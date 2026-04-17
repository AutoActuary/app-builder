from __future__ import annotations

import os
import subprocess
import sys
import venv
from dataclasses import dataclass
from pathlib import Path

from .config import load_project_config


def _python_executable(venv_root: Path) -> Path:
    scripts_dir = "Scripts" if os.name == "nt" else "bin"
    exe_name = "python.exe" if os.name == "nt" else "python"
    return venv_root / scripts_dir / exe_name


def _install_requirements(python_executable: Path, requirements: list[str], requirement_files: list[Path]) -> None:
    if not requirements and not requirement_files:
        return
    command = [str(python_executable), "-m", "pip", "install", "--upgrade"]
    command.extend(requirements)
    for requirement_file in requirement_files:
        command.extend(["-r", str(requirement_file)])
    subprocess.run(command, check=True)


def _expand_requirement_files(project_root: Path, patterns: list[str]) -> list[Path]:
    files: list[Path] = []
    for pattern in patterns:
        matched = list(project_root.glob(os.path.expandvars(pattern)))
        if not matched:
            raise FileNotFoundError(f"No requirements file matched pattern '{pattern}'.")
        files.extend(path for path in matched if path.is_file())
    return files


def _create_venv(target: Path, *, python_executable: Path | None = None) -> Path:
    if target.exists():
        return _python_executable(target)
    if python_executable is None:
        builder = venv.EnvBuilder(with_pip=True, clear=False, symlinks=False, upgrade=False, with_prompt="app-builder")
        builder.create(str(target))
        return _python_executable(target)

    subprocess.run([str(python_executable), "-m", "venv", str(target), "--copies"], check=True)
    return _python_executable(target)


@dataclass(slots=True)
class PythonEnvironmentResult:
    python_bundled: Path | None
    python_venv: Path | None


def ensure_python_environments(project_root: Path) -> PythonEnvironmentResult:
    _, config = load_project_config(project_root)
    bundled_python: Path | None = None
    venv_python: Path | None = None

    if config.python_bundled is not None:
        bundled_root = project_root / config.python_bundled.path
        bundled_python = _create_venv(bundled_root)
        subprocess.run(
            [str(bundled_python), "-m", "pip", "install", f"pip=={config.python_bundled.pip_version}"],
            check=True,
        )
        _install_requirements(
            bundled_python,
            config.python_bundled.requirements,
            _expand_requirement_files(project_root, config.python_bundled.requirements_files),
        )

    if config.python_venv is not None:
        base_python = bundled_python or Path(sys.executable)
        venv_root = project_root / config.python_venv.path
        venv_python = _create_venv(venv_root, python_executable=base_python)
        _install_requirements(
            venv_python,
            config.python_venv.requirements,
            _expand_requirement_files(project_root, config.python_venv.requirements_files),
        )

    return PythonEnvironmentResult(python_bundled=bundled_python, python_venv=venv_python)
