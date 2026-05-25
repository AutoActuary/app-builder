from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Mapping
from zipfile import ZIP_DEFLATED, ZipFile

from .config import load_project_config
from .fileset import build_remap_table, collect_files
from .hooks import run_hook_commands
from .installer_bundle import create_exewrap_zip_installer
from .project import detect_version, expand_windows_envvars
from .python_runtime import (
    PythonEnvironmentResult,
    bundled_python_executable,
    ensure_python_environments as materialize_python_environments,
    python_executable,
)
from .schema import AppBuilderConfig


@dataclass(slots=True)
class ReleaseResult:
    version: str
    payload_archive: Path
    installer_archive: Path
    manifest_path: Path


def build_release(project_root: Path, *, version: str | None = None) -> ReleaseResult:
    _, config = load_project_config(project_root)
    version = version or detect_version(project_root)

    env_result = _run_dependency_stages(project_root)
    hook_env = _build_hook_environment(
        config.installer.name, config.installer.install_directory, project_root
    )
    python_candidates = _runtime_hook_python_candidates(
        project_root, config, env_result
    )

    run_hook_commands(
        project_root,
        config.build_hooks.pre_dist,
        environment=hook_env,
        python_candidates=python_candidates,
    )

    dist_dir = project_root / config.installer.dist
    dist_dir.mkdir(parents=True, exist_ok=True)

    included_files = collect_files(
        project_root,
        config.installer.paths.include,
        config.installer.paths.exclude,
    )
    remap_table = build_remap_table(
        project_root, included_files, config.installer.paths.remap
    )

    payload_archive = dist_dir / f"{_slugify(config.installer.name)}-{version}.zip"
    _write_payload_archive(payload_archive, remap_table, version=version)

    manifest = {
        "name": config.installer.name,
        "version": version,
        "install_directory": config.installer.install_directory,
        "add_uninstaller": config.installer.add_uninstaller,
        "payload_archive": payload_archive.name,
        "start_menu": [
            {
                "target": item.target,
                "display_name": item.display_name,
                "icon": item.icon,
            }
            for item in config.installer.start_menu
        ],
        "install_hooks": {
            "pre_install": config.installer.install_hooks.pre_install,
            "post_install": config.installer.install_hooks.post_install,
            "pre_uninstall": config.installer.install_hooks.pre_uninstall,
            "post_uninstall": config.installer.install_hooks.post_uninstall,
        },
        "included_files": [dst.as_posix() for dst in remap_table.values()],
    }
    manifest_path = (
        dist_dir / f"{_slugify(config.installer.name)}-{version}-manifest.json"
    )
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    installer_archive = dist_dir / (
        f"{_slugify(config.installer.name)}-{version}-installer.exe"
    )
    create_exewrap_zip_installer(
        installer_archive,
        payload_archive=payload_archive,
        manifest_path=manifest_path,
        app_name=config.installer.name,
        pause_on_exit=config.installer.pause_on_exit,
        add_uninstaller=config.installer.add_uninstaller,
    )

    run_hook_commands(
        project_root,
        config.build_hooks.post_dist,
        environment=hook_env,
        python_candidates=python_candidates,
    )
    run_hook_commands(
        project_root,
        config.build_hooks.post_process,
        environment=hook_env,
        python_candidates=python_candidates,
    )
    return ReleaseResult(
        version=version,
        payload_archive=payload_archive,
        installer_archive=installer_archive,
        manifest_path=manifest_path,
    )


def ensure_python_environments(project_root: Path) -> PythonEnvironmentResult:
    return _run_dependency_stages(project_root)


def _run_dependency_stages(project_root: Path) -> PythonEnvironmentResult:
    _, config = load_project_config(project_root)
    hook_env = _build_hook_environment(
        config.installer.name, config.installer.install_directory, project_root
    )
    run_hook_commands(
        project_root,
        config.build_hooks.pre_process,
        environment=hook_env,
        python_candidates=_host_hook_python_candidates(),
    )
    run_hook_commands(
        project_root,
        config.build_hooks.pre_python_bundled,
        environment=hook_env,
        python_candidates=_configured_bundled_hook_python_candidates(
            project_root, config
        ),
    )
    env_result = materialize_python_environments(project_root)
    bundled_candidates = _bundled_hook_python_candidates(env_result)
    run_hook_commands(
        project_root,
        config.build_hooks.post_python_bundled,
        environment=hook_env,
        python_candidates=bundled_candidates,
    )
    run_hook_commands(
        project_root,
        config.build_hooks.pre_python_venv,
        environment=hook_env,
        python_candidates=bundled_candidates,
    )
    run_hook_commands(
        project_root,
        config.build_hooks.post_python_venv,
        environment=hook_env,
        python_candidates=_hook_python_candidates(
            env_result.python_venv, env_result.python_bundled
        ),
    )
    return env_result


def _host_hook_python_candidates() -> list[Path]:
    return [Path(sys.executable)]


def _hook_python_candidates(*candidates: Path | None) -> list[Path]:
    return [candidate for candidate in candidates if candidate is not None] + [
        Path(sys.executable)
    ]


