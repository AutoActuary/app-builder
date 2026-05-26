from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

CONFIG_FILENAMES = ("app_builder.yaml", "app-builder.yaml")
LEGACY_CONFIG_FILENAMES = ("application.yaml",)


class ConfigProbeError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class ConfigProbe:
    path: Path
    app_builder_version: str | None


def find_nearest_config(start: Path, filenames: tuple[str, ...]) -> Path | None:
    current = start.resolve()
    while True:
        for filename in filenames:
            candidate = current / filename
            if candidate.is_file():
                return candidate
        if current.parent == current:
            return None
        current = current.parent


def read_plain_yaml_version(config_path: Path) -> str | None:
    try:
        raw = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as error:
        raise ConfigProbeError(f"{config_path}: could not parse YAML: {error}") from error
    except OSError as error:
        raise ConfigProbeError(f"{config_path}: could not read config: {error}") from error

    if not isinstance(raw, dict):
        raise ConfigProbeError(
            f"{config_path}: expected a YAML mapping at the top level."
        )

    version = raw.get("app_builder_version")
    if version is None:
        return None
    if not isinstance(version, str):
        raise ConfigProbeError(
            f"{config_path}: app_builder_version must be a string when present."
        )
    return version.strip()


def probe_project_config(start: Path) -> ConfigProbe | None:
    config_path = find_nearest_config(start, CONFIG_FILENAMES)
    if config_path is None:
        return None
    return ConfigProbe(config_path, read_plain_yaml_version(config_path))


def legacy_config_path(start: Path) -> Path | None:
    return find_nearest_config(start, LEGACY_CONFIG_FILENAMES)


def is_legacy_version(version: str) -> bool:
    normalized = version.strip().lower()
    return normalized == "0.x" or normalized.startswith("v0.") or normalized.startswith(
        "0."
    )


def is_current_version(version: str | None) -> bool:
    if version is None:
        return True
    return version.strip().lower() in {"", "current"}

