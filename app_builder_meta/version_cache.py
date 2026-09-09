from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from .cache_lock import exclusive_cache_lock as _exclusive_cache_lock
from .environment import get_environment

APP_BUILDER_REPOSITORY_URL = "https://github.com/AutoActuary/app-builder.git"


@dataclass(frozen=True, slots=True)
class ManagedVersion:
    ref: str
    resolved_commit: str
    root: Path
    repo_path: Path
    venv_python: Path


def default_install_root() -> Path:
    return get_environment().install_root


def default_cache_root() -> Path:
    return get_environment().cache_root


def run_managed_version(ref: str, argv: list[str], *, cwd: Path) -> int:
    managed = ensure_managed_version(ref)
    env = get_environment().subprocess_environment()
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
    cache_root: Path | None = None,
    repository_url: str = APP_BUILDER_REPOSITORY_URL,
    python_executable: Path | None = None,
) -> ManagedVersion:
    from app_builder.poetry_dependencies import (
        MAIN_GROUP,
        install_locked_poetry_dependencies,
        load_poetry_lock,
    )

    root = (cache_root or default_cache_root()).resolve()
    versions_root = root / "versions"
    versions_root.mkdir(parents=True, exist_ok=True)
    source_lock = (
        versions_root
        / ".locks"
        / ("source-" + hashlib.sha256(repository_url.encode("utf-8")).hexdigest()[:16])
    )
    with _exclusive_cache_lock(source_lock):
        source_repo = _ensure_source_repo(versions_root, repository_url)
        resolved_commit, ref_kind = _resolve_source_ref(
            source_repo, ref, versions_root=versions_root
        )
        dependency_lock_sha256 = _source_file_sha256(
            source_repo,
            resolved_commit,
            "poetry.lock",
            versions_root=versions_root,
        )
    managed_root = versions_root / _cache_key(ref, repository_url)
    cache_lock = versions_root / ".locks" / (_cache_key(ref, repository_url) + ".lock")
    with _exclusive_cache_lock(cache_lock):
        manifest_path = managed_root / "version-manifest.json"
        existing_payload = _read_manifest_payload(manifest_path)
        existing = _managed_version_from_manifest(
            ref,
            repository_url,
            resolved_commit,
            dependency_lock_sha256,
            existing_payload,
            manifest_path,
        )
        if existing is not None:
            return existing
        if (
            existing_payload is not None
            and existing_payload.get("ref_kind") == "tag"
            and existing_payload.get("resolved_commit") != resolved_commit
        ):
            raise RuntimeError(
                f"Managed app-builder tag {ref!r} moved from "
                f"{existing_payload.get('resolved_commit')} to {resolved_commit}; refusing to replace an immutable tag cache."
            )

        staging_root = versions_root / (
            f".{managed_root.name}.building-{os.getpid()}-{uuid.uuid4().hex}"
        )
        try:
            staging_repo = staging_root / "repo"
            staging_venv = staging_root / "venv"
            staging_root.mkdir(parents=True, exist_ok=False)

            with _exclusive_cache_lock(source_lock):
                _run_cache_git(
                    ["clone", str(source_repo), str(staging_repo)],
                    cwd=source_repo,
                    versions_root=versions_root,
                )
                _run_cache_git(
                    ["fetch", "--tags", "--prune"],
                    cwd=staging_repo,
                    versions_root=versions_root,
                    also_trust=(source_repo,),
                )
            _run_cache_git(
                ["checkout", "--detach", resolved_commit],
                cwd=staging_repo,
                versions_root=versions_root,
            )

            base_python = python_executable or Path(sys.executable)
            _run([str(base_python), "-m", "venv", str(staging_venv)])
            staging_python = _venv_python(staging_venv)
            poetry_lock = load_poetry_lock(staging_repo / "poetry.lock")
            install_locked_poetry_dependencies(
                project_root=staging_repo,
                python_executable=staging_python,
                poetry_lock=poetry_lock,
                groups={MAIN_GROUP},
            )

            final_repo = managed_root / "repo"
            final_venv = managed_root / "venv"
            final_python = _venv_python(final_venv)
            manifest = {
                "requested_ref": ref,
                "ref_kind": ref_kind,
                "resolved_commit": resolved_commit,
                "source_url": repository_url,
                "source_repo": str(source_repo),
                "dependency_lock_sha256": dependency_lock_sha256,
                "dependency_content_hash": poetry_lock.content_hash or "",
                "repo_path": str(final_repo),
                "venv_python": str(final_python),
                "created_at": datetime.now(timezone.utc).isoformat(),
                "last_checked_at": datetime.now(timezone.utc).isoformat(),
                "dependency_contract": "poetry.lock main group with artifact hashes",
            }
            (staging_root / "version-manifest.json").write_text(
                json.dumps(manifest, indent=2), encoding="utf-8"
            )
            _remove_cache_dir(versions_root, managed_root)
            os.replace(staging_root, managed_root)
        finally:
            _remove_cache_dir(versions_root, staging_root)

        return ManagedVersion(
            ref, resolved_commit, managed_root, final_repo, final_python
        )


