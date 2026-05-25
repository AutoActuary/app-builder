from __future__ import annotations

import json
from pathlib import Path
from tempfile import TemporaryDirectory
from zipfile import ZIP_STORED, ZipFile

from .exewrap import stamp_exe_wrap_config


def create_exewrap_zip_installer(
    output_path: Path,
    *,
    payload_archive: Path,
    manifest_path: Path,
    app_name: str,
    pause_on_exit: bool,
    add_uninstaller: bool,
    launcher: bytes | None = None,
) -> None:
    if output_path.exists():
        output_path.unlink()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_bytes(
        stamp_exe_wrap_config(
            _render_bootstrap_config(),
            launcher=launcher,
            include_end_marker=True,
        )
    )

    with TemporaryDirectory() as temp_dir_str:
        temp_dir = Path(temp_dir_str)
        install_cmd = temp_dir / "install.cmd"
        uninstall_cmd = temp_dir / "uninstall.cmd"
        install_cmd.write_text(
            _render_install_script(
                app_name,
                payload_archive.name,
                manifest_path.name,
                pause_on_exit,
            ),
            encoding="utf-8",
        )
        uninstall_cmd.write_text(
            _render_uninstall_script(app_name, pause_on_exit),
            encoding="utf-8",
        )

        with ZipFile(output_path, "a", compression=ZIP_STORED) as zip_file:
            zip_file.write(payload_archive, payload_archive.name)
            zip_file.write(manifest_path, manifest_path.name)
            zip_file.write(install_cmd, install_cmd.name)
            if add_uninstaller:
                zip_file.write(uninstall_cmd, uninstall_cmd.name)


def _render_bootstrap_config() -> bytes:
    return json.dumps(
        {
            "command": [
                "powershell.exe",
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-Command",
                _render_powershell_bootstrap(),
            ]
        },
        separators=(",", ":"),
    ).encode("utf-8")


def _render_powershell_bootstrap() -> str:
    return (
        "$ErrorActionPreference = 'Stop'; "
        "$exitCode = 0; "
        "$extractDir = Join-Path $env:TEMP "
        "('app-builder-' + [guid]::NewGuid().ToString('N')); "
        "try { "
        "New-Item -ItemType Directory -LiteralPath $extractDir | Out-Null; "
        "tar.exe -xf '@{exe_path}' -C $extractDir; "
        "if ($LASTEXITCODE -ne 0) { "
        "$exitCode = $LASTEXITCODE; "
        'throw "tar.exe failed with exit code $exitCode" '
        "}; "
        "& (Join-Path $extractDir 'install.cmd'); "
        "$exitCode = $LASTEXITCODE "
        "} catch { "
        "if ($exitCode -eq 0) { $exitCode = 1 }; "
        "Write-Error $_ -ErrorAction Continue "
        "} finally { "
        "if (Test-Path -LiteralPath $extractDir) { "
        "Remove-Item -LiteralPath $extractDir -Recurse -Force "
        "-ErrorAction SilentlyContinue "
        "} "
        "}; "
        "exit $exitCode"
    )


def _render_install_script(
    app_name: str,
    payload_name: str,
    manifest_name: str,
    pause_on_exit: bool,
) -> str:
    pause_block = "pause\n" if pause_on_exit else ""
    return (
        "@echo off\n"
        f"echo Installing {app_name}\n"
        f"echo Payload archive: {payload_name}\n"
        f"echo Manifest: {manifest_name}\n"
        "echo This first-layer installer carries the payload archive.\n"
        f"{pause_block}"
    )


def _render_uninstall_script(app_name: str, pause_on_exit: bool) -> str:
    pause_block = "pause\n" if pause_on_exit else ""
    return (
        "@echo off\n"
        f"echo Uninstall {app_name} according to your deployment policy.\n"
        f"{pause_block}"
    )
