from __future__ import annotations

import argparse
import json
import os
import shutil
import stat
import subprocess
import sys
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app_builder.exewrap import stamp_exe_wrap_config
from app_builder_meta.version_cache import APP_BUILDER_REPOSITORY_URL

DEFAULT_REF = "v0.20.0"


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Build the app-builder 0.x compatibility bridge."
    )
    parser.add_argument("--ref", default=DEFAULT_REF)
    parser.add_argument("--repo-url", default=APP_BUILDER_REPOSITORY_URL)
    parser.add_argument("--output", type=Path, default=Path("__app_builder_0.x__"))
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
    _run(["git", "checkout", args.ref], cwd=checkout)
    commit = _run(["git", "rev-parse", "HEAD"], cwd=checkout, capture=True).stdout.strip()

    _remove_tree_within(project_root, output)
    output.mkdir(parents=True, exist_ok=True)
    shutil.copytree(checkout / "app_builder", output / "app_builder")
    shutil.copy2(checkout / "cli" / "py" / "app-builder.py", output / "legacy-cli.py")
    shutil.copy2(checkout / "requirements.txt", output / "requirements.txt")
    _write_bootstrap(output / "app-builder-legacy.py")
    (output / "app-builder.exe").write_bytes(
        stamp_exe_wrap_config(_render_legacy_bridge_launcher_config())
    )

    site_packages = output / "site-packages"
    site_packages.mkdir()
    _run(
        [
            str(args.python),
            "-m",
            "pip",
            "install",
            "--upgrade",
            "--target",
            str(site_packages),
            "-r",
            str(output / "requirements.txt"),
        ]
    )
    _smoke_import(args.python, output)

    manifest = {
        "ref": args.ref,
        "resolved_commit": commit,
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
    env["PYTHONPATH"] = os.pathsep.join(
        [str(output / "site-packages"), str(output)]
    )
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


def _remove_tree_within(root: Path, target: Path) -> None:
    if not target.exists():
        return
    root_resolved = root.resolve()
    target_resolved = target.resolve()
    if root_resolved == target_resolved or root_resolved not in target_resolved.parents:
        raise RuntimeError(f"Refusing to remove outside {root_resolved}: {target_resolved}")
    shutil.rmtree(target_resolved, onexc=_retry_remove_readonly)


def _retry_remove_readonly(
    function: Callable[[str], object],
    path: str,
    exc_info: BaseException,
) -> None:
    if isinstance(exc_info, PermissionError):
        os.chmod(path, stat.S_IWRITE)
        function(path)
        return
    raise exc_info


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
