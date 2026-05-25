from __future__ import annotations

import hashlib
from importlib.resources import files

EXE_WRAP_CONFIG_START_MARKER = b"8c0e8d4c-32af-4fd8-9c68-6a0f97efeb6a"
EXE_WRAP_CONFIG_END_MARKER = b"ce3beca3-7ed2-40a4-9133-f82198be1d7b"
EXE_WRAP_CONSOLE_X64_SHA256 = (
    "e272dcbb319cd4e1c18da20211cb8f6e17b9c2b386b1eb68c63e53ac17d9540a"
)


def vendored_console_launcher_bytes() -> bytes:
    payload = (
        files("app_builder")
        .joinpath("assets")
        .joinpath("exewrap")
        .joinpath("ExeWrap-console-x64.exe")
        .read_bytes()
    )
    actual = hashlib.sha256(payload).hexdigest()
    if actual != EXE_WRAP_CONSOLE_X64_SHA256:
        raise RuntimeError(
            "Vendored ExeWrap console launcher SHA256 mismatch: "
            f"expected {EXE_WRAP_CONSOLE_X64_SHA256}, got {actual}."
        )
    return payload


def stamp_exe_wrap_config(
    config: bytes,
    *,
    launcher: bytes | None = None,
    include_end_marker: bool = False,
) -> bytes:
    if launcher is None:
        launcher = vendored_console_launcher_bytes()
    suffix = EXE_WRAP_CONFIG_END_MARKER if include_end_marker else b""
    return launcher + EXE_WRAP_CONFIG_START_MARKER + config + suffix
