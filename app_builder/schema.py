from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass, fields, is_dataclass
from pathlib import Path
from typing import Any, TypeAlias, cast

from .schema_core import ConfigError as ConfigError, config_field, materialize_config

HookCommand: TypeAlias = list[str]
_PYTHON_VERSION_SELECTOR = re.compile(
    r"^[0-9]+\.[0-9]+\.[0-9]+"
    r"(?:(?:a|b|rc)[0-9]+|-(?:alpha|beta|candidate|rc)(?:[.-]?[0-9]+)?)?$",
    re.IGNORECASE,
)


@dataclass(slots=True)
class PythonBundledOptions:
    path: str = config_field(
        default="bin/python",
        description="Project-relative directory where the bundled Python runtime is materialized.",
        example="bin/python",
    )
    python_version: str = config_field(
        default="3.11.1",
        description="Python.org Windows runtime version to materialize. Use major.minor.patch for a stable release; prereleases accept forms such as 3.15.0b4 or 3.15.0-beta.",
        example="3.12.10",
    )


@dataclass(slots=True)
class PythonVenvOptions:
    path: str = config_field(
        default="venv",
        description="Project-relative directory where the Poetry dev virtual environment is created.",
        example="venv",
    )
    python_version: str = config_field(
        default="3.11.1",
        description="Python.org Windows runtime version used when the virtual environment is self-contained because python_bundled is disabled. Prerelease selectors are supported.",
        example="3.12.10",
    )


@dataclass(slots=True)
class InstallHooks:
    pre_install: list[HookCommand] = config_field(
        default_factory=list,
        description="Argv commands written into installer metadata to run before installation.",
    )
    post_install: list[HookCommand] = config_field(
        default_factory=list,
        description="Argv commands written into installer metadata to run after payload files, shortcuts, uninstall support, and Windows Installed Apps registration are complete.",
    )
    pre_uninstall: list[HookCommand] = config_field(
        default_factory=list,
        description="Argv commands written into installer metadata to run before uninstall while the installed app directory is still present.",
    )
    post_uninstall: list[HookCommand] = config_field(
        default_factory=list,
        description="Argv commands written into installer metadata to run after the install directory has been removed. Entrypoints inside the install directory must be self-contained .cmd, .ps1, or .exe files because app-builder stages only argv[0] to temp before removal.",
    )


@dataclass(slots=True)
class BootstrapHooks:
    pre_extract: list[HookCommand] = config_field(
        default_factory=list,
        description="Argv commands run before the installer extracts its top layer. These commands cannot use payload files, installer scripts, or bundled top-layer tools because none have been extracted yet.",
    )


@dataclass(slots=True)
class PathsMapping:
    include: list[str] = config_field(
        default_factory=list,
        description="Required project-relative files or globs included in the release payload. Every entry must match, and the final payload must be nonempty after excludes.",
        example_factory=lambda: [
            "app_builder.yaml",
            "application-templates",
            "bin/python",
        ],
    )
    exclude: list[str] = config_field(
        default_factory=list,
        description="Project-relative files or globs removed from the selected payload.",
        example_factory=lambda: ["**/__pycache__", "dist", "venv"],
    )
    include_dist: bool = config_field(
        default=False,
        description="Whether files beneath installer.dist may enter the application payload. The default excludes dist even when a broad include selects the project root, preventing old release files and build logs from being installed.",
        example=False,
    )
    remap: list[tuple[str, str]] = config_field(
        default_factory=list,
        description="Two-item source and archive-destination pairs. Each source must be a selected literal project-relative path; destinations must be safe, unique archive paths.",
        example_factory=lambda: [("README.md", "docs/README.md")],
    )


@dataclass(slots=True)
class StartMenuShortcut:
    target: str = config_field(
        description="Install-relative command or file launched by the shortcut. The target must be present at that payload path after remapping.",
        example="application-templates/program.cmd",
    )
    display_name: str | None = config_field(
        default=None,
        description="Shortcut display name. Defaults to the installer name when omitted by downstream tooling.",
        example="MyApp",
    )
    icon: str | None = config_field(
        default=None,
        description="Optional install-relative shortcut icon path. The icon must be present at that payload path after remapping; when omitted, installer.icon is used.",
        example="application-templates/icon.ico",
    )


