from __future__ import annotations

import os
import sys
import time
from contextlib import contextmanager
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


@contextmanager
def exclusive_cache_lock(
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
