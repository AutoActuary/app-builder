from __future__ import annotations

import subprocess
from pathlib import Path


def bridge_executable(install_root: Path) -> Path:
    return install_root / "__app_builder_0.x__" / "app-builder.exe"


def run_legacy_bridge(
    argv: list[str],
    *,
    cwd: Path,
    install_root: Path,
) -> int:
    executable = bridge_executable(install_root)
    if not executable.is_file():
        raise RuntimeError(
            "The app-builder 0.x compatibility bridge is not installed.\n"
            f"Expected: {executable}\n"
            "Reinstall app-builder with the legacy bridge artifact included."
        )
    completed = subprocess.run([str(executable), *argv], cwd=cwd, check=False)
    return completed.returncode