@dataclass(slots=True)
class InstallerOptions:
    name: str = config_field(
        description="Human-facing application name and Windows install identity. It must be a trimmed, filename-safe, non-reserved Windows name.",
        example="MyApp",
    )
    install_directory: str = config_field(
        description="Windows install directory. A variable-root path must start with %LOCALAPPDATA%, %APPDATA%, or %USERPROFILE% and name an application subdirectory; the installer expands it on the user's machine. A fixed absolute path is also allowed when it is not a drive root or protected Windows directory.",
        example=r"%LOCALAPPDATA%\MyCompany\MyApp",
    )
    icon: str = config_field(
        default="application-templates/icon.ico",
        description="Project-relative .ico file embedded into generated executables. It is also the default install-relative Start Menu icon path, so include it at the same payload path or override the shortcut icon.",
        example="application-templates/icon.ico",
    )
    payload_format: str = config_field(
        default="zip",
        description="Inner payload archive format. Use zip for the Windows tar.exe path or 7z for stronger compression with bundled 7-Zip extraction.",
        example="zip",
    )
    wait_on_exit: bool = config_field(
        default=True,
        description="Whether generated installer scripts should wait briefly before exiting. The wait closes after 30 seconds or Enter; --yes skips prompts and the wait, while --no-wait skips only the wait.",
        example=True,
    )
    add_uninstaller: bool = config_field(
        default=True,
        description="Whether installation adds the installed uninstall scripts, Start Menu uninstall shortcut, and per-user Windows Installed Apps registration.",
        example=True,
    )
    start_menu: list[StartMenuShortcut] = config_field(
        default_factory=list,
        description="Windows Start Menu shortcut declarations.",
        example_factory=lambda: [
            {
                "target": "application-templates/program.cmd",
                "display_name": "MyApp",
                "icon": "application-templates/icon.ico",
            }
        ],
    )
    bootstrap_hooks: BootstrapHooks = config_field(
        default_factory=BootstrapHooks,
        description="Early installer hook command declarations.",
    )
    install_hooks: InstallHooks = config_field(
        default_factory=InstallHooks,
        description="Installer and uninstaller hook command declarations.",
    )
    dist: str = config_field(
        default="dist",
        description="Project-relative subdirectory inside the project where release artifacts and build logs are written.",
        example="dist",
    )
    paths: PathsMapping = config_field(
        default_factory=PathsMapping,
        description="Payload include, exclude, and remap rules.",
    )


@dataclass(slots=True)
class BuildHooks:
    pre_process: list[HookCommand] = config_field(
        default_factory=list,
        description="Argv commands run before dependency or release processing begins.",
    )
    pre_python_bundled: list[HookCommand] = config_field(
        default_factory=list,
        description="Argv commands run before bundled Python is materialized.",
    )
    post_python_bundled: list[HookCommand] = config_field(
        default_factory=list,
        description="Argv commands run after bundled Python is materialized.",
    )
    pre_python_venv: list[HookCommand] = config_field(
        default_factory=list,
        description="Argv commands run before the virtual environment is materialized.",
    )
    post_python_venv: list[HookCommand] = config_field(
        default_factory=list,
        description="Argv commands run after the virtual environment is materialized.",
    )
    pre_dist: list[HookCommand] = config_field(
        default_factory=list,
        description="Argv commands run before the release payload is assembled.",
    )
    post_dist: list[HookCommand] = config_field(
        default_factory=list,
        description="Argv commands run after installer assembly and stale named-output candidates are cleared, but before output collection, checksums, and release notes. This stage may create extra outputs or sign the installer; it must not modify the sealed payload or manifest.",
    )
    pre_github_release: list[HookCommand] = config_field(
        default_factory=list,
        description="Argv commands run before GitHub release upload.",
    )
    post_github_release: list[HookCommand] = config_field(
        default_factory=list,
        description="Argv commands run after GitHub release upload.",
    )


