from __future__ import annotations

import ctypes
import hashlib
import os
import re
import shutil
import subprocess
from collections.abc import Mapping
from pathlib import Path, PurePosixPath, PureWindowsPath
from tempfile import TemporaryDirectory

SEVENZIP_EXE_SHA256 = (
    "6b95e76bbe2147bdc6b0debbd28fd45ef160175fa22762f64ffdb0025e75e9e6"
)
SEVENZIP_DLL_SHA256 = (
    "84d2bcf774aba77e938d3f36bfe020e0d49cfb3074ad9de69b5af78054602b7e"
)

_SEVENZIP_NOISE_PATTERNS = [
    re.compile(r"^7-Zip .* Copyright \(c\) 1999.* Igor Pavlov.*$"),
    re.compile(r"^Open archive: .*$"),
    re.compile(r"^-+$"),
    re.compile(r"^Path = .*$"),
    re.compile(r"^Type = .*$"),
    re.compile(r"^Physical Size = .*$"),
    re.compile(r"^Headers Size = .*$"),
    re.compile(r"^Method = .*$"),
    re.compile(r"^Solid = .*$"),
    re.compile(r"^Blocks = .*$"),
    re.compile(r"^Scanning the drive:.*$"),
    re.compile(r"^.* files?, .* bytes.*$"),
    re.compile(r"^Updating archive: .*$"),
    re.compile(r"^Creating archive: .*$"),
    re.compile(r"^Add new data to archive: .*$"),
    re.compile(r"^Files read from disk: .*$"),
    re.compile(r"^Archive size: .*$"),
    re.compile(r"^Everything is Ok.*$"),
    re.compile(r"^Extracting archive:.*$"),
    re.compile(r"^Scanning the drive for archives:.*$"),
    re.compile(r"^Offset\s+=\s+\d+$"),
    re.compile(r"^Folders:\s+\d+.*$"),
    re.compile(r"^Files:\s+\d+.*$"),
    re.compile(r"^Size:\s+\d+.*$"),
    re.compile(r"^Compressed:\s+\d+.*$"),
    re.compile(r"^\s*\d+%\s.*$"),
    re.compile(r"^\s*\d+%$"),
]


def vendored_7zip_files() -> dict[Path, str]:
    sevenzip_exe = _vendored_7zip_file("7z.exe", SEVENZIP_EXE_SHA256)
    sevenzip_dll = _vendored_7zip_file("7z.dll", SEVENZIP_DLL_SHA256)
    return {
        sevenzip_exe: "bin/7z.exe",
        sevenzip_dll: "bin/7z.dll",
    }


def vendored_7zip_executable() -> Path:
    return _vendored_7zip_file("7z.exe", SEVENZIP_EXE_SHA256)


def create_7z_payload_archive(
    output_path: Path,
    project_root: Path,
    remap_table: Mapping[Path, PurePosixPath],
    *,
    version: str,
    sevenzip_bin: Path | None = None,
) -> None:
    if sevenzip_bin is None:
        sevenzip_bin = vendored_7zip_executable()

    output_path = output_path.resolve()
    if output_path.exists():
        output_path.unlink()
    output_path.parent.mkdir(parents=True, exist_ok=True)

    project_root = project_root.resolve()
    with TemporaryDirectory() as temp_dir_str:
        stage_dir = Path(temp_dir_str) / "stage"
        stage_dir.mkdir()

        direct_files: list[Path] = []
        staged_files: list[Path] = []
        for source, destination in sorted(
            remap_table.items(), key=lambda item: item[1].as_posix()
        ):
            archive_path = validate_archive_path(destination)
            source_path = source.resolve()
            if _can_archive_directly(project_root, source_path, archive_path):
                direct_files.append(source_path)
                continue
            staged_files.append(_stage_file(source_path, stage_dir, archive_path))

        version_path = stage_dir / "version.txt"
        version_path.write_text(version, encoding="utf-8")
        staged_files.append(version_path)

        archive_created = False
        if direct_files:
            _create_7z_from_filelist(
                output_path,
                project_root,
                direct_files,
                sevenzip_bin=sevenzip_bin,
                append=False,
            )
            archive_created = True
        if staged_files:
            _create_7z_from_filelist(
                output_path,
                stage_dir,
                staged_files,
                sevenzip_bin=sevenzip_bin,
                append=archive_created,
            )


