from __future__ import annotations

from dataclasses import dataclass, field, fields, is_dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence, cast


class ConfigError(ValueError):
    pass


def _ensure_mapping(value: Any, *, field_name: str) -> Mapping[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, Mapping):
        raise ConfigError(
            f"Expected '{field_name}' to be a mapping, got {type(value).__name__}."
        )
    return value


def _ensure_list_of_strings(value: Any, *, field_name: str) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise ConfigError(f"Expected '{field_name}' to be a list of strings.")
    result: list[str] = []
    for item in value:
        if not isinstance(item, str):
            raise ConfigError(
                f"Expected '{field_name}' entries to be strings, got {type(item).__name__}."
            )
        result.append(item)
    return result


def _ensure_bool(value: Any, *, field_name: str, default: bool) -> bool:
    if value is None:
        return default
    if not isinstance(value, bool):
        raise ConfigError(
            f"Expected '{field_name}' to be a bool, got {type(value).__name__}."
        )
    return value


def _ensure_string(
    value: Any, *, field_name: str, default: str | None = None
) -> str | None:
    if value is None:
        return default
    if not isinstance(value, str):
        raise ConfigError(
            f"Expected '{field_name}' to be a string, got {type(value).__name__}."
        )
    return value


@dataclass(slots=True)
class PythonBundledOptions:
    path: str = "bin/python"
    python_version: str = "3.11.1"
    pip_version: str = "23.2.1"
    requirements: list[str] = field(default_factory=list)
    requirements_files: list[str] = field(default_factory=list)

    @classmethod
    def from_mapping(cls, value: Any) -> "PythonBundledOptions | None":
        if value is None:
            return None
        data = _ensure_mapping(value, field_name="python_bundled")
        return cls(
            path=_ensure_string(
                data.get("path"), field_name="python_bundled.path", default="bin/python"
            )
            or "bin/python",
            python_version=_ensure_string(
                data.get("python_version"),
                field_name="python_bundled.python_version",
                default="3.11.1",
            )
            or "3.11.1",
            pip_version=_ensure_string(
                data.get("pip_version"),
                field_name="python_bundled.pip_version",
                default="23.2.1",
            )
            or "23.2.1",
            requirements=_ensure_list_of_strings(
                data.get("requirements"),
                field_name="python_bundled.requirements",
            ),
            requirements_files=_ensure_list_of_strings(
                data.get("requirements_files"),
                field_name="python_bundled.requirements_files",
            ),
        )


@dataclass(slots=True)
class PythonVenvOptions:
    path: str = "venv"
    requirements: list[str] = field(default_factory=list)
    requirements_files: list[str] = field(default_factory=list)

    @classmethod
    def from_mapping(cls, value: Any) -> "PythonVenvOptions | None":
        if value is None:
            return None
        data = _ensure_mapping(value, field_name="python_venv")
        return cls(
            path=_ensure_string(
                data.get("path"), field_name="python_venv.path", default="venv"
            )
            or "venv",
            requirements=_ensure_list_of_strings(
                data.get("requirements"), field_name="python_venv.requirements"
            ),
            requirements_files=_ensure_list_of_strings(
                data.get("requirements_files"),
                field_name="python_venv.requirements_files",
            ),
        )


@dataclass(slots=True)
class InstallHooks:
    pre_install: list[str] = field(default_factory=list)
    post_install: list[str] = field(default_factory=list)
    pre_uninstall: list[str] = field(default_factory=list)
    post_uninstall: list[str] = field(default_factory=list)

    @classmethod
    def from_mapping(cls, value: Any) -> "InstallHooks":
        data = _ensure_mapping(value, field_name="installer.install_hooks")
        return cls(
            pre_install=_ensure_list_of_strings(
                data.get("pre_install"),
                field_name="installer.install_hooks.pre_install",
            ),
            post_install=_ensure_list_of_strings(
                data.get("post_install"),
                field_name="installer.install_hooks.post_install",
            ),
            pre_uninstall=_ensure_list_of_strings(
                data.get("pre_uninstall"),
                field_name="installer.install_hooks.pre_uninstall",
            ),
            post_uninstall=_ensure_list_of_strings(
                data.get("post_uninstall"),
                field_name="installer.install_hooks.post_uninstall",
            ),
        )


@dataclass(slots=True)
class PathsMapping:
    include: list[str] = field(default_factory=list)
    exclude: list[str] = field(default_factory=list)
    remap: list[tuple[str, str]] = field(default_factory=list)

    @classmethod
    def from_mapping(cls, value: Any) -> "PathsMapping":
        data = _ensure_mapping(value, field_name="installer.paths")
        remap_value = data.get("remap") or []
        remap: list[tuple[str, str]] = []
        if not isinstance(remap_value, Sequence) or isinstance(
            remap_value, (str, bytes)
        ):
            raise ConfigError(
                "Expected 'installer.paths.remap' to be a list of [src, dst] pairs."
            )
        for item in remap_value:
            if (
                not isinstance(item, Sequence)
                or isinstance(item, (str, bytes))
                or len(item) != 2
                or not all(isinstance(part, str) for part in item)
            ):
                raise ConfigError(
                    "Each 'installer.paths.remap' item must be a two-item string pair."
                )
            remap.append((item[0], item[1]))
        return cls(
            include=_ensure_list_of_strings(
                data.get("include"), field_name="installer.paths.include"
            ),
            exclude=_ensure_list_of_strings(
                data.get("exclude"), field_name="installer.paths.exclude"
            ),
            remap=remap,
        )


