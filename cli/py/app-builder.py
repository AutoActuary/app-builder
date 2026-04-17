from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import venv
from pathlib import Path
from typing import Sequence

import yaml


CONFIG_FILENAMES = ("app_builder.yaml", "app-builder.yaml", "application.yaml")
VERSIONS_DIR = Path(
    os.environ.get("LOCALAPPDATA", tempfile.gettempdir()),
    "autoactuary",
    "app-builder",
    "versions",
)


class ConfigVersionError(RuntimeError):
    pass


def _find_project_root(start: Path) -> Path:
    current = start.resolve()
    while True:
        if (current / ".git").exists():
            return current
        if current.parent == current:
            raise FileNotFoundError("Run app-builder inside a git repository.")
        current = current.parent


def _find_config_path(project_root: Path) -> Path | None:
    for filename in CONFIG_FILENAMES:
        path = project_root / filename
        if path.exists():
            return path
    return None


def _read_desired_version(project_root: Path) -> str | None:
    config_path = _find_config_path(project_root)
    if config_path is None:
        return None
    if config_path.name == "application.yaml":
        raise ConfigVersionError("Legacy application.yaml is not supported by the 1.x dispatcher.")

    raw = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    if not isinstance(raw, dict):
        raise ConfigVersionError(f"{config_path.name} must contain a YAML mapping.")
    version = raw.get("app_builder_version")
    if version is None:
        return None
    if not isinstance(version, str):
        raise ConfigVersionError("app_builder_version must be a string.")
    return version


def _version_python(version_root: Path) -> Path:
    scripts_dir = "Scripts" if os.name == "nt" else "bin"
    exe_name = "python.exe" if os.name == "nt" else "python"
    return version_root / "venv" / scripts_dir / exe_name


def _run(args: Sequence[str | Path], *, cwd: Path) -> None:
    subprocess.run([str(arg) for arg in args], cwd=cwd, check=True)


def ensure_app_version(version: str) -> Path:
    version_root = VERSIONS_DIR / version
    python_executable = _version_python(version_root)
    if python_executable.exists():
        return version_root

    repo_root = version_root / "repo"
    if version_root.exists():
        shutil.rmtree(version_root)
    version_root.mkdir(parents=True, exist_ok=True)

    _run(["git", "clone", "https://github.com/AutoActuary/app-builder.git", str(repo_root)], cwd=version_root)
    _run(["git", "checkout", version], cwd=repo_root)
    venv.EnvBuilder(with_pip=True, clear=True, symlinks=False).create(str(version_root / "venv"))
    _run([_version_python(version_root), "-m", "pip", "install", "-r", repo_root / "requirements.txt"], cwd=repo_root)
    return version_root


def _main_arg_in(options: Sequence[str]) -> bool:
    return len(sys.argv) >= 2 and sys.argv[1].lower() in {option.lower() for option in options}


def run_versioned_main() -> int:
    if _main_arg_in(["--install-version"]):
        if len(sys.argv) < 3:
            print("Usage: app-builder --install-version <version>")
            return 255
        ensure_app_version(sys.argv[2])
        return 0

    if _main_arg_in(["--use-version"]):
        if len(sys.argv) < 3:
            print("Usage: app-builder --use-version <version>")
            return 255
        desired_version = sys.argv[2]
    elif _main_arg_in(["-h", "--help", "help", "-i", "--init", "init"]):
        desired_version = "current"
    else:
        try:
            desired_version = _read_desired_version(_find_project_root(Path.cwd())) or "current"
        except (ConfigVersionError, FileNotFoundError) as exc:
            print(exc)
            return 1

    if desired_version == "current":
        command = [Path(sys.executable), "-m", "app_builder", *sys.argv[1:]]
        completed = subprocess.run([str(item) for item in command], check=False)
        return int(completed.returncode)

    version_root = ensure_app_version(desired_version)
    command = [_version_python(version_root), "-m", "app_builder", *sys.argv[1:]]
    completed = subprocess.run([str(item) for item in command], cwd=version_root / "repo", check=False)
    return int(completed.returncode)


if __name__ == "__main__":
    raise SystemExit(run_versioned_main())