@dataclass(slots=True)
class ReleaseOutputSpec:
    name: str = config_field(
        description="Unique logical name used by publication targets. Built-in names such as payload, installer, manifest, and checksums are reserved.",
        example="wheels",
    )
    pattern: str = config_field(
        description="Exact path or non-recursive glob relative to installer.dist. Wildcards are allowed only in the filename segment.",
        example="wheels/*.whl",
    )
    min_matches: int = config_field(
        default=1,
        description="Minimum number of files the pattern must resolve; must be zero or greater.",
        example=1,
    )
    max_matches: int | None = config_field(
        default=1,
        description="Maximum number of files the pattern may resolve. It must be at least min_matches; set to null for no upper bound.",
        example=None,
    )


@dataclass(slots=True)
class GitHubPublication:
    outputs: list[str] = config_field(
        default_factory=lambda: ["payload", "installer", "manifest", "checksums"],
        description="Exact logical output names uploaded to the GitHub release. A configured name expands to every matched file; unknown names and case-insensitive upload filename collisions are rejected.",
    )


@dataclass(slots=True)
class Publications:
    github: GitHubPublication = config_field(
        default_factory=GitHubPublication,
        description="GitHub release publication settings.",
    )


@dataclass(slots=True, kw_only=True)
class AppBuilderConfig:
    app_builder_version: str | None = config_field(
        default="current",
        description="Literal version selector read by the app-builder launcher before config interpolation. Use current for the installed 1.x version; explicit 1.x tags, branches, or commits use the managed version cache. Use app-builder 0.x for legacy projects.",
        example="current",
    )
    python_bundled: PythonBundledOptions | None = config_field(
        default_factory=PythonBundledOptions,
        description="Optional bundled Python runtime. Set to null to disable.",
    )
    python_venv: PythonVenvOptions | None = config_field(
        default_factory=PythonVenvOptions,
        description="Optional Poetry dev virtual environment derived from bundled Python when available. Set to null to disable.",
    )
    installer: InstallerOptions = config_field(
        description="Required installer metadata and release payload settings.",
    )
    build_hooks: BuildHooks = config_field(
        default_factory=BuildHooks,
        description="Build and release hook command declarations.",
    )
    outputs: list[ReleaseOutputSpec] = config_field(
        default_factory=list,
        description="Named release output collections produced by hooks or other project build steps and picked up from installer.dist.",
    )
    publications: Publications = config_field(
        default_factory=Publications,
        description="Explicit publication output selections.",
    )

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "AppBuilderConfig":
        return load_app_builder_config(value)

    def to_dict(self) -> dict[str, Any]:
        return cast(dict[str, Any], _dataclass_to_dict(self))


def load_app_builder_config(
    value: Mapping[str, Any],
    *,
    path: str = "config",
) -> AppBuilderConfig:
    if _looks_like_legacy_config(value):
        raise ConfigError(
            path,
            "legacy application.yaml layout is not supported. Expected app_builder.yaml 1.x keys such as 'installer', 'python_bundled', and 'build_hooks'.",
        )
    config = materialize_config(AppBuilderConfig, value, path=path)
    if config.installer.payload_format not in {"zip", "7z"}:
        raise ConfigError(
            f"{path}.installer.payload_format",
            "expected one of: 'zip', '7z'.",
        )
    for section_name, options in (
        ("python_bundled", config.python_bundled),
        ("python_venv", config.python_venv),
    ):
        if (
            options is not None
            and _PYTHON_VERSION_SELECTOR.fullmatch(options.python_version) is None
        ):
            raise ConfigError(
                f"{path}.{section_name}.python_version",
                "expected major.minor.patch, optionally followed by a Python prerelease such as b4, rc1, or -beta.",
            )
    return config


def _looks_like_legacy_config(value: Mapping[str, Any]) -> bool:
    string_keys = {key.lower() for key in value if isinstance(key, str)}
    return bool(
        string_keys.intersection(
            {
                "application",
                "dependencies",
                "app-builder",
                "app_builder",
            }
        )
    )


def _dataclass_to_dict(value: Any) -> Any:
    if is_dataclass(value):
        result: dict[str, Any] = {}
        for field_ in fields(value):
            result[field_.name] = _dataclass_to_dict(getattr(value, field_.name))
        return result
    if isinstance(value, Path):
        return value.as_posix()
    if isinstance(value, list):
        return [_dataclass_to_dict(item) for item in value]
    if isinstance(value, tuple):
        return [_dataclass_to_dict(item) for item in value]
    return value
