from __future__ import annotations

import json
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Any


def resolve_app_builder_version(package_dir: Path | None = None) -> str:
    package_root = package_dir or Path(__file__).resolve().parent
    installed_version = _installed_manifest_version(package_root.parent)
    if installed_version is not None:
        return installed_version
    try:
        return version("app-builder")
    except PackageNotFoundError:
        return "0.0.0-dev"


def _installed_manifest_version(install_root: Path) -> str | None:
    manifest_path = install_root / "app-builder-manifest.json"
    if not manifest_path.is_file():
        return None
    try:
        payload: Any = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    name = payload.get("name")
    installed_version = payload.get("version")
    if not isinstance(name, str) or _identity_key(name) != "appbuilder":
        return None
    if not isinstance(installed_version, str) or not installed_version.strip():
        return None
    return installed_version.strip()


def _identity_key(value: str) -> str:
    return "".join(character for character in value.casefold() if character.isalnum())
