from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
from types import TracebackType

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app_builder.exewrap import stamp_exe_wrap_config
from app_builder_meta.version_cache import APP_BUILDER_REPOSITORY_URL

DEFAULT_REF = "v0.20.0"
DEFAULT_COMMIT = "189712c7d27258d6404b38f57ab9b6cb967d0ff9"
LOCK_PATH = PROJECT_ROOT / "scripts" / "legacy-0x-requirements.lock"
BUILD_LOCK_PATH = PROJECT_ROOT / "scripts" / "legacy-0x-build-requirements.lock"


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Build the app-builder 0.x compatibility bridge."
    )
    parser.add_argument("--ref", default=DEFAULT_REF)
    parser.add_argument("--expected-commit")
    parser.add_argument("--repo-url", default=APP_BUILDER_REPOSITORY_URL)
    parser.add_argument("--output", type=Path, default=Path("__app_builder_0x__"))
    parser.add_argument("--python", type=Path, default=Path(sys.executable))
    args = parser.parse_args()

    project_root = Path.cwd().resolve()
    output = (project_root / args.output).resolve()
    cache_root = project_root / "build" / "legacy-0x-bridge"
    source_repo = _ensure_source_repo(cache_root, args.repo_url)
    checkout = cache_root / "checkout"
    _remove_tree_within(cache_root, checkout)
    _run(["git", "clone", str(source_repo), str(checkout)])
    _run(["git", "fetch", "--tags", "--prune"], cwd=checkout)
    commit = _run(
        ["git", "rev-parse", f"{args.ref}^{{commit}}"],
        cwd=checkout,
        capture=True,
    ).stdout.strip()
    expected_commit = args.expected_commit
    if expected_commit is None and args.ref == DEFAULT_REF:
        expected_commit = DEFAULT_COMMIT
    if expected_commit is None and re.fullmatch(r"[0-9a-fA-F]{40}", args.ref):
        expected_commit = args.ref.lower()
    if expected_commit is None:
        raise RuntimeError(
            "A custom legacy 0.x ref requires --expected-commit so the bridge "
            "cannot silently follow a moved tag or branch."
        )
    if commit.lower() != expected_commit.lower():
        raise RuntimeError(
            f"Legacy 0.x ref {args.ref!r} resolved to {commit}, expected "
            f"{expected_commit}."
        )
    _run(["git", "checkout", "--detach", commit], cwd=checkout)

    _remove_tree_within(project_root, output)
    output.mkdir(parents=True, exist_ok=True)
    shutil.copytree(checkout / "app_builder", output / "app_builder")
    shutil.copy2(checkout / "cli" / "py" / "app-builder.py", output / "legacy-cli.py")
    _write_bootstrap(output / "app-builder-legacy.py")
    (output / "app-builder.exe").write_bytes(
        stamp_exe_wrap_config(_render_legacy_bridge_launcher_config())
    )

    site_packages = output / "site-packages"
    site_packages.mkdir()
    with tempfile.TemporaryDirectory(prefix="app-builder-0x-build-") as temp_dir:
        build_site = Path(temp_dir) / "site-packages"
        _install_locked_requirements(args.python, BUILD_LOCK_PATH, build_site)
        build_env = os.environ.copy()
        build_env["PYTHONNOUSERSITE"] = "1"
        build_env["PYTHONPATH"] = str(build_site)
        _install_locked_requirements(
            args.python,
            LOCK_PATH,
            site_packages,
            env=build_env,
            no_build_isolation=True,
        )
    _smoke_import(args.python, output)

    manifest = {
        "ref": args.ref,
        "resolved_commit": commit,
        "dependency_lock": LOCK_PATH.relative_to(PROJECT_ROOT).as_posix(),
        "dependency_lock_sha256": _sha256_file(LOCK_PATH),
        "build_dependency_lock_sha256": _sha256_file(BUILD_LOCK_PATH),
        "source_url": args.repo_url,
        "built_at": datetime.now(timezone.utc).isoformat(),
        "python": str(args.python.resolve()),
        "entrypoint": "app-builder.exe",
        "bootstrap": "app-builder-legacy.py",
        "site_packages": "site-packages",
    }
    (output / "bridge-manifest.json").write_text(
        json.dumps(manifest, indent=2), encoding="utf-8"
    )
    print(f"Built 0.x bridge at {output}")
    return 0


