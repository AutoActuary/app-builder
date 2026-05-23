from __future__ import annotations

import json
import os
import subprocess
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from tempfile import TemporaryDirectory
from typing import Mapping
from zipfile import ZIP_DEFLATED, ZipFile

from .config import load_project_config
from .fileset import build_remap_table, collect_files
from .hooks import run_hook_commands
from .project import detect_version, expand_windows_envvars
from .python_runtime import (
    PythonEnvironmentResult,
    ensure_python_environments as materialize_python_environments,
)


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
    python_for_hooks = env_result.python_venv or env_result.python_bundled

    run_hook_commands(
        project_root,
        config.build_hooks.pre_dist,
        environment=hook_env,
        python_for_hooks=python_for_hooks,
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
        "install_directory": expand_windows_envvars(config.installer.install_directory),
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

    installer_archive = (
        dist_dir / f"{_slugify(config.installer.name)}-{version}-installer.zip"
    )
    _write_installer_archive(
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
        python_for_hooks=python_for_hooks,
    )
    run_hook_commands(
        project_root,
        config.build_hooks.post_process,
        environment=hook_env,
        python_for_hooks=python_for_hooks,
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
        python_for_hooks=None,
    )
    run_hook_commands(
        project_root,
        config.build_hooks.pre_python_bundled,
        environment=hook_env,
        python_for_hooks=None,
    )
    env_result = materialize_python_environments(project_root)
    python_for_hooks = env_result.python_bundled
    run_hook_commands(
        project_root,
        config.build_hooks.post_python_bundled,
        environment=hook_env,
        python_for_hooks=python_for_hooks,
    )
    run_hook_commands(
        project_root,
        config.build_hooks.pre_python_venv,
        environment=hook_env,
        python_for_hooks=python_for_hooks,
    )
    run_hook_commands(
        project_root,
        config.build_hooks.post_python_venv,
        environment=hook_env,
        python_for_hooks=env_result.python_venv or python_for_hooks,
    )
    return env_result


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


def _write_installer_archive(
    installer_archive: Path,
    *,
    payload_archive: Path,
    manifest_path: Path,
    app_name: str,
    pause_on_exit: bool,
    add_uninstaller: bool,
) -> None:
    with TemporaryDirectory() as temp_dir_str:
        temp_dir = Path(temp_dir_str)
        install_cmd = temp_dir / "install.cmd"
        uninstall_cmd = temp_dir / "uninstall.cmd"
        install_cmd.write_text(
            _render_install_script(
                app_name, payload_archive.name, manifest_path.name, pause_on_exit
            ),
            encoding="utf-8",
        )
        uninstall_cmd.write_text(
            _render_uninstall_script(app_name, pause_on_exit), encoding="utf-8"
        )
        with ZipFile(installer_archive, "w", compression=ZIP_DEFLATED) as zip_file:
            zip_file.write(payload_archive, payload_archive.name)
            zip_file.write(manifest_path, manifest_path.name)
            zip_file.write(install_cmd, install_cmd.name)
            if add_uninstaller:
                zip_file.write(uninstall_cmd, uninstall_cmd.name)


def _render_install_script(
    app_name: str, payload_name: str, manifest_name: str, pause_on_exit: bool
) -> str:
    pause_block = "pause\n" if pause_on_exit else ""
    return (
        "@echo off\n"
        f"echo Installing {app_name}\n"
        f"echo Payload archive: {payload_name}\n"
        f"echo Manifest: {manifest_name}\n"
        "echo Extract this zip bundle and follow your deployment policy.\n"
        f"{pause_block}"
    )


def _render_uninstall_script(app_name: str, pause_on_exit: bool) -> str:
    pause_block = "pause\n" if pause_on_exit else ""
    return f"@echo off\necho Uninstall {app_name} according to your deployment policy.\n{pause_block}"


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
    run_hook_commands(
        project_root,
        config.build_hooks.pre_github_release,
        environment=hook_env,
        python_for_hooks=None,
    )

    remote_url = subprocess.run(
        ["git", "config", "--get", "remote.origin.url"],
        cwd=project_root,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    owner, repo = _parse_github_remote(remote_url)
    token = os.environ.get("GITHUB_TOKEN")
    if not token:
        raise RuntimeError("Set GITHUB_TOKEN before using 'app-builder release-gh'.")

    import urllib.request

    body = json.dumps(
        {
            "tag_name": release.version,
            "name": release.version,
            "draft": draft,
        }
    ).encode("utf-8")
    request = urllib.request.Request(
        f"https://api.github.com/repos/{owner}/{repo}/releases",
        data=body,
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "User-Agent": "app-builder",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    with urllib.request.urlopen(request) as response:
        release_payload = json.loads(response.read().decode("utf-8"))
    upload_url = release_payload["upload_url"].split("{", 1)[0]
    html_url = str(release_payload["html_url"])
    for artifact in (
        release.payload_archive,
        release.installer_archive,
        release.manifest_path,
    ):
        upload_request = urllib.request.Request(
            f"{upload_url}?name={artifact.name}",
            data=artifact.read_bytes(),
            headers={
                "Accept": "application/vnd.github+json",
                "Authorization": f"Bearer {token}",
                "User-Agent": "app-builder",
                "Content-Type": "application/octet-stream",
            },
            method="POST",
        )
        with urllib.request.urlopen(upload_request):
            pass

    run_hook_commands(
        project_root,
        config.build_hooks.post_github_release,
        environment=hook_env,
        python_for_hooks=None,
    )
    return html_url


def _parse_github_remote(remote_url: str) -> tuple[str, str]:
    cleaned = remote_url.removesuffix(".git")
    if cleaned.startswith("git@github.com:"):
        owner_repo = cleaned.split(":", 1)[1]
    elif "github.com/" in cleaned:
        owner_repo = cleaned.split("github.com/", 1)[1]
    else:
        raise RuntimeError(f"Unsupported GitHub remote URL: {remote_url}")
    owner, repo = owner_repo.split("/", 1)
    return owner, repo


def _slugify(value: str) -> str:
    slug = "".join(char.lower() if char.isalnum() else "-" for char in value)
    return slug.strip("-")
