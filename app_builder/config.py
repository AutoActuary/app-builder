from __future__ import annotations

from pathlib import Path

import yaml

from .config_interpolation import interpolate_config
from .schema import AppBuilderConfig, ConfigError, load_app_builder_config

CONFIG_FILENAMES = ("app_builder.yaml", "app-builder.yaml")


def load_config(
    config_path: Path, *, app_version: str | None = None
) -> AppBuilderConfig:
    raw = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    if not isinstance(raw, dict):
        raise ConfigError(
            "config",
            f"expected mapping at the top level of {config_path.name}, got {type(raw).__name__}.",
        )
    resolved = interpolate_config(
        raw,
        project_root=config_path.parent,
        app_version=app_version,
    )
    return load_app_builder_config(resolved)


def find_config_path(project_root: Path) -> Path:
    for filename in CONFIG_FILENAMES:
        path = project_root / filename
        if path.exists():
            return path
    raise FileNotFoundError(
        f"Could not find any config file in {project_root}. Expected one of: {', '.join(CONFIG_FILENAMES)}."
    )


def load_project_config(
    project_root: Path,
    *,
    app_version: str | None = None,
) -> tuple[Path, AppBuilderConfig]:
    path = find_config_path(project_root)
    return path, load_config(path, app_version=app_version)
