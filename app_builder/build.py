from __future__ import annotations

import json
import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Mapping
from zipfile import ZIP_DEFLATED, ZipFile

from .config import load_project_config
from .exewrap import (
    stamp_exe_icon,
    stamp_exe_wrap_config,
    vendored_console_launcher_bytes,
)
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
from .sevenzip import create_7z_payload_archive, vendored_7zip_files


@dataclass(slots=True)
class ReleaseResult:
    version: str
    payload_archive: Path
    installer_archive: Path
    manifest_path: Path


def build_release(project_root: Path, *, version: str | None = None) -> ReleaseResult:
    version = version or detect_version(project_root)
    _, config = load_project_config(project_root, app_version=version)

    env_result = _run_dependency_stages(project_root, app_version=version)
    hook_env = _build_hook_environment(
        config.installer.name,
        config.installer.install_directory,
        project_root,
        version=version,
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
    installer_icon_path = _resolve_installer_icon(project_root, config)

    included_files = collect_files(
        project_root,
        config.installer.paths.include,
        config.installer.paths.exclude,
    )
    remap_table = build_remap_table(
        project_root, included_files, config.installer.paths.remap
    )
    _add_app_builder_meta_launcher(config, dist_dir, remap_table, installer_icon_path)

    payload_archive = dist_dir / (
        f"{_slugify(config.installer.name)}-{version}."
        f"{config.installer.payload_format}"
    )
    _write_payload_archive(
        payload_archive,
        project_root,
        remap_table,
        version=version,
        payload_format=config.installer.payload_format,
    )

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
                "icon": item.icon or config.installer.icon,
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
        icon_path=installer_icon_path,
        top_layer_files=_installer_top_layer_files(config),
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


def _run_dependency_stages(
    project_root: Path,
    *,
    app_version: str | None = None,
) -> PythonEnvironmentResult:
    _, config = load_project_config(project_root, app_version=app_version)
    hook_env = _build_hook_environment(
        config.installer.name, config.installer.install_directory, project_root
    )
    run_hook_commands(
        project_root,
        config.build_hooks.pre_process,
        environment=hook_env,
        python_candidates=_runtime_hook_python_candidates(project_root, config),
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


def _hook_python_candidates(*candidates: Path | None) -> list[Path]:
    return [candidate for candidate in candidates if candidate is not None]


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
    project_root: Path,
    remap_table: Mapping[Path, PurePosixPath],
    *,
    version: str,
    payload_format: str = "zip",
) -> None:
    if payload_format == "7z":
        create_7z_payload_archive(
            payload_archive,
            project_root,
            remap_table,
            version=version,
        )
        return
    if payload_format != "zip":
        raise ValueError(f"Unknown installer.payload_format: {payload_format}")
    with ZipFile(payload_archive, "w", compression=ZIP_DEFLATED) as zip_file:
        for source, destination in sorted(
            remap_table.items(), key=lambda item: item[1].as_posix()
        ):
            zip_file.write(source, destination.as_posix())
        zip_file.writestr("version.txt", version)


def _add_app_builder_meta_launcher(
    config: AppBuilderConfig,
    dist_dir: Path,
    remap_table: dict[Path, PurePosixPath],
    installer_icon_path: Path | None,
) -> None:
    if config.installer.name.strip().lower() != "app-builder":
        return
    launcher_path = dist_dir / "_generated" / "app-builder.exe"
    launcher_path.parent.mkdir(parents=True, exist_ok=True)
    launcher = None
    if installer_icon_path is not None:
        launcher = stamp_exe_icon(
            vendored_console_launcher_bytes(),
            installer_icon_path,
        )
    launcher_path.write_bytes(
        stamp_exe_wrap_config(_render_meta_launcher_config(), launcher=launcher)
    )
    remap_table[launcher_path] = PurePosixPath("app-builder.exe")


def _resolve_installer_icon(
    project_root: Path,
    config: AppBuilderConfig,
) -> Path | None:
    icon = config.installer.icon.strip()
    if not icon:
        return None
    icon_path = project_root / icon
    if icon_path.is_file():
        return icon_path
    if icon == "application-templates/icon.ico":
        return None
    raise FileNotFoundError(f"Configured installer.icon does not exist: {icon_path}")


def _installer_top_layer_files(config: AppBuilderConfig) -> Mapping[Path, str]:
    if config.installer.payload_format == "7z":
        return vendored_7zip_files()
    return {}


def _render_meta_launcher_config() -> bytes:
    return (
        "{\n"
        '  "env": {\n'
        '    "APP_BUILDER_INSTALL_ROOT": "@{exe_dir}",\n'
        '    "PYTHONNOUSERSITE": "1",\n'
        '    "PYTHONPATH": "@{exe_dir}"\n'
        "  },\n"
        '  "command": [\n'
        '    "@{exe_dir}\\\\bin\\\\python\\\\python\\\\python.exe",\n'
        '    "-P",\n'
        '    "-X",\n'
        '    "utf8",\n'
        '    "-m",\n'
        '    "app_builder_meta",\n'
        "    @{args}\n"
        "  ]\n"
        "}\n"
    ).encode("utf-8")


def _build_hook_environment(
    app_name: str,
    install_directory: str,
    project_root: Path,
    *,
    version: str | None = None,
) -> dict[str, str]:
    return {
        "app_builder_name": app_name,
        "app_builder_version": version or "",
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
    _, config = load_project_config(project_root, app_version=release.version)
    hook_env = _build_hook_environment(
        config.installer.name,
        config.installer.install_directory,
        project_root,
        version=release.version,
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
    for candidate in _github_cli_candidates():
        if candidate.is_file():
            return str(candidate)
    raise RuntimeError(_github_cli_missing_message())


def _github_cli_candidates() -> list[Path]:
    candidates: list[Path] = []
    candidates.extend(_where_github_cli_paths())
    candidates.extend(
        Path(candidate)
        for candidate in (shutil.which("gh.exe"), shutil.which("gh"))
        if candidate
    )
    candidates.extend(_known_github_cli_paths())
    return _existing_unique_paths(candidates)


def _where_github_cli_paths() -> list[Path]:
    where_executable = shutil.which("where.exe")
    if where_executable is None:
        return []

    candidates: list[Path] = []
    for executable_name in ("gh.exe", "gh"):
        result = subprocess.run(
            [where_executable, executable_name],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            continue
        candidates.extend(
            Path(line.strip()) for line in result.stdout.splitlines() if line.strip()
        )
    return candidates


def _known_github_cli_paths() -> list[Path]:
    candidates: list[Path] = []
    for env_name in ("ProgramFiles", "ProgramFiles(x86)"):
        base = os.environ.get(env_name)
        if base:
            candidates.append(Path(base) / "GitHub CLI" / "gh.exe")
            candidates.extend(
                _glob_existing_paths(Path(base) / "WinGet" / "Packages", "GitHub.cli_*")
            )

    local_app_data = os.environ.get("LOCALAPPDATA")
    if local_app_data:
        local_root = Path(local_app_data)
        candidates.append(local_root / "Programs" / "GitHub CLI" / "gh.exe")
        candidates.append(local_root / "GitHub CLI" / "gh.exe")
        candidates.extend(
            _glob_existing_paths(
                local_root / "Microsoft" / "WinGet" / "Packages", "GitHub.cli_*"
            )
        )

    program_data = os.environ.get("ProgramData")
    if program_data:
        candidates.append(Path(program_data) / "chocolatey" / "bin" / "gh.exe")

    user_profile = os.environ.get("USERPROFILE")
    if user_profile:
        user_root = Path(user_profile)
        candidates.append(user_root / "scoop" / "shims" / "gh.exe")
        candidates.append(
            user_root / "scoop" / "apps" / "gh" / "current" / "bin" / "gh.exe"
        )

    return candidates


def _glob_existing_paths(root: Path, package_pattern: str) -> list[Path]:
    if not root.is_dir():
        return []
    candidates: list[Path] = []
    for package_root in root.glob(package_pattern):
        candidates.append(package_root / "gh.exe")
        candidates.extend(package_root.glob("**/gh.exe"))
    return candidates


def _existing_unique_paths(candidates: list[Path]) -> list[Path]:
    unique_candidates: list[Path] = []
    seen: set[str] = set()
    for candidate in candidates:
        key = os.path.normcase(os.path.abspath(os.fspath(candidate)))
        if key in seen:
            continue
        seen.add(key)
        unique_candidates.append(candidate)
    return unique_candidates


def _github_cli_missing_message() -> str:
    return (
        "GitHub releases require GitHub CLI (`gh.exe`). app-builder searched "
        "PATH, where.exe results, and common GitHub CLI install locations but "
        "could not find it.\n\n"
        "Install GitHub CLI, then authenticate before running `app-builder "
        "release-gh`:\n"
        "  winget install --id GitHub.cli\n"
        "  gh auth login\n\n"
        "Other install options:\n"
        "  choco install gh\n"
        "  scoop install gh\n"
        "  Download the MSI from https://cli.github.com/\n\n"
        "If gh.exe is already installed, add its directory to PATH or install it "
        "in one of the standard locations such as `C:\\Program Files\\GitHub "
        "CLI\\gh.exe`."
    )


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
