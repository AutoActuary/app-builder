from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, fields, is_dataclass
from pathlib import Path
from typing import Any, TypeAlias, cast

from .schema_core import ConfigError as ConfigError, config_field, materialize_config

HookCommand: TypeAlias = list[str]


@dataclass(slots=True)
class PythonBundledOptions:
    path: str = config_field(
        default="bin/python",
        description="Project-relative directory where the bundled Python runtime is materialized.",
        example="bin/python",
    )
    python_version: str = config_field(
        default="3.11.1",
        description="NuGet Python package version or version prefix to materialize.",
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
        description="NuGet Python package version or version prefix used when the virtual environment is self-contained because python_bundled is disabled.",
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
        description="Argv commands written into installer metadata to run after installation.",
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
class PathsMapping:
    include: list[str] = config_field(
        default_factory=list,
        description="Project-relative files or globs included in the release payload.",
        example_factory=lambda: ["src", "app_builder.yaml", "application-templates"],
    )
    exclude: list[str] = config_field(
        default_factory=list,
        description="Project-relative files or globs excluded from the release payload.",
        example_factory=lambda: ["**/__pycache__", "dist", "venv"],
    )
    remap: list[tuple[str, str]] = config_field(
        default_factory=list,
        description="Two-item source and destination pairs for relocating payload files.",
        example_factory=lambda: [("README.md", "docs/README.md")],
    )


@dataclass(slots=True)
class StartMenuShortcut:
    target: str = config_field(
        description="Project-relative command or file launched by the shortcut.",
        example="application-templates/program.cmd",
    )
    display_name: str | None = config_field(
        default=None,
        description="Shortcut display name. Defaults to the installer name when omitted by downstream tooling.",
        example="MyApp",
    )
    icon: str | None = config_field(
        default=None,
        description="Project-relative icon path for the shortcut.",
        example="application-templates/icon.ico",
    )


@dataclass(slots=True)
class InstallerOptions:
    name: str = config_field(
        description="Human-facing application name.",
        example="MyApp",
    )
    install_directory: str = config_field(
        description="Windows install directory. Percent-style environment variables are expanded at build time.",
        example=r"%localappdata%\MyCompany\MyApp",
    )
    icon: str = config_field(
        default="application-templates/icon.ico",
        description="Project-relative default icon used for Start Menu shortcuts when a shortcut does not specify its own icon.",
        example="application-templates/icon.ico",
    )
    pause_on_exit: bool = config_field(
        default=True,
        description="Whether generated installer scripts should pause before exiting.",
        example=True,
    )
    add_uninstaller: bool = config_field(
        default=True,
        description="Whether the installer bundle should include an uninstall script.",
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
    install_hooks: InstallHooks = config_field(
        default_factory=InstallHooks,
        description="Installer and uninstaller hook command declarations.",
    )
    dist: str = config_field(
        default="dist",
        description="Project-relative output directory for release artifacts.",
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
        description="Argv commands run after the release payload is assembled.",
    )
    pre_github_release: list[HookCommand] = config_field(
        default_factory=list,
        description="Argv commands run before GitHub release upload.",
    )
    post_github_release: list[HookCommand] = config_field(
        default_factory=list,
        description="Argv commands run after GitHub release upload.",
    )
    post_process: list[HookCommand] = config_field(
        default_factory=list,
        description="Argv commands run at the end of release processing.",
    )


@dataclass(slots=True, kw_only=True)
class AppBuilderConfig:
    app_builder_version: str | None = config_field(
        default="current",
        description="Version selector read by the meta CLI before loading the full config. Use current for the installed 1.x app-builder; explicit 1.x tags, branches, or commits are resolved through the managed version cache. Use the command line form app-builder 0.x for legacy 0.x projects.",
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
    return materialize_config(AppBuilderConfig, value, path=path)


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