def validate_archive_path(value: PurePosixPath | str) -> PurePosixPath:
    raw_value = str(value).replace("\\", "/")
    posix_path = PurePosixPath(raw_value)
    windows_path = PureWindowsPath(raw_value)
    if (
        not raw_value
        or raw_value.strip() != raw_value
        or posix_path.is_absolute()
        or windows_path.is_absolute()
        or windows_path.drive
    ):
        raise ValueError(f"Unsafe archive path: {value!s}")
    if any(part in ("", ".", "..") for part in posix_path.parts):
        raise ValueError(f"Unsafe archive path: {value!s}")
    if any(":" in part for part in posix_path.parts):
        raise ValueError(f"Unsafe archive path: {value!s}")
    return posix_path


def can_7z_read_file(filepath: Path) -> bool:
    if os.name != "nt":
        return True

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    create_file = kernel32.CreateFileW
    create_file.argtypes = [
        ctypes.c_wchar_p,
        ctypes.c_uint32,
        ctypes.c_uint32,
        ctypes.c_void_p,
        ctypes.c_uint32,
        ctypes.c_uint32,
        ctypes.c_void_p,
    ]
    create_file.restype = ctypes.c_void_p
    close_handle = kernel32.CloseHandle
    close_handle.argtypes = [ctypes.c_void_p]
    close_handle.restype = ctypes.c_int

    generic_read = 0x80000000
    generic_write = 0x40000000
    open_existing = 3
    file_attribute_normal = 0x80
    invalid_handle_value = ctypes.c_void_p(-1).value
    handle = create_file(
        str(filepath),
        generic_read | generic_write,
        0,
        None,
        open_existing,
        file_attribute_normal,
        None,
    )
    if handle == invalid_handle_value:
        return False
    close_handle(handle)
    return True


def _vendored_7zip_file(name: str, expected_sha256: str) -> Path:
    path = Path(__file__).resolve().parent / "assets" / "7zip" / name
    payload = path.read_bytes()
    actual = hashlib.sha256(payload).hexdigest()
    if actual != expected_sha256:
        raise RuntimeError(
            f"Vendored 7-Zip file {name} SHA256 mismatch: "
            f"expected {expected_sha256}, got {actual}."
        )
    return path


def _can_archive_directly(
    project_root: Path,
    source: Path,
    archive_path: PurePosixPath,
) -> bool:
    try:
        relative = source.relative_to(project_root)
    except ValueError:
        return False
    return archive_path == PurePosixPath(relative.as_posix()) and can_7z_read_file(
        source
    )


def _stage_file(source: Path, stage_dir: Path, archive_path: PurePosixPath) -> Path:
    target = stage_dir.joinpath(*archive_path.parts)
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        shutil.copy2(source, target)
    except OSError as error:
        raise RuntimeError(f"Failed to stage file for 7z archive: {source}") from error
    return target


def _create_7z_from_filelist(
    output_path: Path,
    base_dir: Path,
    filelist: list[Path],
    *,
    sevenzip_bin: Path,
    append: bool,
) -> None:
    if not filelist:
        return
    if not append and output_path.exists():
        output_path.unlink()

    with TemporaryDirectory() as temp_dir_str:
        filelist_path = Path(temp_dir_str) / "7z-files.txt"
        filelist_path.write_text(
            "\n".join(
                file.resolve().relative_to(base_dir.resolve()).as_posix()
                for file in filelist
            ),
            encoding="utf-8",
        )
        _run_7z_quiet(
            [
                sevenzip_bin,
                "a",
                "-y",
                "-t7z",
                "-m0=lzma2:d1024m",
                "-mx=9",
                "-aoa",
                "-mfb=64",
                "-md=32m",
                "-ms=on",
                "-scsUTF-8",
                "-bd",
                output_path,
                f"@{filelist_path}",
            ],
            cwd=base_dir,
        )


def _run_7z_quiet(command: list[Path | str], *, cwd: Path) -> None:
    result = subprocess.run(
        [os.fspath(item) for item in command],
        cwd=cwd,
        capture_output=True,
        text=True,
        check=False,
    )
    output = _filter_7z_output(result.stdout + result.stderr)
    if result.returncode != 0:
        detail = output.strip() or (result.stdout + result.stderr).strip()
        if detail:
            raise RuntimeError(
                "7-Zip command failed with exit code "
                f"{result.returncode}:\n{detail}"
            )
        raise RuntimeError(f"7-Zip command failed with exit code {result.returncode}.")


def _filter_7z_output(output: str) -> str:
    visible_lines = []
    for line in output.splitlines():
        normalized = line.strip()
        if not normalized:
            continue
        if any(pattern.match(normalized) for pattern in _SEVENZIP_NOISE_PATTERNS):
            continue
        visible_lines.append(line)
    return "\n".join(visible_lines)
