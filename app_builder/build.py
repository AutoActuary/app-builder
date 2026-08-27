from __future__ import annotations

import json
import hashlib
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Mapping
from urllib.parse import quote
from zipfile import ZIP_DEFLATED, ZipFile

from .build_preflight import validate_build_configuration
from .build_reporting import BuildReporter, build_log_path
from .config import load_project_config
from .exewrap import (
    stamp_exe_icon,
    stamp_exe_wrap_config,
    vendored_console_launcher_bytes,
)
from .fileset import (
    build_remap_table,
    collect_files,
    validate_archive_path,
    validate_remap_table,
)
from .hooks import run_hook_commands
from .installer_bundle import create_exewrap_zip_installer
from .project import detect_version, expand_windows_envvars
from .python_runtime import (
    PythonEnvironmentMaterializer,
    PythonEnvironmentResult,
    bundled_python_executable,
    python_executable,
)
from .release_preflight import (
    run_publication_preflight,
    write_checksums_file,
    write_release_notes,
)
from .release_outputs import (
    ReleaseOutput,
    describe_output,
    prepare_configured_output_locations,
    resolve_configured_outputs,
    select_publication_outputs,
)
from .schema import AppBuilderConfig
from .sevenzip import create_7z_payload_archive, vendored_7zip_files


@dataclass(slots=True)
class ReleaseResult:
    version: str
    payload_archive: Path
    installer_archive: Path
    manifest_path: Path
    checksums_path: Path
    release_notes_path: Path
    outputs: tuple[ReleaseOutput, ...] = ()
    github_artifacts: tuple[Path, ...] | None = None
    build_log_path: Path | None = None

    @property
    def publication_artifacts(self) -> tuple[Path, ...]:
        if self.github_artifacts is not None:
            return self.github_artifacts
        return (
            self.payload_archive,
            self.installer_archive,
            self.manifest_path,
            self.checksums_path,
        )


