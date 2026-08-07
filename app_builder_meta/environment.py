from __future__ import annotations

import difflib
import hashlib
import os
import sys
import urllib.parse
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from functools import cache
from pathlib import Path

_SETTING_VARIABLES = frozenset(
    {
        "APP_BUILDER_CACHE_ROOT",
        "APP_BUILDER_INSTALL_ROOT",
    }
)

# These values are supplied to hooks. They remain valid when a hook invokes
# app-builder recursively, including on case-insensitive Windows environments.
_CONTEXT_VARIABLES = frozenset(
    {
        "APP_BUILDER_INSTALL_DIRECTORY",
        "APP_BUILDER_NAME",
        "APP_BUILDER_PROJECT_ROOT",
        "APP_BUILDER_START_MENU",
        "APP_BUILDER_VERSION",
    }
)

KNOWN_APP_BUILDER_ENVIRONMENT_VARIABLES = _SETTING_VARIABLES | _CONTEXT_VARIABLES


@dataclass(frozen=True, slots=True)
class AppBuilderEnvironment:
    cache_root: Path
    install_root: Path
    pip_cache_dir: Path | None
    poetry_cache_dir: Path | None
    cache_root_is_explicit: bool = False
    install_root_is_explicit: bool = False

    @property
    def downloads(self) -> Path:
        return self.cache_root / "downloads"

    @property
    def versions(self) -> Path:
        return self.cache_root / "versions"

    @property
    def locks(self) -> Path:
        return self.cache_root / "locks"

    def download_path(self, url: str) -> Path:
        parsed = urllib.parse.urlsplit(url)
        filename = Path(parsed.path).name or "download"
        key = hashlib.sha256(url.encode("utf-8")).hexdigest()[:16]
        return self.downloads / key / filename

    def download_lock_path(self, url: str) -> Path:
        key = hashlib.sha256(url.encode("utf-8")).hexdigest()
        return self.locks / "downloads" / f"{key}.lock"

    def subprocess_environment(
        self, environ: Mapping[str, str] | None = None
    ) -> dict[str, str]:
        result = dict(os.environ if environ is None else environ)
        if self.cache_root_is_explicit:
            result["APP_BUILDER_CACHE_ROOT"] = str(self.cache_root)
        if self.install_root_is_explicit:
            result["APP_BUILDER_INSTALL_ROOT"] = str(self.install_root)
        if self.pip_cache_dir is not None:
            result["PIP_CACHE_DIR"] = str(self.pip_cache_dir)
        if self.poetry_cache_dir is not None:
            result["POETRY_CACHE_DIR"] = str(self.poetry_cache_dir)
        return result


def _environment_value(environ: Mapping[str, str], name: str) -> str | None:
    direct = environ.get(name)
    if direct is not None:
        return direct
    folded_name = name.casefold()
    for key, value in environ.items():
        if key.casefold() == folded_name:
            return value
    return None


def _configured_path(environ: Mapping[str, str], name: str) -> Path | None:
    value = _environment_value(environ, name)
    if value is None or not value.strip():
        return None
    return Path(value).expanduser().resolve()


def _default_cache_root(environ: Mapping[str, str]) -> Path:
    if os.name == "nt":
        local_app_data = _environment_value(environ, "LOCALAPPDATA")
        if local_app_data:
            return (Path(local_app_data) / "app-builder" / "cache").resolve()
    xdg_cache = _environment_value(environ, "XDG_CACHE_HOME")
    base = Path(xdg_cache).expanduser() if xdg_cache else Path.home() / ".cache"
    return (base / "app-builder").resolve()


def _emit_warning(message: str) -> None:
    print(f"Warning: {message}", file=sys.stderr)


def _warn_for_unknown_variables(
    environ: Mapping[str, str], warning_sink: Callable[[str], None]
) -> None:
    seen: set[str] = set()
    for raw_name in environ:
        name = raw_name.upper()
        if not name.startswith("APP_BUILDER_") or name in seen:
            continue
        seen.add(name)
        if name in KNOWN_APP_BUILDER_ENVIRONMENT_VARIABLES:
            continue
        suggestion = difflib.get_close_matches(
            name,
            sorted(KNOWN_APP_BUILDER_ENVIRONMENT_VARIABLES),
            n=1,
            cutoff=0.72,
        )
        suffix = f" Did you mean {suggestion[0]}?" if suggestion else ""
        warning_sink(f"unknown app-builder environment variable {raw_name}.{suffix}")


def _read_environment(
    environ: Mapping[str, str],
    *,
    warning_sink: Callable[[str], None] = _emit_warning,
) -> AppBuilderEnvironment:
    _warn_for_unknown_variables(environ, warning_sink)

    configured_cache_root = _configured_path(environ, "APP_BUILDER_CACHE_ROOT")
    configured_install_root = _configured_path(environ, "APP_BUILDER_INSTALL_ROOT")
    cache_root = configured_cache_root or _default_cache_root(environ)
    install_root = configured_install_root or Path(__file__).resolve().parents[1]

    pip_cache_dir = _configured_path(environ, "PIP_CACHE_DIR")
    poetry_cache_dir = _configured_path(environ, "POETRY_CACHE_DIR")
    if configured_cache_root is not None:
        pip_cache_dir = pip_cache_dir or cache_root / "pip"
        poetry_cache_dir = poetry_cache_dir or cache_root / "poetry"

    return AppBuilderEnvironment(
        cache_root=cache_root,
        install_root=install_root,
        pip_cache_dir=pip_cache_dir,
        poetry_cache_dir=poetry_cache_dir,
        cache_root_is_explicit=configured_cache_root is not None,
        install_root_is_explicit=configured_install_root is not None,
    )


@cache
def get_environment() -> AppBuilderEnvironment:
    return _read_environment(os.environ)
