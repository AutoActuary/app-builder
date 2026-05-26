from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

APP_BUILDER_REPOSITORY_URL = "https://github.com/AutoActuary/app-builder.git"


@dataclass(frozen=True, slots=True)
class ManagedVersion:
    ref: str
    resolved_commit: str
    root: Path
    repo_path: Path
    venv_python: Path


def default_install_root() -> Path:
    override = os.environ.get("APP_BUILDER_INSTALL_ROOT")
    if override:
        return Path(override).resolve()
    return Path(__file__).resolve().parents[1]


def run_managed_version(ref: str, argv: list[str], *, cwd: Path) -> int:
    managed = ensure_managed_version(ref)
    env = os.environ.copy()
    env["PYTHONNOUSERSITE"] = "1"
    env["PYTHONPATH"] = _prepend_path(str(managed.repo_path), env.get("PYTHONPATH", ""))
    completed = subprocess.run(
        [str(managed.venv_python), "-P", "-m", "app_builder", *argv],
        cwd=cwd,
        env=env,
        check=False,
    )
    return completed.returncode


def ensure_managed_version(
    ref: str,
    *,
    install_root: Path | None = None,
    repository_url: str = APP_BUILDER_REPOSITORY_URL,
    python_executable: Path | None = None,
) -> ManagedVersion:
    root = (install_root or default_install_root()).resolve()
    versions_root = root / "versions"
    versions_root.mkdir(parents=True, exist_ok=True)
    source_repo = _ensure_source_repo(versions_root, repository_url)
    cache_root = versions_root / _cache_key(ref)
    manifest_path = cache_root / "version-manifest.json"
    existing = _read_manifest(ref, manifest_path)
    if existing is not None:
        return existing

    _remove_cache_dir(versions_root, cache_root)
    repo_path = cache_root / "repo"
    venv_root = cache_root / "venv"
    cache_root.mkdir(parents=True, exist_ok=True)

    _run(["git", "clone", str(source_repo), str(repo_path)])
    _run(["git", "fetch", "--tags", "--prune"], cwd=repo_path)
    _run(["git", "checkout", ref], cwd=repo_path)
    resolved_commit = _run(
        ["git", "rev-parse", "HEAD"], cwd=repo_path, capture=True
    ).stdout.strip()

    base_python = python_executable or Path(sys.executable)
    _run([str(base_python), "-m", "venv", str(venv_root)])
    venv_python = _venv_python(venv_root)
    _run([str(venv_python), "-m", "pip", "install", "--upgrade", "pip"])
    _run([str(venv_python), "-m", "pip", "install", str(repo_path)])

    manifest = {
        "requested_ref": ref,
        "resolved_commit": resolved_commit,
        "source_url": repository_url,
        "source_repo": str(source_repo),
        "repo_path": str(repo_path),
        "venv_python": str(venv_python),
        "created_at": datetime.now(timezone.utc).isoformat(),
        "dependency_install_command": [
            str(venv_python),
            "-m",
            "pip",
            "install",
            str(repo_path),
        ],
    }
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return ManagedVersion(ref, resolved_commit, cache_root, repo_path, venv_python)


def _ensure_source_repo(versions_root: Path, repository_url: str) -> Path:
    source_root = versions_root / "_source"
    source_repo = source_root / "app-builder.git"
    if source_repo.exists():
        _run(["git", "fetch", "--tags", "--prune"], cwd=source_repo)
        return source_repo
    source_root.mkdir(parents=True, exist_ok=True)
    _run(["git", "clone", repository_url, str(source_repo)])
    return source_repo


def _read_manifest(ref: str, manifest_path: Path) -> ManagedVersion | None:
    if not manifest_path.is_file():
        return None
    try:
        raw = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if raw.get("requested_ref") != ref:
        return None
    repo_path = Path(str(raw.get("repo_path", "")))
    venv_python = Path(str(raw.get("venv_python", "")))
    resolved_commit = raw.get("resolved_commit")
    if not isinstance(resolved_commit, str):
        return None
    if not repo_path.is_dir() or not venv_python.is_file():
        return None
    return ManagedVersion(
        ref=ref,
        resolved_commit=resolved_commit,
        root=manifest_path.parent,
        repo_path=repo_path,
        venv_python=venv_python,
    )


def _cache_key(ref: str) -> str:
    key = re.sub(r"[^A-Za-z0-9_.-]+", "-", ref.strip()).strip(".-")
    return key or "unnamed-ref"


def _remove_cache_dir(versions_root: Path, cache_root: Path) -> None:
    if not cache_root.exists():
        return
    versions_resolved = versions_root.resolve()
    cache_resolved = cache_root.resolve()
    if versions_resolved not in cache_resolved.parents:
        raise RuntimeError(
            f"Refusing to remove cache outside versions root: {cache_root}"
        )
    shutil.rmtree(cache_root)


def _venv_python(venv_root: Path) -> Path:
    if os.name == "nt":
        return venv_root / "Scripts" / "python.exe"
    return venv_root / "bin" / "python"


def _prepend_path(value: str, existing: str) -> str:
    if not existing:
        return value
    return value + os.pathsep + existing


def _run(
    args: list[str],
    *,
    cwd: Path | None = None,
    capture: bool = False,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        args,
        cwd=cwd,
        check=True,
        capture_output=capture,
        text=True,
    )