def _ensure_source_repo(versions_root: Path, repository_url: str) -> Path:
    source_root = versions_root / "_source"
    repository_key = hashlib.sha256(repository_url.encode("utf-8")).hexdigest()[:16]
    source_repo = source_root / f"app-builder-{repository_key}.git"
    if source_repo.exists():
        _run_cache_git(
            ["fetch", "--force", "--tags", "--prune"],
            cwd=source_repo,
            versions_root=versions_root,
        )
        return source_repo
    source_root.mkdir(parents=True, exist_ok=True)
    staging_repo = source_root / f".{source_repo.name}.building-{uuid.uuid4().hex}"
    try:
        _run(["git", "clone", repository_url, str(staging_repo)])
        os.replace(staging_repo, source_repo)
    finally:
        _remove_cache_dir(versions_root, staging_repo)
    return source_repo


def _read_manifest_payload(manifest_path: Path) -> dict[str, object] | None:
    if not manifest_path.is_file():
        return None
    try:
        raw = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return raw if isinstance(raw, dict) else None


def _managed_version_from_manifest(
    ref: str,
    repository_url: str,
    resolved_commit: str,
    dependency_lock_sha256: str,
    raw: dict[str, object] | None,
    manifest_path: Path,
) -> ManagedVersion | None:
    if raw is None:
        return None
    if (
        raw.get("requested_ref") != ref
        or raw.get("source_url") != repository_url
        or raw.get("resolved_commit") != resolved_commit
        or raw.get("dependency_lock_sha256") != dependency_lock_sha256
    ):
        return None
    repo_path = Path(str(raw.get("repo_path", "")))
    venv_python = Path(str(raw.get("venv_python", "")))
    if not repo_path.is_dir() or not venv_python.is_file():
        return None
    return ManagedVersion(
        ref=ref,
        resolved_commit=resolved_commit,
        root=manifest_path.parent,
        repo_path=repo_path,
        venv_python=venv_python,
    )


def _source_file_sha256(
    source_repo: Path,
    commit: str,
    path: str,
    *,
    versions_root: Path,
) -> str:
    result = subprocess.run(
        _cache_git_command(
            ["show", f"{commit}:{path}"],
            versions_root=versions_root,
            repositories=(source_repo,),
        ),
        cwd=source_repo,
        check=False,
        capture_output=True,
    )
    if result.returncode != 0:
        detail = result.stderr.decode("utf-8", errors="replace").strip()
        raise RuntimeError(
            f"Managed app-builder ref {commit!r} has no committed {path}. {detail}"
        )
    return hashlib.sha256(result.stdout).hexdigest()


def _cache_key(ref: str, repository_url: str = APP_BUILDER_REPOSITORY_URL) -> str:
    key = re.sub(r"[^A-Za-z0-9_.-]+", "-", ref.strip()).strip(".-")
    label = key or "unnamed-ref"
    digest = hashlib.sha256((repository_url + "\0" + ref).encode("utf-8")).hexdigest()[
        :12
    ]
    return f"{label}-{digest}"