def _current_git_commit(project_root: Path) -> str | None:
    result = subprocess.run(
        ["git", "rev-parse", "--verify", "HEAD"],
        cwd=project_root,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        return None
    commit = result.stdout.strip()
    return commit or None


def build_release(
    project_root: Path,
    *,
    version: str | None = None,
    verbose: bool = False,
) -> ReleaseResult:
    build_commit = _current_git_commit(project_root)
    version = version or detect_version(project_root)
    _, config = load_project_config(project_root, app_version=version)
    validate_build_configuration(project_root, config, version=version)
    dist_dir = project_root / config.installer.dist
    artifact_prefix = f"{_slugify(config.installer.name)}-{version}"
    reporter = BuildReporter(
        build_log_path(dist_dir, artifact_prefix=artifact_prefix),
        total_stages=8,
        verbose=verbose,
    )
    with reporter.stage("Configuration preflight"):
        reporter.detail(f"Project: {project_root.resolve()}")
        reporter.detail(f"Release: {config.installer.name} {version}")
        reporter.detail(f"Install target: {config.installer.install_directory}")

    with reporter.stage("Dependency materialization"):
        env_result = _run_dependency_stages(project_root, app_version=version)
        for build_input in env_result.build_inputs:
            reporter.detail(f"Build input: {json.dumps(build_input, sort_keys=True)}")
    hook_env = _build_hook_environment(
        config.installer.name,
        config.installer.install_directory,
        project_root,
        version=version,
    )
    python_candidates = _runtime_hook_python_candidates(
        project_root, config, env_result
    )

    with reporter.stage("Pre-distribution hooks"):
        run_hook_commands(
            project_root,
            config.build_hooks.pre_dist,
            environment=hook_env,
            python_candidates=python_candidates,
        )

    with reporter.stage("Payload file selection"):
        dist_dir.mkdir(parents=True, exist_ok=True)
        installer_icon_path = _resolve_installer_icon(project_root, config)
        included_files = collect_files(
            project_root,
            config.installer.paths.include,
            config.installer.paths.exclude,
        )
        if not config.installer.paths.include_dist:
            included_files = _exclude_payload_directory(included_files, dist_dir)
        if _shortcut_inherits_installer_icon(config, installer_icon_path):
            assert installer_icon_path is not None
            included_files = _include_payload_file(included_files, installer_icon_path)
            reporter.detail(
                "Implicit payload input: "
                f"{installer_icon_path.resolve().relative_to(project_root.resolve())} "
                "(inherited Start Menu icon)"
            )
        remap_table = build_remap_table(
            project_root, included_files, config.installer.paths.remap
        )
        _add_app_builder_meta_launcher(
            config, dist_dir, remap_table, installer_icon_path
        )
        validate_remap_table(remap_table, reserved_paths=("version.txt",))
        installer_hook_python_candidates = _installer_hook_python_candidates(
            project_root, config, remap_table
        )
        installer_bundled_python_path = _installer_bundled_python_path(
            project_root, config, remap_table
        )
        start_menu = _start_menu_manifest(config, remap_table, installer_icon_path)
        _validate_installer_payload_contract(
            config,
            remap_table,
            start_menu=start_menu,
            hook_python_candidates=installer_hook_python_candidates,
        )
        reporter.detail(f"Resolved {len(remap_table)} payload files:")
        for source, destination in sorted(
            remap_table.items(), key=lambda item: item[1].as_posix()
        ):
            reporter.detail(
                f"  {source.resolve().relative_to(project_root.resolve())} -> "
                f"{destination.as_posix()}"
            )

    payload_archive = dist_dir / (
        f"{_slugify(config.installer.name)}-{version}."
        f"{config.installer.payload_format}"
    )
    with reporter.stage("Payload archive and manifest"):
        current_commit = _current_git_commit(project_root)
        if build_commit is not None and current_commit != build_commit:
            raise RuntimeError(
                "Git HEAD changed while release artifacts were being built. "
                "Run the release again from a stable checkout."
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
            "build_commit": build_commit,
            "install_directory": config.installer.install_directory,
            "add_uninstaller": config.installer.add_uninstaller,
            "payload_archive": payload_archive.name,
            "hook_python_candidates": installer_hook_python_candidates,
            "python_bundled_path": installer_bundled_python_path,
            "start_menu": start_menu,
            "install_hooks": {
                "pre_install": config.installer.install_hooks.pre_install,
                "post_install": config.installer.install_hooks.post_install,
                "pre_uninstall": config.installer.install_hooks.pre_uninstall,
                "post_uninstall": config.installer.install_hooks.post_uninstall,
            },
            "included_files": [dst.as_posix() for dst in remap_table.values()],
            "build_inputs": list(env_result.build_inputs),
        }
        manifest_path = dist_dir / f"{artifact_prefix}-manifest.json"
        manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        reporter.detail(
            f"Payload: {payload_archive} ({payload_archive.stat().st_size} bytes)"
        )
        reporter.detail(f"Manifest: {manifest_path}")

    installer_archive = dist_dir / (
        f"{_slugify(config.installer.name)}-{version}-installer.exe"
    )
    with reporter.stage("Installer assembly"):
        create_exewrap_zip_installer(
            installer_archive,
            payload_archive=payload_archive,
            manifest_path=manifest_path,
            app_name=config.installer.name,
            wait_on_exit=config.installer.wait_on_exit,
            add_uninstaller=config.installer.add_uninstaller,
            icon_path=installer_icon_path,
            top_layer_files=_installer_top_layer_files(config),
            bootstrap_pre_extract_commands=config.installer.bootstrap_hooks.pre_extract,
        )
        reporter.detail(
            f"Installer: {installer_archive} ({installer_archive.stat().st_size} bytes)"
        )

    with reporter.stage("Post-distribution hooks"):
        sealed_outputs = {
            payload_archive: _sha256_file(payload_archive),
            manifest_path: _sha256_file(manifest_path),
        }
        removed_outputs = prepare_configured_output_locations(
            dist_dir,
            config.outputs,
            protected_paths=(payload_archive, installer_archive, manifest_path),
        )
        for removed_output in removed_outputs:
            reporter.detail(f"Removed stale named-output candidate: {removed_output}")
        run_hook_commands(
            project_root,
            config.build_hooks.post_dist,
            environment=hook_env,
            python_candidates=python_candidates,
        )
        _assert_sealed_release_outputs_unchanged(sealed_outputs)
    checksums_path = dist_dir / f"{artifact_prefix}-SHA256SUMS.txt"
    release_notes_path = dist_dir / f"{artifact_prefix}-release-notes.md"
    with reporter.stage("Integrity metadata and publication outputs"):
        configured_output_paths = resolve_configured_outputs(
            dist_dir,
            config.outputs,
            occupied_paths=(
                payload_archive,
                installer_archive,
                manifest_path,
                checksums_path,
                release_notes_path,
            ),
        )
        checksum_inputs = (
            payload_archive,
            installer_archive,
            manifest_path,
            *(path for _, path in configured_output_paths),
        )
        write_checksums_file(checksum_inputs, checksums_path)
        outputs = (
            describe_output("payload", payload_archive),
            describe_output("installer", installer_archive),
            describe_output("manifest", manifest_path),
            *(describe_output(name, path) for name, path in configured_output_paths),
            describe_output("checksums", checksums_path),
        )
        github_outputs = select_publication_outputs(
            outputs,
            config.publications.github.outputs,
            declared_names=(spec.name for spec in config.outputs),
        )
        write_release_notes(
            project_root,
            app_name=config.installer.name,
            version=version,
            artifacts=(output.path for output in github_outputs),
            output_path=release_notes_path,
        )
        for output in outputs:
            reporter.detail(
                f"Output {output.name}: {output.path.name} "
                f"({output.size} bytes, sha256:{output.sha256})"
            )
        reporter.detail(
            "GitHub selection: "
            + ", ".join(output.path.name for output in github_outputs)
        )
    return ReleaseResult(
        version=version,
        payload_archive=payload_archive,
        installer_archive=installer_archive,
        manifest_path=manifest_path,
        checksums_path=checksums_path,
        release_notes_path=release_notes_path,
        outputs=outputs,
        github_artifacts=tuple(output.path for output in github_outputs),
        build_log_path=reporter.log_path,
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
    app_builder_python = Path(sys.executable).resolve()
    run_hook_commands(
        project_root,
        config.build_hooks.pre_process,
        environment=hook_env,
        python_candidates=[app_builder_python],
    )
    run_hook_commands(
        project_root,
        config.build_hooks.pre_python_bundled,
        environment=hook_env,
        python_candidates=[app_builder_python],
    )
    materializer = PythonEnvironmentMaterializer(
        project_root,
        app_version=app_version,
    )
    bundled_python = materializer.materialize_bundled()
    bundled_candidates = _hook_python_candidates(
        bundled_python,
        app_builder_python,
    )
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
    venv_python = materializer.materialize_venv()
    env_result = materializer.result()
    run_hook_commands(
        project_root,
        config.build_hooks.post_python_venv,
        environment=hook_env,
        python_candidates=_hook_python_candidates(
            venv_python,
            bundled_python,
            app_builder_python,
        ),
    )
    return env_result


def _hook_python_candidates(*candidates: Path | None) -> list[Path]:
    return [candidate for candidate in candidates if candidate is not None]


def _runtime_hook_python_candidates(
    project_root: Path,
    config: AppBuilderConfig,
    env_result: PythonEnvironmentResult | None = None,
) -> list[Path]:
    if env_result is not None:
        return _hook_python_candidates(
            env_result.python_venv,
            env_result.python_bundled,
            Path(sys.executable).resolve(),
        )

    venv_python: Path | None = None
    if config.python_venv is not None:
        venv_python = python_executable(project_root / config.python_venv.path)

    bundled_python: Path | None = None
    if config.python_bundled is not None:
        bundled_python = bundled_python_executable(
            project_root / config.python_bundled.path
        )

    return _hook_python_candidates(
        venv_python,
        bundled_python,
        Path(sys.executable).resolve(),
    )


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
            _paths_validated=True,
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


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as input_file:
        for chunk in iter(lambda: input_file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _assert_sealed_release_outputs_unchanged(
    expected_digests: Mapping[Path, str],
) -> None:
    for path, expected_digest in expected_digests.items():
        if not path.is_file():
            raise RuntimeError(
                f"post_dist removed sealed release file {path.name!r}. Payload and "
                "manifest files are embedded during installer assembly and cannot "
                "be changed afterward."
            )
        if _sha256_file(path) != expected_digest:
            raise RuntimeError(
                f"post_dist modified sealed release file {path.name!r}. Generate "
                "payload inputs in pre_dist; post_dist may create extra outputs or "
                "sign the final installer, but the embedded payload and manifest "
                "must remain unchanged."
            )


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
    configured_icon = config.installer.icon
    if configured_icon is None or not configured_icon.strip():
        return None
    icon = Path(configured_icon)
    if icon.is_absolute() or ".." in icon.parts:
        raise ValueError("installer.icon must be a project-relative file path.")
    icon_path = (project_root / icon).resolve()
    try:
        icon_path.relative_to(project_root.resolve())
    except ValueError as error:
        raise ValueError("installer.icon must resolve inside the project.") from error
    if icon_path.is_file():
        return icon_path
    raise FileNotFoundError(f"Configured installer.icon does not exist: {icon_path}")


def _shortcut_inherits_installer_icon(
    config: AppBuilderConfig,
    installer_icon_path: Path | None,
) -> bool:
    return installer_icon_path is not None and any(
        shortcut.icon is None for shortcut in config.installer.start_menu
    )


def _include_payload_file(files: list[Path], required_file: Path) -> list[Path]:
    resolved_required = required_file.resolve()
    if any(file_path.resolve() == resolved_required for file_path in files):
        return files
    return [*files, resolved_required]


def _start_menu_manifest(
    config: AppBuilderConfig,
    remap_table: Mapping[Path, PurePosixPath],
    installer_icon_path: Path | None,
) -> list[dict[str, str | None]]:
    inherited_icon: str | None = None
    if _shortcut_inherits_installer_icon(config, installer_icon_path):
        assert installer_icon_path is not None
        destination = remap_table.get(installer_icon_path.resolve())
        if destination is None:
            raise RuntimeError(
                "The inherited installer icon was not included in the payload."
            )
        inherited_icon = destination.as_posix()

    return [
        {
            "target": shortcut.target,
            "display_name": shortcut.display_name,
            "icon": inherited_icon if shortcut.icon is None else shortcut.icon or None,
        }
        for shortcut in config.installer.start_menu
    ]


def _exclude_payload_directory(files: list[Path], directory: Path) -> list[Path]:
    resolved_directory = directory.resolve()
    selected = [
        path
        for path in files
        if path.resolve() != resolved_directory
        and resolved_directory not in path.resolve().parents
    ]
    if not selected:
        raise ValueError(
            "Payload file set is empty after excluding installer.dist. Set "
            "installer.paths.include_dist: true only when release output genuinely "
            "belongs inside the installed application."
        )
    return selected


def _installer_hook_python_candidates(
    project_root: Path,
    config: AppBuilderConfig,
    remap_table: Mapping[Path, PurePosixPath],
) -> list[str]:
    source_candidates: list[Path] = []
    if config.python_venv is not None:
        source_candidates.append(
            (
                project_root / config.python_venv.path / "Scripts" / "python.exe"
            ).resolve()
        )
    if config.python_bundled is not None:
        source_candidates.append(
            bundled_python_executable(
                project_root / config.python_bundled.path
            ).resolve()
        )

    destinations: list[str] = []
    resolved_remaps = {
        source.resolve(): destination for source, destination in remap_table.items()
    }
    for source in source_candidates:
        destination = resolved_remaps.get(source)
        if destination is not None:
            destinations.append(destination.as_posix().replace("/", "\\"))
    return destinations


def _installer_bundled_python_path(
    project_root: Path,
    config: AppBuilderConfig,
    remap_table: Mapping[Path, PurePosixPath],
) -> str | None:
    if config.python_bundled is None:
        return None

    bundled_root = (project_root / config.python_bundled.path).resolve()
    source_python = bundled_python_executable(bundled_root).resolve()
    source_config = (bundled_root / "pyvenv.cfg").resolve()
    resolved_remaps = {
        source.resolve(): destination for source, destination in remap_table.items()
    }
    installed_python = resolved_remaps.get(source_python)
    installed_config = resolved_remaps.get(source_config)
    if installed_python is None and installed_config is None:
        return None
    if installed_python is None or installed_config is None:
        raise ValueError(
            "An installed python_bundled runtime must include both its base "
            "python.exe and pyvenv.cfg after remapping."
        )

    installed_root = installed_python.parent.parent
    expected_config = installed_root / "pyvenv.cfg"
    if installed_config.as_posix().casefold() != expected_config.as_posix().casefold():
        raise ValueError(
            "python_bundled remaps must preserve pyvenv.cfg beside the runtime's "
            "python directory."
        )
    return installed_root.as_posix()


def _validate_installer_payload_contract(
    config: AppBuilderConfig,
    remap_table: Mapping[Path, PurePosixPath],
    *,
    start_menu: list[dict[str, str | None]],
    hook_python_candidates: list[str],
) -> None:
    destinations = {
        destination.as_posix().casefold() for destination in remap_table.values()
    }

    def require_payload_path(value: str, *, label: str) -> None:
        try:
            normalized = validate_archive_path(value).as_posix()
        except ValueError as error:
            raise ValueError(
                f"{label} must be a safe install-relative path."
            ) from error
        if normalized.casefold() not in destinations:
            raise FileNotFoundError(
                f"{label} is not present in the final payload after remapping: "
                f"{value!r}."
            )

    for index, (shortcut, manifest_shortcut) in enumerate(
        zip(config.installer.start_menu, start_menu)
    ):
        require_payload_path(
            shortcut.target,
            label=f"installer.start_menu[{index}].target",
        )
        effective_icon = manifest_shortcut["icon"]
        if effective_icon:
            require_payload_path(
                effective_icon,
                label=f"installer.start_menu[{index}].icon",
            )

    automatic_python_hooks = (
        *config.installer.install_hooks.pre_install,
        *config.installer.install_hooks.post_install,
        *config.installer.install_hooks.pre_uninstall,
    )
    if any(
        Path(command[0]).suffix.casefold() == ".py"
        for command in automatic_python_hooks
    ):
        if not hook_python_candidates:
            raise ValueError(
                "Installer .py hooks require a configured python_venv or "
                "python_bundled interpreter that is included in the final payload."
            )


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
    artifacts = list(release.publication_artifacts)
    preflight = run_publication_preflight(
        project_root,
        version=release.version,
        app_name=config.installer.name,
        dist_dir=project_root / config.installer.dist,
        artifacts=artifacts,
        release_outputs=(
            (output.path for output in release.outputs)
            if release.outputs
            else release.publication_artifacts
        ),
        payload_archive=release.payload_archive,
        installer_archive=release.installer_archive,
        manifest_path=release.manifest_path,
        checksums_path=release.checksums_path,
        release_notes_path=release.release_notes_path,
    )
    _run_gh(project_root, gh_executable, ["auth", "status"], check=True)
    repository = _run_gh(
        project_root,
        gh_executable,
        ["repo", "view", "--json", "nameWithOwner", "--jq", ".nameWithOwner"],
        check=True,
    ).stdout.strip()
    if not repository:
        raise RuntimeError("GitHub release preflight could not resolve the repository.")
    remote_tag_exists = _validate_github_tag_target(
        project_root,
        gh_executable,
        repository=repository,
        version=release.version,
        head_commit=preflight.head_commit,
    )
    view_result = _run_gh(
        project_root,
        gh_executable,
        [
            "release",
            "view",
            release.version,
            "--repo",
            repository,
            "--json",
            "url,assets,isDraft,targetCommitish",
        ],
        check=False,
    )
    if view_result.returncode == 0:
        try:
            release_payload = json.loads(view_result.stdout)
        except json.JSONDecodeError as error:
            raise RuntimeError(
                "GitHub release preflight received invalid release metadata."
            ) from error
        html_url = str(release_payload.get("url", "")).strip()
        is_draft = release_payload.get("isDraft")
        target_commitish = release_payload.get("targetCommitish")
        if not isinstance(is_draft, bool) or not isinstance(target_commitish, str):
            raise RuntimeError(
                "GitHub release metadata did not contain a valid draft target."
            )
        if not remote_tag_exists and not is_draft:
            raise RuntimeError(
                "GitHub reports an existing published release without a readable "
                f"tag {release.version!r}."
            )
        expected_asset_names = {artifact.name for artifact in artifacts}
        existing_assets = release_payload.get("assets", [])
        if not isinstance(existing_assets, list):
            raise RuntimeError(
                "GitHub release metadata contained an invalid asset list."
            )
        stale_asset_names = sorted(
            str(asset.get("name"))
            for asset in existing_assets
            if isinstance(asset, dict)
            and isinstance(asset.get("name"), str)
            and asset["name"] not in expected_asset_names
        )
        _run_gh(
            project_root,
            gh_executable,
            [
                "release",
                "upload",
                release.version,
                *(str(artifact) for artifact in artifacts),
                "--clobber",
                "--repo",
                repository,
            ],
            check=True,
        )
        edit_args = [
            "release",
            "edit",
            release.version,
            "--title",
            f"{config.installer.name} {release.version}",
            "--notes-file",
            str(release.release_notes_path),
            "--repo",
            repository,
        ]
        if is_draft and not remote_tag_exists:
            edit_args.extend(["--target", preflight.head_commit])
        _run_gh(
            project_root,
            gh_executable,
            edit_args,
            check=True,
        )
        for asset_name in stale_asset_names:
            _run_gh(
                project_root,
                gh_executable,
                [
                    "release",
                    "delete-asset",
                    release.version,
                    asset_name,
                    "--yes",
                    "--repo",
                    repository,
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
            f"{config.installer.name} {release.version}",
            "--notes-file",
            str(release.release_notes_path),
            "--target",
            preflight.head_commit,
            "--repo",
            repository,
        ]
        if draft:
            create_args.append("--draft")
        _run_gh(project_root, gh_executable, create_args, check=True)
        html_url = _run_gh(
            project_root,
            gh_executable,
            [
                "release",
                "view",
                release.version,
                "--repo",
                repository,
                "--json",
                "url",
                "--jq",
                ".url",
            ],
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


def _validate_github_tag_target(
    project_root: Path,
    gh_executable: str,
    *,
    repository: str,
    version: str,
    head_commit: str,
) -> bool:
    encoded_version = quote(version, safe="")
    result = _run_gh(
        project_root,
        gh_executable,
        ["api", f"repos/{repository}/git/ref/tags/{encoded_version}"],
        check=False,
    )
    if result.returncode != 0:
        if "404" in result.stderr:
            return False
        detail = result.stderr.strip() or result.stdout.strip() or "unknown gh error"
        raise RuntimeError(
            f"GitHub release preflight could not inspect tag {version!r}: {detail}"
        )
    try:
        payload = json.loads(result.stdout)
        target = payload["object"]
        target_type = str(target["type"])
        target_sha = str(target["sha"])
    except (json.JSONDecodeError, KeyError, TypeError) as error:
        raise RuntimeError(
            f"GitHub release preflight received invalid tag metadata for {version!r}."
        ) from error
    if target_type == "tag":
        annotated = _run_gh(
            project_root,
            gh_executable,
            ["api", f"repos/{repository}/git/tags/{target_sha}"],
            check=True,
        )
        try:
            target_sha = str(json.loads(annotated.stdout)["object"]["sha"])
        except (json.JSONDecodeError, KeyError, TypeError) as error:
            raise RuntimeError(
                f"GitHub release preflight received invalid annotated tag metadata for {version!r}."
            ) from error
    if target_sha != head_commit:
        raise RuntimeError(
            f"GitHub release preflight failed: tag {version!r} points to "
            f"{target_sha}, not HEAD {head_commit}."
        )
    return True


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