def _bundled_hook_python_candidates(
    env_result: PythonEnvironmentResult,
) -> list[Path]:
    return _hook_python_candidates(env_result.python_bundled, env_result.python_venv)


def _configured_bundled_hook_python_candidates(
    project_root: Path,
    config: AppBuilderConfig,
) -> list[Path]:
    bundled_python: Path | None = None
    if config.python_bundled is not None:
        bundled_python = bundled_python_executable(
            project_root / config.python_bundled.path
        )

    venv_python: Path | None = None
    if config.python_venv is not None:
        venv_python = python_executable(project_root / config.python_venv.path)

    return _hook_python_candidates(bundled_python, venv_python)


def _runtime_hook_python_candidates(
    project_root: Path,
    config: AppBuilderConfig,
    env_result: PythonEnvironmentResult | None = None,
) -> list[Path]:
    if env_result is not None:
        return _hook_python_candidates(
            env_result.python_venv, env_result.python_bundled
        )

    venv_python: Path | None = None
    if config.python_venv is not None:
        venv_python = python_executable(project_root / config.python_venv.path)

    bundled_python: Path | None = None
    if config.python_bundled is not None:
        bundled_python = bundled_python_executable(
            project_root / config.python_bundled.path
        )

    return _hook_python_candidates(venv_python, bundled_python)


def _write_payload_archive(
    payload_archive: Path,
    remap_table: Mapping[Path, PurePosixPath],
    *,
    version: str,
) -> None:
    with ZipFile(payload_archive, "w", compression=ZIP_DEFLATED) as zip_file:
        for source, destination in sorted(
            remap_table.items(), key=lambda item: item[1].as_posix()
        ):
            zip_file.write(source, destination.as_posix())
        zip_file.writestr("version.txt", version)


def _build_hook_environment(
    app_name: str, install_directory: str, project_root: Path
) -> dict[str, str]:
    return {
        "app_builder_name": app_name,
        "app_builder_install_directory": expand_windows_envvars(install_directory),
        "app_builder_project_root": str(project_root),
        "app_builder_start_menu": os.path.join(
            os.environ.get("APPDATA", ""),
            "Microsoft",
            "Windows",
            "Start Menu",
            "Programs",
            app_name,
        ),
    }


def upload_release_to_github(
    project_root: Path, *, release: ReleaseResult, draft: bool
) -> str:
    _, config = load_project_config(project_root)
    hook_env = _build_hook_environment(
        config.installer.name, config.installer.install_directory, project_root
    )
    python_candidates = _runtime_hook_python_candidates(project_root, config)
    run_hook_commands(
        project_root,
        config.build_hooks.pre_github_release,
        environment=hook_env,
        python_candidates=python_candidates,
    )

    gh_executable = _resolve_github_cli()
    artifacts = [
        release.payload_archive,
        release.installer_archive,
        release.manifest_path,
    ]
    view_result = _run_gh(
        project_root,
        gh_executable,
        ["release", "view", release.version, "--json", "url", "--jq", ".url"],
        check=False,
    )
    if view_result.returncode == 0:
        html_url = view_result.stdout.strip()
        _run_gh(
            project_root,
            gh_executable,
            [
                "release",
                "upload",
                release.version,
                *(str(artifact) for artifact in artifacts),
                "--clobber",
            ],
            check=True,
        )
    else:
        create_args = [
            "release",
            "create",
            release.version,
            *(str(artifact) for artifact in artifacts),
            "--title",
            release.version,
            "--notes",
            "",
        ]
        if draft:
            create_args.append("--draft")
        _run_gh(project_root, gh_executable, create_args, check=True)
        html_url = _run_gh(
            project_root,
            gh_executable,
            ["release", "view", release.version, "--json", "url", "--jq", ".url"],
            check=True,
        ).stdout.strip()

    if not html_url:
        html_url = release.version

    run_hook_commands(
        project_root,
        config.build_hooks.post_github_release,
        environment=hook_env,
        python_candidates=python_candidates,
    )
    return html_url


def _resolve_github_cli() -> str:
    gh_executable = shutil.which("gh.exe") or shutil.which("gh")
    if gh_executable is None:
        raise RuntimeError(
            "GitHub releases require GitHub CLI (`gh.exe`) on PATH. "
            "Install gh.exe and authenticate with `gh auth login` before running "
            "`app-builder release-gh`."
        )
    return gh_executable


def _run_gh(
    project_root: Path,
    gh_executable: str,
    args: list[str],
    *,
    check: bool,
) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        [gh_executable, *args],
        cwd=project_root,
        capture_output=True,
        text=True,
    )
    if check and result.returncode != 0:
        stderr = result.stderr.strip()
        stdout = result.stdout.strip()
        detail = stderr or stdout or f"exit code {result.returncode}"
        raise RuntimeError(
            "GitHub CLI command failed: " f"{' '.join(['gh', *args])}\n{detail}"
        )
    return result


def _slugify(value: str) -> str:
    slug = "".join(char.lower() if char.isalnum() else "-" for char in value)
    return slug.strip("-")
