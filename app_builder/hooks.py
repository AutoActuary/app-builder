from __future__ import annotations

import os
import subprocess
from collections.abc import Sequence
from pathlib import Path

from .schema import HookCommand

PythonCandidate = str | Path


def _normalize_python_candidates(
    python_candidates: Sequence[PythonCandidate | None] | None,
    python_for_hooks: Path | None,
) -> tuple[Path, ...]:
    candidates: list[Path] = []
    if python_candidates is None:
        if python_for_hooks is not None:
            candidates.append(python_for_hooks)
    else:
        candidates.extend(
            Path(candidate) for candidate in python_candidates if candidate
        )

    unique_candidates: list[Path] = []
    seen: set[str] = set()
    for candidate in candidates:
        key = os.path.normcase(os.path.abspath(os.fspath(candidate)))
        if key in seen:
            continue
        seen.add(key)
        unique_candidates.append(candidate)
    return tuple(unique_candidates)


def _select_python(python_candidates: Sequence[Path]) -> str:
    for candidate in python_candidates:
        if candidate.exists():
            return str(candidate)
    candidates = ", ".join(str(candidate) for candidate in python_candidates)
    detail = f" Checked: {candidates}." if candidates else ""
    raise RuntimeError(
        "Cannot run Python hook from a .py entrypoint because app-builder could "
        "not find the Python runtime configured for this project. Enable or "
        "materialize python_bundled/python_venv, or use an explicit command such "
        "as ['python', 'script.py'] if the target machine is expected to provide "
        f"Python on PATH.{detail}"
    )


def run_hook_commands(
    project_root: Path,
    commands: list[HookCommand],
    *,
    environment: dict[str, str],
    python_candidates: Sequence[PythonCandidate | None] | None = None,
    python_for_hooks: Path | None = None,
) -> None:
    env = os.environ.copy()
    env.update(environment)
    normalized_python_candidates = _normalize_python_candidates(
        python_candidates, python_for_hooks
    )
    for command in commands:
        _run_single_hook(
            project_root,
            command,
            env=env,
            python_candidates=normalized_python_candidates,
        )


def _run_single_hook(
    project_root: Path,
    command: HookCommand,
    *,
    env: dict[str, str],
    python_candidates: Sequence[Path],
) -> None:
    if not command:
        return
    if _run_script_hook(
        project_root,
        command,
        env=env,
        python_candidates=python_candidates,
    ):
        return
    subprocess.run(
        command,
        cwd=project_root,
        env=env,
        check=True,
    )


def _run_script_hook(
    project_root: Path,
    argv: list[str],
    *,
    env: dict[str, str],
    python_candidates: Sequence[Path],
) -> bool:
    if not argv:
        return False
    candidate = _resolve_hook_path(project_root, argv[0])
    suffix = candidate.suffix.lower()
    if candidate.exists() and suffix == ".py":
        subprocess.run(
            [_select_python(python_candidates), str(candidate), *argv[1:]],
            cwd=project_root,
            env=env,
            check=True,
        )
        return True
    if candidate.exists() and suffix == ".ps1":
        subprocess.run(
            [
                "powershell.exe",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(candidate),
                *argv[1:],
            ],
            cwd=project_root,
            env=env,
            check=True,
        )
        return True
    return False


def _resolve_hook_path(project_root: Path, value: str) -> Path:
    path = Path(value)
    if path.is_absolute():
        return path.resolve()
    return (project_root / path).resolve()
