from __future__ import annotations

import os
import shlex
import subprocess
import sys
from pathlib import Path


def _select_python(python_for_hooks: Path | None) -> str:
    return str(python_for_hooks or Path(sys.executable))


def run_hook_commands(
    project_root: Path,
    commands: list[str],
    *,
    environment: dict[str, str],
    python_for_hooks: Path | None,
) -> None:
    env = os.environ.copy()
    env.update(environment)
    for command in commands:
        _run_single_hook(
            project_root, command, env=env, python_for_hooks=python_for_hooks
        )


def _run_single_hook(
    project_root: Path,
    command: str,
    *,
    env: dict[str, str],
    python_for_hooks: Path | None,
) -> None:
    parts = shlex.split(command, posix=False)
    if not parts:
        return
    candidate = (project_root / parts[0]).resolve()
    suffix = candidate.suffix.lower()
    if candidate.exists() and suffix == ".py":
        subprocess.run(
            [_select_python(python_for_hooks), str(candidate), *parts[1:]],
            cwd=project_root,
            env=env,
            check=True,
        )
        return
    if candidate.exists() and suffix == ".ps1":
        subprocess.run(
            [
                "powershell.exe",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(candidate),
                *parts[1:],
            ],
            cwd=project_root,
            env=env,
            check=True,
        )
        return
    subprocess.run(
        ["cmd.exe", "/c", command],
        cwd=project_root,
        env=env,
        check=True,
    )
