from __future__ import annotations

import os
import subprocess
from pathlib import Path


def find_project_root(start: Path) -> Path:
    current = start.resolve()
    while True:
        if (current / ".git").exists():
            return current
        if current.parent == current:
            raise FileNotFoundError("Run app-builder inside a git repository.")
        current = current.parent


def detect_version(project_root: Path) -> str:
    completed = subprocess.run(
        ["git", "describe", "--tags", "--always", "--dirty"],
        cwd=project_root,
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode == 0:
        version = completed.stdout.strip()
        if version:
            return version
    return "0.0.0-dev"


def expand_windows_envvars(value: str) -> str:
    resolved = value
    for env_name in ("LOCALAPPDATA", "APPDATA", "USERPROFILE", "TEMP"):
        env_value = os.environ.get(env_name)
        if env_value:
            resolved = resolved.replace(f"%{env_name.lower()}%", env_value)
            resolved = resolved.replace(f"%{env_name}%", env_value)
    return os.path.expandvars(resolved)
