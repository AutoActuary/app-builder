from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import time
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import BinaryIO, Iterator

if sys.platform == "win32":
    import msvcrt

    def _acquire_platform_lock(lock_file: BinaryIO) -> None:
        msvcrt.locking(lock_file.fileno(), msvcrt.LK_NBLCK, 1)

    def _release_platform_lock(lock_file: BinaryIO) -> None:
        msvcrt.locking(lock_file.fileno(), msvcrt.LK_UNLCK, 1)

else:
    import fcntl

    def _acquire_platform_lock(lock_file: BinaryIO) -> None:
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)

    def _release_platform_lock(lock_file: BinaryIO) -> None:
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)


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


def default_cache_root() -> Path:
    override = os.environ.get("APP_BUILDER_CACHE_ROOT")
    if override:
        return Path(override).expanduser().resolve()
    if os.name == "nt":
        local_app_data = os.environ.get("LOCALAPPDATA")
        if local_app_data:
            return (Path(local_app_data) / "app-builder" / "cache").resolve()
    xdg_cache = os.environ.get("XDG_CACHE_HOME")
    base = Path(xdg_cache).expanduser() if xdg_cache else Path.home() / ".cache"
    return (base / "app-builder").resolve()


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
    cache_root: Path | None = None,
    repository_url: str = APP_BUILDER_REPOSITORY_URL,
    python_executable: Path | None = None,
) -> ManagedVersion:
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
        resolved_commit, ref_kind = _resolve_source_ref(source_repo, ref)
    managed_root = versions_root / _cache_key(ref, repository_url)
    cache_lock = versions_root / ".locks" / (_cache_key(ref, repository_url) + ".lock")
    with _exclusive_cache_lock(cache_lock):
        manifest_path = managed_root / "version-manifest.json"
        existing_payload = _read_manifest_payload(manifest_path)
        existing = _managed_version_from_manifest(
            ref,
            repository_url,
            resolved_commit,
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
        _remove_cache_dir(versions_root, staging_root)
        try:
            staging_repo = staging_root / "repo"
            staging_venv = staging_root / "venv"
            staging_root.mkdir(parents=True, exist_ok=False)

            _run(["git", "clone", str(source_repo), str(staging_repo)])
            _run(["git", "fetch", "--tags", "--prune"], cwd=staging_repo)
            _run(["git", "checkout", "--detach", resolved_commit], cwd=staging_repo)

            base_python = python_executable or Path(sys.executable)
            _run([str(base_python), "-m", "venv", str(staging_venv)])
            staging_python = _venv_python(staging_venv)
            _run([str(staging_python), "-m", "pip", "install", "--upgrade", "pip"])
            _run([str(staging_python), "-m", "pip", "install", str(staging_repo)])

            final_repo = managed_root / "repo"
            final_venv = managed_root / "venv"
            final_python = _venv_python(final_venv)
            manifest = {
                "requested_ref": ref,
                "ref_kind": ref_kind,
                "resolved_commit": resolved_commit,
                "source_url": repository_url,
                "source_repo": str(source_repo),
                "repo_path": str(final_repo),
                "venv_python": str(final_python),
                "created_at": datetime.now(timezone.utc).isoformat(),
                "last_checked_at": datetime.now(timezone.utc).isoformat(),
                "dependency_install_command": [
                    str(final_python),
                    "-m",
                    "pip",
                    "install",
                    str(final_repo),
                ],
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
        _run(["git", "fetch", "--force", "--tags", "--prune"], cwd=source_repo)
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
    raw: dict[str, object] | None,
    manifest_path: Path,
) -> ManagedVersion | None:
    if raw is None:
        return None
    if (
        raw.get("requested_ref") != ref
        or raw.get("source_url") != repository_url
        or raw.get("resolved_commit") != resolved_commit
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


def _resolve_source_ref(source_repo: Path, ref: str) -> tuple[str, str]:
    candidates = (
        (f"refs/tags/{ref}^{{commit}}", "tag"),
        (f"refs/remotes/origin/{ref}^{{commit}}", "branch"),
        (f"{ref}^{{commit}}", "commit"),
    )
    for candidate, kind in candidates:
        result = _run(
            ["git", "rev-parse", "--verify", candidate],
            cwd=source_repo,
            capture=True,
            check=False,
        )
        if result.returncode == 0:
            return result.stdout.strip(), kind
    raise RuntimeError(
        f"Could not resolve app-builder ref {ref!r} from the managed source repository."
    )


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


@contextmanager
def _exclusive_cache_lock(
    lock_path: Path, *, timeout_seconds: float = 600.0
) -> Iterator[None]:
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("a+b") as lock_file:
        lock_file.seek(0, os.SEEK_END)
        if lock_file.tell() == 0:
            lock_file.write(b"\0")
            lock_file.flush()
        deadline = time.monotonic() + timeout_seconds
        while True:
            lock_file.seek(0)
            try:
                _acquire_platform_lock(lock_file)
                break
            except OSError:
                if time.monotonic() >= deadline:
                    raise TimeoutError(
                        f"Timed out waiting for app-builder cache lock: {lock_path}"
                    )
                time.sleep(0.1)
        try:
            yield
        finally:
            lock_file.seek(0)
            _release_platform_lock(lock_file)


def _prepend_path(value: str, existing: str) -> str:
    if not existing:
        return value
    return value + os.pathsep + existing


def _run(
    args: list[str],
    *,
    cwd: Path | None = None,
    capture: bool = False,
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        args,
        cwd=cwd,
        check=check,
        capture_output=capture,
        text=True,
    )