def managed_version_manifests(
    *, cache_root: Path | None = None
) -> tuple[dict[str, object], ...]:
    versions_root = (cache_root or default_cache_root()).resolve() / "versions"
    if not versions_root.is_dir():
        return ()
    manifests: list[dict[str, object]] = []
    for manifest_path in sorted(versions_root.glob("*/version-manifest.json")):
        payload = _read_manifest_payload(manifest_path)
        if payload is None:
            continue
        payload = dict(payload)
        payload["cache_path"] = str(manifest_path.parent)
        manifests.append(payload)
    return tuple(manifests)


def remove_managed_version(
    ref: str,
    *,
    cache_root: Path | None = None,
    repository_url: str = APP_BUILDER_REPOSITORY_URL,
) -> bool:
    versions_root = (cache_root or default_cache_root()).resolve() / "versions"
    managed_root = versions_root / _cache_key(ref, repository_url)
    if not versions_root.exists():
        return False
    cache_lock = versions_root / ".locks" / (_cache_key(ref, repository_url) + ".lock")
    with _exclusive_cache_lock(cache_lock):
        if not managed_root.exists():
            return False
        _remove_cache_dir(versions_root, managed_root)
        return True


def _resolve_source_ref(
    source_repo: Path, ref: str, *, versions_root: Path
) -> tuple[str, str]:
    candidates = (
        (f"refs/tags/{ref}^{{commit}}", "tag"),
        (f"refs/remotes/origin/{ref}^{{commit}}", "branch"),
        (f"{ref}^{{commit}}", "commit"),
    )
    last_git_error = ""
    for candidate, kind in candidates:
        result = _run_cache_git(
            ["rev-parse", "--verify", candidate],
            cwd=source_repo,
            versions_root=versions_root,
            capture=True,
            check=False,
        )
        if result.returncode == 0:
            return result.stdout.strip(), kind
        last_git_error = result.stderr.strip() or last_git_error
    message = (
        f"Could not resolve app-builder ref {ref!r} from the managed source repository."
    )
    if last_git_error:
        message += f"\nGit error: {last_git_error}"
    raise RuntimeError(message)


def _remove_cache_dir(versions_root: Path, cache_root: Path) -> None:
    if not cache_root.exists():
        return
    versions_resolved = versions_root.resolve()
    cache_resolved = cache_root.resolve()
    if versions_resolved not in cache_resolved.parents:
        raise RuntimeError(
            f"Refusing to remove cache outside versions root: {cache_root}"
        )
    shutil.rmtree(cache_root, onerror=_clear_readonly_and_retry)


def _clear_readonly_and_retry(function: object, path: str, _error: object) -> None:
    os.chmod(path, stat.S_IWRITE)
    callable_function = function
    if not callable(callable_function):
        raise TypeError(f"Cache cleanup callback is not callable: {function!r}")
    callable_function(path)


def _venv_python(venv_root: Path) -> Path:
    if os.name == "nt":
        return venv_root / "Scripts" / "python.exe"
    return venv_root / "bin" / "python"


def _prepend_path(value: str, existing: str) -> str:
    if not existing:
        return value
    return value + os.pathsep + existing


def _run_cache_git(
    args: list[str],
    *,
    cwd: Path,
    versions_root: Path,
    also_trust: tuple[Path, ...] = (),
    capture: bool = False,
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    command = _cache_git_command(
        args,
        versions_root=versions_root,
        repositories=(cwd, *also_trust),
    )
    return _run(command, cwd=cwd, capture=capture, check=check)


def _cache_git_command(
    args: list[str], *, versions_root: Path, repositories: tuple[Path, ...]
) -> list[str]:
    versions_resolved = versions_root.resolve()
    command = ["git"]
    for repository in repositories:
        repository_resolved = repository.resolve()
        safe_directories = [repository_resolved]
        if (repository_resolved / ".git").is_dir():
            safe_directories.append((repository_resolved / ".git").resolve())
        for safe_directory in safe_directories:
            if versions_resolved not in safe_directory.parents:
                raise RuntimeError(
                    f"Refusing to trust Git repository outside versions root: {repository}"
                )
            command.extend(["-c", f"safe.directory={safe_directory}"])
    return command + args


def _run(
    args: list[str],
    *,
    cwd: Path | None = None,
    capture: bool = False,
    check: bool = True,
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        args,
        cwd=cwd,
        env=env,
        check=check,
        capture_output=capture,
        text=True,
    )
