"""Disposable snapshots of freshly hydrated Python runtimes."""

from __future__ import annotations

import hashlib
import json
import os
import platform
import shutil
import stat
import subprocess
import sys
import time
import uuid
from collections.abc import Callable
from dataclasses import asdict
from pathlib import Path

from app_builder_meta.cache_lock import exclusive_cache_lock
from app_builder_meta.environment import get_environment

from . import __version__
from .fileset import validate_archive_path
from .poetry_dependencies import PoetryLock
from .schema import PythonBundledOptions, PythonVenvOptions
from .sevenzip import vendored_7zip_executable

STAGES = ("python-bin", "python-venv")
MAX_BYTES = 5 * 1024**3
_CACHE_ERRORS = (OSError, ValueError, RuntimeError, subprocess.SubprocessError)


def cache_root() -> Path:
    return get_environment().cache_root / "python-environments"


def _lock_path() -> Path:
    return get_environment().locks / "python-environments.lock"


def cache_files(stage: str) -> list[Path]:
    if stage not in STAGES:
        raise ValueError(f"Unknown Python cache stage: {stage}")
    return sorted(
        path
        for path in (cache_root() / stage).glob("*.7z")
        if not path.name.startswith(".")
    )


def clear_cache(stage: str) -> tuple[int, int]:
    with exclusive_cache_lock(_lock_path()):
        files = cache_files(stage)
        size = sum(path.stat().st_size for path in files)
        for path in files:
            path.unlink()
        return len(files), size


def _prune() -> None:
    files = [path for stage in STAGES for path in cache_files(stage)]
    entries = sorted((p.stat().st_mtime, p.stat().st_size, p) for p in files)
    total = sum(size for _, size, _ in entries)
    for _, size, path in entries:
        if total <= MAX_BYTES:
            break
        path.unlink()
        total -= size


def runtime_cache(
    stage: str,
    options: PythonBundledOptions | PythonVenvOptions,
    poetry_lock: PoetryLock,
    groups: set[str],
    bundled_options: PythonBundledOptions | None = None,
) -> PythonEnvironmentCache | None:
    environment = get_environment()
    enabled = {
        "python-bin": environment.cache_python_bin,
        "python-venv": environment.cache_python_venv,
    }[stage]
    if not enabled or not poetry_lock.sha256:
        return None
    identity = {
        "stage": stage,
        "app_builder": __version__,
        "platform": sys.platform,
        "architecture": platform.machine(),
        "python": asdict(options),
        "bundled": asdict(bundled_options) if bundled_options else None,
        "lock": poetry_lock.sha256,
        "content_hash": poetry_lock.content_hash,
        "groups": sorted(groups),
    }
    key = hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()
    return PythonEnvironmentCache(stage, key)


def _run_7z(*args: str, cwd: Path) -> str:
    result = subprocess.run(
        [str(vendored_7zip_executable()), *args, "-sccUTF-8", "-bd"],
        cwd=cwd,
        capture_output=True,
        encoding="utf-8",
        errors="replace",
        check=True,
    )
    return result.stdout


def _validate_members(listing: str) -> None:
    paths = []
    for block in listing.strip().split("\n\n"):
        fields = dict(
            line.split(" = ", 1) for line in block.splitlines() if " = " in line
        )
        if "Path" not in fields:
            continue
        paths.append(validate_archive_path(fields["Path"]))
        if (
            fields.get("Symbolic Link")
            or fields.get("Hard Link")
            or fields.get("Reparse")
            or "L" in fields.get("Attributes", "")
            or fields.get("Attributes", "").split(" ")[-1].startswith("l")
        ):
            raise ValueError(f"Unsupported link in Python cache: {fields['Path']}")
    if not paths or not any(p.as_posix() == "pyvenv.cfg" for p in paths):
        raise ValueError("Python cache has no runtime at its archive root")


