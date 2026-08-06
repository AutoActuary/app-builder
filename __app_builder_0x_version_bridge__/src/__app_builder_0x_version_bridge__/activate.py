from __future__ import annotations

import os
import sys
from pathlib import Path

from .context import legacy_repo_for_executable


def activate() -> None:
    repo = legacy_repo_for_executable(Path(sys.executable))
    if repo is None:
        return
    repo_key = _path_key(repo)
    sys.path[:] = [entry for entry in sys.path if _entry_key(entry) != repo_key]
    sys.path.insert(0, str(repo))


def _entry_key(entry: object) -> str | None:
    if not isinstance(entry, (str, bytes, os.PathLike)):
        return None
    try:
        return _path_key(Path(entry))
    except (OSError, TypeError, ValueError):
        return None


def _path_key(path: Path) -> str:
    return os.path.normcase(str(path.resolve()))


activate()
