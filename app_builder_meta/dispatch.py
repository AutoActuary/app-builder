from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path

from .config_probe import (
    ConfigProbeError,
    is_current_version,
    is_legacy_version,
    legacy_config_path,
    probe_project_config,
)
from .legacy_0x import run_legacy_bridge
from .version_cache import default_install_root, run_managed_version


@dataclass(frozen=True, slots=True)
class CurrentInstall:
    argv: list[str]


@dataclass(frozen=True, slots=True)
class Managed1xVersion:
    ref: str
    argv: list[str]


@dataclass(frozen=True, slots=True)
class Legacy0x:
    argv: list[str]


@dataclass(frozen=True, slots=True)
class LegacyConfigErrorTarget:
    path: Path


@dataclass(frozen=True, slots=True)
class LegacyVersionErrorTarget:
    version: str


Target = (
    CurrentInstall
    | Managed1xVersion
    | Legacy0x
    | LegacyConfigErrorTarget
    | LegacyVersionErrorTarget
)


class MetaDispatchError(RuntimeError):
    pass


def dispatch(argv: list[str], *, cwd: Path | None = None) -> int:
    active_cwd = (cwd or Path.cwd()).resolve()
    try:
        target = choose_target(argv, active_cwd)
        return run_target(target, cwd=active_cwd)
    except (ConfigProbeError, MetaDispatchError, RuntimeError) as error:
        print(str(error), file=sys.stderr)
        return 2


def choose_target(argv: list[str], cwd: Path) -> Target:
    if argv[:1] == ["0.x"]:
        return Legacy0x(argv=argv[1:])

    probe = probe_project_config(cwd)
    if probe is None:
        legacy_path = legacy_config_path(cwd)
        if legacy_path is not None:
            return LegacyConfigErrorTarget(path=legacy_path)
        return CurrentInstall(argv=argv)

    version = probe.app_builder_version
    if is_current_version(version):
        return CurrentInstall(argv=argv)
    assert version is not None
    if is_legacy_version(version):
        return LegacyVersionErrorTarget(version=version)
    return Managed1xVersion(ref=version, argv=argv)


def run_target(target: Target, *, cwd: Path) -> int:
    if isinstance(target, CurrentInstall):
        return _run_current(target.argv)
    if isinstance(target, Managed1xVersion):
        return run_managed_version(target.ref, target.argv, cwd=cwd)
    if isinstance(target, Legacy0x):
        return run_legacy_bridge(
            target.argv, cwd=cwd, install_root=default_install_root()
        )
    if isinstance(target, LegacyConfigErrorTarget):
        raise MetaDispatchError(
            "Legacy app-builder config detected: "
            f"{target.path}\n\n"
            "This 1.x launcher does not automatically run legacy projects.\n"
            "Use:\n"
            "  app-builder 0.x <command>\n\n"
            "To migrate, create app_builder.yaml and remove application.yaml when ready."
        )
    if isinstance(target, LegacyVersionErrorTarget):
        raise MetaDispatchError(
            f"app_builder_version: {target.version} is not valid in app_builder.yaml.\n"
            "Use:\n"
            "  app-builder 0.x <command>"
        )
    raise AssertionError(f"Unhandled dispatch target: {target!r}")


def _run_current(argv: list[str]) -> int:
    import click

    from app_builder.main import main as app_builder_main

    try:
        result = app_builder_main.main(
            args=argv,
            prog_name="app-builder",
            standalone_mode=False,
        )
    except click.ClickException as error:
        error.show()
        return error.exit_code
    return int(result or 0)