class PythonEnvironmentCache:
    def __init__(self, stage: str, key: str) -> None:
        self.stage = stage
        self.path = cache_root() / stage / f"{key}.7z"

    def _message(self, message: str, *, warning: bool = False) -> None:
        prefix = "WARNING: " if warning else ""
        print(
            f"{prefix}{self.stage} cache [{self.path.stem[:12]}]: {message}",
            file=sys.stderr,
        )

    def restore(self, destination: Path, prepare: Callable[[], bool]) -> bool:
        """Restore into an absent runtime owned by the caller's replacement helper."""
        started = time.monotonic()
        if destination.exists():
            raise ValueError(
                f"Cache restore requires an absent destination: {destination}"
            )
        try:
            with exclusive_cache_lock(_lock_path()):
                if not self.path.is_file():
                    self._message("miss")
                    return False
                try:
                    listing = _run_7z(
                        "l", "-slt", "-ba", str(self.path), cwd=self.path.parent
                    )
                    _validate_members(listing)
                    _run_7z(
                        "x",
                        "-y",
                        str(self.path),
                        f"-o{destination}",
                        cwd=self.path.parent,
                    )
                    try:
                        valid = prepare()
                    except (RuntimeError, subprocess.SubprocessError) as error:
                        raise ValueError(
                            f"cached runtime check failed: {error}"
                        ) from error
                    if not valid:
                        raise ValueError("restored runtime failed validation")
                except _CACHE_ERRORS as error:
                    # OS errors can mean a good archive was inaccessible or the disk is full.
                    if isinstance(error, ValueError) or (
                        isinstance(error, subprocess.CalledProcessError)
                        and any(
                            word in (error.stdout or "") + (error.stderr or "")
                            for word in (
                                "CRC Failed",
                                "Data Error",
                                "Is not archive",
                                "Can not open the file as archive",
                            )
                        )
                    ):
                        self.path.unlink(missing_ok=True)
                    raise
                self.path.touch()
                self._message(f"hit ({time.monotonic() - started:.1f}s)")
                return True
        except _CACHE_ERRORS as error:
            detail = str(error)
            if isinstance(error, subprocess.CalledProcessError):
                detail += " " + (error.stderr or error.stdout or "").strip()
            self._message(f"{detail}. Rebuilding normally.", warning=True)
        # Failure here must propagate: never hydrate over a partial restore.
        if destination.exists():
            shutil.rmtree(destination)
        return False

    def save(self, runtime: Path) -> None:
        started = time.monotonic()
        temporary = self.path.with_name(f".{self.path.stem}-{uuid.uuid4().hex}.7z")
        try:
            with exclusive_cache_lock(_lock_path()):
                if self.path.exists():
                    return
                # Reject links before 7-Zip can follow one out of the fresh runtime.
                for directory, dirs, files in os.walk(runtime):
                    for name in [*dirs, *files]:
                        path = Path(directory) / name
                        validate_archive_path(path.relative_to(runtime).as_posix())
                        attributes = path.lstat()
                        if (
                            stat.S_ISLNK(attributes.st_mode)
                            or getattr(attributes, "st_file_attributes", 0)
                            & stat.FILE_ATTRIBUTE_REPARSE_POINT
                        ):
                            raise ValueError(f"Cannot cache runtime link: {path}")
                self.path.parent.mkdir(parents=True, exist_ok=True)
                _run_7z("a", "-t7z", "-mx=1", "-y", str(temporary), ".", cwd=runtime)
                if temporary.stat().st_size > MAX_BYTES:
                    self._message("snapshot exceeds the 5 GiB target; not saved")
                    return
                temporary.replace(self.path)
                self.path.touch()
                _prune()
                self._message(f"saved ({time.monotonic() - started:.1f}s)")
        except _CACHE_ERRORS as error:
            self._message(f"could not save snapshot: {error}", warning=True)
        finally:
            try:
                temporary.unlink(missing_ok=True)
            except OSError as error:
                self._message(
                    f"could not remove temporary archive: {error}", warning=True
                )