def _ensure_source_repo(cache_root: Path, repo_url: str) -> Path:
    source_root = cache_root / "_source"
    source_repo = source_root / "app-builder.git"
    if source_repo.exists():
        _run(["git", "fetch", "--tags", "--prune"], cwd=source_repo)
        return source_repo
    source_root.mkdir(parents=True, exist_ok=True)
    _run(["git", "clone", repo_url, str(source_repo)])
    return source_repo


def _write_bootstrap(path: Path) -> None:
    path.write_text(
        """
from __future__ import annotations

import runpy
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "site-packages"))
sys.path.insert(0, str(ROOT))
runpy.run_path(str(ROOT / "legacy-cli.py"), run_name="__main__")
""".lstrip(),
        encoding="utf-8",
    )


def _render_legacy_bridge_launcher_config() -> bytes:
    return (
        "{\n"
        '  "env": {\n'
        '    "PYTHONNOUSERSITE": "1",\n'
        '    "PYTHONPATH": "@{exe_dir}\\\\site-packages;@{exe_dir}"\n'
        "  },\n"
        '  "command": [\n'
        '    "@{exe_dir}\\\\..\\\\bin\\\\python\\\\python\\\\python.exe",\n'
        '    "-X",\n'
        '    "utf8",\n'
        '    "@{exe_dir}\\\\app-builder-legacy.py",\n'
        "    @{args}\n"
        "  ]\n"
        "}\n"
    ).encode("utf-8")


def _smoke_import(python: Path, output: Path) -> None:
    env = os.environ.copy()
    env["PYTHONNOUSERSITE"] = "1"
    env["APP_BUILDER_0X_BRIDGE"] = str(output)
    env["PYTHONPATH"] = os.pathsep.join([str(output / "site-packages"), str(output)])
    _run(
        [
            str(python),
            "-c",
            "import app_builder, os, pathlib; "
            "origin = pathlib.Path(app_builder.__file__).resolve(); "
            "root = pathlib.Path(os.environ['APP_BUILDER_0X_BRIDGE']).resolve(); "
            "assert root in origin.parents, origin",
        ],
        cwd=output,
        env=env,
    )


def _install_locked_requirements(
    python: Path,
    lock_path: Path,
    target: Path,
    *,
    env: dict[str, str] | None = None,
    no_build_isolation: bool = False,
) -> None:
    command = [
        str(python),
        "-m",
        "pip",
        "install",
        "--quiet",
        "--progress-bar",
        "off",
        "--disable-pip-version-check",
        "--require-hashes",
        "--no-deps",
        "--target",
        str(target),
        "-r",
        str(lock_path),
    ]
    if no_build_isolation:
        command.append("--no-build-isolation")
    _run(command, env=env)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as input_file:
        for chunk in iter(lambda: input_file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _remove_tree_within(root: Path, target: Path) -> None:
    if not target.exists():
        return
    root_resolved = root.resolve()
    target_resolved = target.resolve()
    if root_resolved == target_resolved or root_resolved not in target_resolved.parents:
        raise RuntimeError(
            f"Refusing to remove outside {root_resolved}: {target_resolved}"
        )
    shutil.rmtree(target_resolved, onerror=_retry_remove_readonly)


def _retry_remove_readonly(
    function: Callable[..., object],
    path: str,
    exc_info: tuple[type[BaseException], BaseException, TracebackType | None],
) -> None:
    error = exc_info[1]
    if isinstance(error, PermissionError):
        os.chmod(path, stat.S_IWRITE)
        function(path)
        return
    raise error


def _run(
    args: list[str],
    *,
    cwd: Path | None = None,
    env: dict[str, str] | None = None,
    capture: bool = False,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        args,
        cwd=cwd,
        env=env,
        capture_output=capture,
        text=True,
        check=True,
    )


if __name__ == "__main__":
    raise SystemExit(main())
