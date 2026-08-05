from __future__ import annotations

import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator


class BuildReporter:
    def __init__(
        self,
        log_path: Path,
        *,
        total_stages: int,
        verbose: bool = False,
    ) -> None:
        self.log_path = log_path
        self.total_stages = total_stages
        self.verbose = verbose
        self._stage_number = 0
        log_path.parent.mkdir(parents=True, exist_ok=True)
        log_path.write_text(
            f"app-builder build log\nstarted_utc={_utc_now()}\n",
            encoding="utf-8",
        )
        print(f"Build log: {log_path}", flush=True)

    @contextmanager
    def stage(self, name: str) -> Iterator[None]:
        self._stage_number += 1
        prefix = f"[{self._stage_number}/{self.total_stages}] {name}"
        started = time.monotonic()
        self._write(f"START {prefix}", visible=True)
        try:
            yield
        except BaseException as error:
            elapsed = time.monotonic() - started
            self._write(
                f"FAIL  {prefix} ({elapsed:.1f}s): {type(error).__name__}: {error}",
                visible=True,
            )
            raise
        elapsed = time.monotonic() - started
        self._write(f"DONE  {prefix} ({elapsed:.1f}s)", visible=True)

    def detail(self, message: str) -> None:
        self._write(f"      {message}", visible=self.verbose)

    def _write(self, message: str, *, visible: bool) -> None:
        with self.log_path.open("a", encoding="utf-8") as log_file:
            log_file.write(f"{_utc_now()} {message}\n")
        if visible:
            print(message, flush=True)


def build_log_path(dist_dir: Path, *, artifact_prefix: str) -> Path:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    return dist_dir / "build-logs" / f"{artifact_prefix}-{timestamp}.log"


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")