@dataclass(slots=True)
class StartMenuShortcut:
    target: str
    display_name: str | None = None
    icon: str | None = None

    @classmethod
    def from_value(cls, value: Any, *, field_name: str) -> "StartMenuShortcut":
        if isinstance(value, str):
            return cls(target=value)
        if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
            items = list(value)
            if len(items) not in (2, 3) or not all(
                isinstance(item, str) for item in items
            ):
                raise ConfigError(
                    f"Expected '{field_name}' items to be strings or [target, name, optional icon]."
                )
            return cls(
                target=items[0],
                display_name=items[1],
                icon=items[2] if len(items) == 3 else None,
            )
        raise ConfigError(
            f"Expected '{field_name}' items to be strings or [target, name, optional icon]."
        )


@dataclass(slots=True)
class InstallerOptions:
    name: str
    install_directory: str
    ascii_banner: str = "application-templates/asciibanner.txt"
    icon: str = "application-templates/icon.ico"
    pause_on_exit: bool = True
    add_uninstaller: bool = True
    start_menu: list[StartMenuShortcut] = field(default_factory=list)
    install_hooks: InstallHooks = field(default_factory=InstallHooks)
    dist: str = "dist"
    paths: PathsMapping = field(default_factory=PathsMapping)

    @classmethod
    def from_mapping(cls, value: Any) -> "InstallerOptions":
        data = _ensure_mapping(value, field_name="installer")
        name = _ensure_string(data.get("name"), field_name="installer.name")
        if not name:
            raise ConfigError("Expected 'installer.name' to be set.")
        install_directory = _ensure_string(
            data.get("install_directory"),
            field_name="installer.install_directory",
        )
        if not install_directory:
            raise ConfigError("Expected 'installer.install_directory' to be set.")
        start_menu_value = data.get("start_menu") or []
        if not isinstance(start_menu_value, Sequence) or isinstance(
            start_menu_value, (str, bytes)
        ):
            raise ConfigError("Expected 'installer.start_menu' to be a list.")
        start_menu = [
            StartMenuShortcut.from_value(item, field_name="installer.start_menu")
            for item in start_menu_value
        ]
        return cls(
            name=name,
            install_directory=install_directory,
            ascii_banner=_ensure_string(
                data.get("ascii_banner"),
                field_name="installer.ascii_banner",
                default="application-templates/asciibanner.txt",
            )
            or "application-templates/asciibanner.txt",
            icon=_ensure_string(
                data.get("icon"),
                field_name="installer.icon",
                default="application-templates/icon.ico",
            )
            or "application-templates/icon.ico",
            pause_on_exit=_ensure_bool(
                data.get("pause_on_exit"),
                field_name="installer.pause_on_exit",
                default=True,
            ),
            add_uninstaller=_ensure_bool(
                data.get("add_uninstaller"),
                field_name="installer.add_uninstaller",
                default=True,
            ),
            start_menu=start_menu,
            install_hooks=InstallHooks.from_mapping(data.get("install_hooks")),
            dist=_ensure_string(
                data.get("dist"), field_name="installer.dist", default="dist"
            )
            or "dist",
            paths=PathsMapping.from_mapping(data.get("paths")),
        )


@dataclass(slots=True)
class BuildHooks:
    pre_process: list[str] = field(default_factory=list)
    pre_python_bundled: list[str] = field(default_factory=list)
    post_python_bundled: list[str] = field(default_factory=list)
    pre_python_venv: list[str] = field(default_factory=list)
    post_python_venv: list[str] = field(default_factory=list)
    pre_dist: list[str] = field(default_factory=list)
    post_dist: list[str] = field(default_factory=list)
    pre_github_release: list[str] = field(default_factory=list)
    post_github_release: list[str] = field(default_factory=list)
    post_process: list[str] = field(default_factory=list)

    @classmethod
    def from_mapping(cls, value: Any) -> "BuildHooks":
        data = _ensure_mapping(value, field_name="build_hooks")
        kwargs = {
            field_.name: _ensure_list_of_strings(
                data.get(field_.name), field_name=f"build_hooks.{field_.name}"
            )
            for field_ in fields(cls)
        }
        return cls(**kwargs)


@dataclass(slots=True)
class AppBuilderConfig:
    app_builder_version: str | None = "v1.0.0"
    python_bundled: PythonBundledOptions | None = field(
        default_factory=PythonBundledOptions
    )
    python_venv: PythonVenvOptions | None = field(default_factory=PythonVenvOptions)
    installer: InstallerOptions = field(
        default_factory=lambda: InstallerOptions(
            name="MyApp",
            install_directory=r"%localappdata%\MyCompany\MyApp",
        )
    )
    build_hooks: BuildHooks = field(default_factory=BuildHooks)

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "AppBuilderConfig":
        if "application" in value or "dependencies" in value:
            raise ConfigError(
                "This looks like a legacy application.yaml file. app-builder 1.x expects 'app_builder.yaml'."
            )
        return cls(
            app_builder_version=_ensure_string(
                value.get("app_builder_version"),
                field_name="app_builder_version",
                default="v1.0.0",
            ),
            python_bundled=PythonBundledOptions.from_mapping(
                value.get("python_bundled")
            ),
            python_venv=PythonVenvOptions.from_mapping(value.get("python_venv")),
            installer=InstallerOptions.from_mapping(value.get("installer") or {}),
            build_hooks=BuildHooks.from_mapping(value.get("build_hooks")),
        )

    def to_dict(self) -> dict[str, Any]:
        return cast(dict[str, Any], _dataclass_to_dict(self))


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
