"""Keep distlib entry points relative to app-builder's Python runtimes."""

from __future__ import annotations

import importlib.machinery
import os
import sys
import sysconfig
import time
from pathlib import Path
from types import ModuleType
from typing import Any, cast

_DISTLIB_SCRIPT_MODULE = "pip._vendor.distlib.scripts"
_RELATIVE_LAUNCHER_PREFIX = "<launcher_dir>\\"
_WINDOWS_RETRY_DELAYS = (0.05, 0.1, 0.2, 0.4, 0.8)


def _scripts_directory() -> Path:
    return Path(sysconfig.get_path("scripts"))


def _relative_launcher_executable() -> str:
    scripts_directory = _scripts_directory().resolve()
    sibling_python = scripts_directory / "python.exe"
    if sibling_python.is_file():
        relative_python = sibling_python.name
    else:
        executable = Path(sys.executable).resolve()
        prefix = Path(sys.prefix).resolve()
        try:
            executable.relative_to(prefix)
        except ValueError as error:
            raise RuntimeError(
                f"Python executable {executable} is outside its runtime {prefix}."
            ) from error
        relative_python = os.path.relpath(executable, scripts_directory)
    return _RELATIVE_LAUNCHER_PREFIX + relative_python.replace("/", "\\")


def _patch_script_maker(module: ModuleType) -> None:
    script_maker = getattr(module, "ScriptMaker", None)
    if script_maker is None:
        raise RuntimeError(f"{module.__name__} does not expose ScriptMaker.")
    script_maker.executable = _relative_launcher_executable()


class _PatchedLoader:
    def __init__(self, loader: Any) -> None:
        self._loader = loader

    def create_module(self, spec: Any) -> ModuleType | None:
        create_module = getattr(self._loader, "create_module", None)
        return create_module(spec) if create_module is not None else None

    def exec_module(self, module: ModuleType) -> None:
        self._loader.exec_module(module)
        _patch_script_maker(module)


class _DistlibScriptFinder:
    def find_spec(
        self, fullname: str, path: Any = None, target: ModuleType | None = None
    ) -> Any:
        if fullname != _DISTLIB_SCRIPT_MODULE:
            return None
        spec = importlib.machinery.PathFinder.find_spec(fullname, path)
        if spec is None or spec.loader is None:
            return spec
        spec.loader = cast(Any, _PatchedLoader(spec.loader))
        return spec


def install_import_hook() -> None:
    if os.name != "nt":
        return
    module = sys.modules.get(_DISTLIB_SCRIPT_MODULE)
    if isinstance(module, ModuleType):
        _patch_script_maker(module)
    if not any(isinstance(finder, _DistlibScriptFinder) for finder in sys.meta_path):
        sys.meta_path.insert(0, _DistlibScriptFinder())


def _known_distlib_launchers() -> tuple[tuple[bytes, bool], ...]:
    try:
        from pip._vendor.distlib.scripts import WRAPPERS
    except (ImportError, ModuleNotFoundError):
        return ()

    return tuple(
        sorted(
            (
                (cast(bytes, wrapper), name.startswith("w"))
                for name, wrapper in WRAPPERS.items()
            ),
            key=lambda item: len(item[0]),
            reverse=True,
        )
    )


def _replace_file(path: Path, payload: bytes) -> None:
    temporary = path.with_name(f".{path.name}.app-builder-{os.getpid()}.tmp")
    try:
        temporary.write_bytes(payload)
        _replace_with_retry(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _replace_with_retry(source: Path, destination: Path) -> None:
    for delay in (*_WINDOWS_RETRY_DELAYS, None):
        try:
            os.replace(source, destination)
            return
        except OSError as error:
            if (
                os.name != "nt"
                or getattr(error, "winerror", None) not in {5, 32}
                or delay is None
            ):
                raise
            time.sleep(delay)


def heal_existing_launchers() -> None:
    if os.name != "nt":
        return
    scripts_directory = _scripts_directory()
    relative_python: str | None = None
    known_launchers = _known_distlib_launchers()
    for executable in scripts_directory.glob("*.exe"):
        payload = executable.read_bytes()
        matched = next(
            (
                (launcher, windowed)
                for launcher, windowed in known_launchers
                if payload.startswith(launcher)
            ),
            None,
        )
        if matched is None:
            continue
        launcher, windowed = matched
        line_end = payload.find(b"\n", len(launcher))
        if line_end < 0 or not payload[line_end + 1 :].startswith(b"PK"):
            continue
        if relative_python is None:
            relative_python = _relative_launcher_executable()
        interpreter = (
            relative_python.replace("python.exe", "pythonw.exe")
            if windowed
            else relative_python
        )
        replacement = f"#!{interpreter}\n".encode("utf-8")
        healed = launcher + replacement + payload[line_end + 1 :]
        if healed == payload:
            continue
        _replace_file(executable, healed)
