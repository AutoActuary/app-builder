from __future__ import annotations

import hashlib
import os
import struct
from dataclasses import dataclass
from importlib.resources import files
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

EXE_WRAP_CONFIG_START_MARKER = b"8c0e8d4c-32af-4fd8-9c68-6a0f97efeb6a"
EXE_WRAP_CONFIG_END_MARKER = b"ce3beca3-7ed2-40a4-9133-f82198be1d7b"
EXE_WRAP_CONSOLE_X64_SHA256 = (
    "f1a68e6b71dbe0db7db3e8c151dcb66c10d77469a219f1cb4fb365fe3a78cf10"
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


@dataclass(frozen=True, slots=True)
class _IconImage:
    width: int
    height: int
    color_count: int
    planes: int
    bit_count: int
    data: bytes


def stamp_exe_icon(exe_payload: bytes, icon_path: Path) -> bytes:
    if os.name != "nt":
        raise RuntimeError(
            "Embedding installer.icon into ExeWrap executables requires Windows."
        )
    if not icon_path.is_file():
        raise FileNotFoundError(f"Configured installer.icon does not exist: {icon_path}")

    images = _read_icon_images(icon_path)
    with TemporaryDirectory() as temp_dir_str:
        exe_path = Path(temp_dir_str) / "launcher.exe"
        exe_path.write_bytes(exe_payload)
        _update_exe_icon_resources(exe_path, images)
        return exe_path.read_bytes()


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


def _read_icon_images(icon_path: Path) -> list[_IconImage]:
    payload = icon_path.read_bytes()
    if len(payload) < 6:
        raise ValueError(f"{icon_path} is not a valid .ico file.")

    reserved, image_type, image_count = struct.unpack_from("<HHH", payload, 0)
    if reserved != 0 or image_type != 1 or image_count < 1:
        raise ValueError(f"{icon_path} is not a Windows icon (.ico) file.")

    directory_size = 6 + image_count * 16
    if len(payload) < directory_size:
        raise ValueError(f"{icon_path} has a truncated .ico directory.")

    images: list[_IconImage] = []
    for index in range(image_count):
        offset = 6 + index * 16
        (
            width,
            height,
            color_count,
            reserved_byte,
            planes,
            bit_count,
            bytes_in_resource,
            image_offset,
        ) = struct.unpack_from("<BBBBHHII", payload, offset)
        if reserved_byte != 0:
            raise ValueError(f"{icon_path} has an invalid .ico directory entry.")
        if bytes_in_resource < 1:
            raise ValueError(f"{icon_path} has an empty .ico image.")
        image_end = image_offset + bytes_in_resource
        if image_offset >= len(payload) or image_end > len(payload):
            raise ValueError(f"{icon_path} has a truncated .ico image.")
        images.append(
            _IconImage(
                width=width,
                height=height,
                color_count=color_count,
                planes=planes,
                bit_count=bit_count,
                data=payload[image_offset:image_end],
            )
        )
    return images


def _render_icon_group_resource(images: list[_IconImage]) -> bytes:
    parts = [struct.pack("<HHH", 0, 1, len(images))]
    for resource_id, image in enumerate(images, start=1):
        parts.append(
            struct.pack(
                "<BBBBHHIH",
                image.width,
                image.height,
                image.color_count,
                0,
                image.planes,
                image.bit_count,
                len(image.data),
                resource_id,
            )
        )
    return b"".join(parts)


def _update_exe_icon_resources(exe_path: Path, images: list[_IconImage]) -> None:
    import ctypes
    from ctypes import wintypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    begin_update_resource = kernel32.BeginUpdateResourceW
    begin_update_resource.argtypes = [wintypes.LPCWSTR, wintypes.BOOL]
    begin_update_resource.restype = wintypes.HANDLE

    update_resource = kernel32.UpdateResourceW
    update_resource.argtypes = [
        wintypes.HANDLE,
        wintypes.LPCWSTR,
        wintypes.LPCWSTR,
        wintypes.WORD,
        wintypes.LPVOID,
        wintypes.DWORD,
    ]
    update_resource.restype = wintypes.BOOL

    end_update_resource = kernel32.EndUpdateResourceW
    end_update_resource.argtypes = [wintypes.HANDLE, wintypes.BOOL]
    end_update_resource.restype = wintypes.BOOL

    handle = begin_update_resource(str(exe_path), False)
    if not handle:
        raise ctypes.WinError(ctypes.get_last_error())

    should_discard = True
    try:
        for resource_id, image in enumerate(images, start=1):
            _update_resource(
                update_resource,
                handle,
                resource_type=3,
                resource_name=resource_id,
                data=image.data,
            )
        _update_resource(
            update_resource,
            handle,
            resource_type=14,
            resource_name=1,
            data=_render_icon_group_resource(images),
        )
        if not end_update_resource(handle, False):
            raise ctypes.WinError(ctypes.get_last_error())
        should_discard = False
    finally:
        if should_discard:
            end_update_resource(handle, True)


def _update_resource(
    update_resource: Any,
    handle: Any,
    *,
    resource_type: int,
    resource_name: int,
    data: bytes,
) -> None:
    import ctypes
    from ctypes import wintypes

    data_buffer = ctypes.create_string_buffer(data)
    ok = update_resource(
        handle,
        _make_int_resource(resource_type),
        _make_int_resource(resource_name),
        wintypes.WORD(0x0409),
        data_buffer,
        len(data),
    )
    if not ok:
        raise ctypes.WinError(ctypes.get_last_error())


def _make_int_resource(value: int) -> Any:
    import ctypes
    from ctypes import wintypes

    return ctypes.cast(ctypes.c_void_p(value), wintypes.LPCWSTR)
