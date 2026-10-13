from __future__ import annotations

import json
import os
import queue
import shutil
import subprocess
import sys
import threading
import time
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from app_builder.installer_bundle import _powershell_common_functions

from test.test_installer_failure_modes import (
    _build_and_extract_installer,
    _installer_env,
    _registry_entries_for_install,
    _remove_registry_entries_for_install,
    _run_install,
    _winreg,
    _write_payload,
)

_CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)
_POWERSHELL = shutil.which("powershell.exe") or "powershell.exe"


_NATIVE_HANDLE_CHILD = r"""
import ctypes
import sys

kernel = ctypes.WinDLL("kernel32", use_last_error=True)
kernel.CreateFileW.argtypes = [
    ctypes.c_wchar_p, ctypes.c_uint, ctypes.c_uint, ctypes.c_void_p,
    ctypes.c_uint, ctypes.c_uint, ctypes.c_void_p,
]
kernel.CreateFileW.restype = ctypes.c_void_p
kernel.CloseHandle.argtypes = [ctypes.c_void_p]
kernel.CloseHandle.restype = ctypes.c_int

path = sys.argv[1]
is_directory = sys.argv[2] == "directory"
flags = 0x02000000 if is_directory else 0
handle = kernel.CreateFileW(path, 0, 0x3, None, 3, flags, None)
if handle == ctypes.c_void_p(-1).value:
    print("ERROR:" + str(ctypes.get_last_error()), flush=True)
    raise SystemExit(2)
print("READY", flush=True)
try:
    command = sys.stdin.readline().strip()
    if command != "RELEASE":
        print("ERROR:missing release", flush=True)
        raise SystemExit(3)
finally:
    kernel.CloseHandle(handle)
print("RELEASED", flush=True)
"""


def _powershell_quote(value: str | Path) -> str:
    return "'" + str(value).replace("'", "''") + "'"


class _ProcessLines:
    def __init__(self, process: subprocess.Popen[str]) -> None:
        self.queue: queue.Queue[str] = queue.Queue()

        def read() -> None:
            assert process.stdout is not None
            for line in process.stdout:
                self.queue.put(line)

        self.reader = threading.Thread(target=read, daemon=True)
        self.reader.start()

    def join(self, timeout: float = 5) -> None:
        self.reader.join(timeout=timeout)
        if self.reader.is_alive():
            raise AssertionError("process output reader did not reach EOF")

    def drain(self) -> list[str]:
        output: list[str] = []
        while True:
            try:
                output.append(self.queue.get_nowait())
            except queue.Empty:
                return output


def _terminate_process_tree(process: subprocess.Popen[str]) -> None:
    if process.poll() is not None:
        return
    taskkill = shutil.which("taskkill.exe") or shutil.which("taskkill")
    if taskkill:
        try:
            subprocess.run(
                [taskkill, "/PID", str(process.pid), "/T", "/F"],
                capture_output=True,
                text=True,
                timeout=5,
                creationflags=_CREATE_NO_WINDOW,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired):
            pass
    if process.poll() is None:
        process.kill()
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        pass


def _close_process_streams(process: subprocess.Popen[str]) -> None:
    for stream in (process.stdin, process.stdout, process.stderr):
        if stream is not None and not stream.closed:
            stream.close()


def _cleanup_process(process: subprocess.Popen[str], lines: _ProcessLines) -> None:
    if process.poll() is None:
        _terminate_process_tree(process)
    try:
        lines.join()
    except AssertionError:
        pass
    _close_process_streams(process)


def _wait_for_path(
    path: Path, process: subprocess.Popen[str], timeout: float = 10
) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if path.exists():
            return
        if process.poll() is not None:
            raise AssertionError(f"process exited before creating barrier {path}")
        time.sleep(0.05)
    if process.poll() is None:
        _terminate_process_tree(process)
    raise AssertionError(f"process did not create barrier {path}")


def _wait_for_line(
    process: subprocess.Popen[str],
    lines: _ProcessLines,
    text: str,
    timeout: float,
) -> str:
    deadline = time.monotonic() + timeout
    seen: list[str] = []
    while time.monotonic() < deadline:
        try:
            line = lines.queue.get(
                timeout=min(0.2, max(0.01, deadline - time.monotonic()))
            )
        except queue.Empty:
            if process.poll() is not None:
                lines.join()
                buffered = lines.drain()
                seen.extend(buffered)
                for buffered_line in buffered:
                    if text in buffered_line:
                        return buffered_line
                break
            continue
        seen.append(line)
        if text in line:
            return line
    _cleanup_process(process, lines)
    raise AssertionError(
        f"process did not emit {text!r}; returncode={process.poll()} output={''.join(seen)!r}"
    )


def _finish_process(
    process: subprocess.Popen[str], lines: _ProcessLines, timeout: float = 30
) -> tuple[int, str]:
    try:
        process.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        _terminate_process_tree(process)
        try:
            lines.join()
        finally:
            _close_process_streams(process)
        raise AssertionError("child process exceeded bounded timeout")
    lines.join()
    output = lines.drain()
    _close_process_streams(process)
    return int(process.returncode), "".join(output)


class _NativeHandle:
    def __init__(self, path: Path, *, directory: bool = False) -> None:
        self.process = subprocess.Popen(
            [
                sys.executable,
                "-c",
                _NATIVE_HANDLE_CHILD,
                str(path),
                "directory" if directory else "file",
            ],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            creationflags=_CREATE_NO_WINDOW,
        )
        self.lines = _ProcessLines(self.process)
        try:
            _wait_for_line(self.process, self.lines, "READY", 10)
        except Exception:
            _terminate_process_tree(self.process)
            self.lines.join()
            _close_process_streams(self.process)
            raise

    def release(self) -> None:
        if self.process.poll() is not None:
            return
        assert self.process.stdin is not None
        self.process.stdin.write("RELEASE\n")
        self.process.stdin.flush()
        _wait_for_line(self.process, self.lines, "RELEASED", 10)
        self.process.wait(timeout=10)
        self.lines.join()
        _close_process_streams(self.process)

    def close(self) -> None:
        if self.process.poll() is None:
            try:
                self.release()
            except (AssertionError, OSError, subprocess.TimeoutExpired):
                _terminate_process_tree(self.process)
        if self.process.poll() is not None:
            try:
                self.lines.join()
            except AssertionError:
                pass
        _close_process_streams(self.process)

    def __enter__(self) -> _NativeHandle:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()


def _start_powershell(
    script: Path, *, env: dict[str, str] | None = None
) -> tuple[subprocess.Popen[str], _ProcessLines]:
    process = subprocess.Popen(
        [
            _POWERSHELL,
            "-NoLogo",
            "-NoProfile",
            "-NonInteractive",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(script),
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
        env=env,
        creationflags=_CREATE_NO_WINDOW,
    )
    return process, _ProcessLines(process)


def _write_move_script(
    directory: Path,
    *,
    source: Path,
    destination: Path,
    description: str = "test directory",
    function: str = "Move-AppBuilderDirectoryWithRetry",
) -> Path:
    script = directory / "move-probe.ps1"
    script.write_text(
        _powershell_common_functions()
        + "\n$ErrorActionPreference = 'Stop'\n"
        + "$AppBuilderScriptOptions = [pscustomobject]@{ Interactive = $false }\n"
        + "try {\n"
        + f"    {function} {_powershell_quote(source)} {_powershell_quote(destination)} {_powershell_quote(description)}\n"
        + "    exit 0\n"
        + "} catch {\n"
        + "    Write-Error $_\n"
        + "    exit 1\n"
        + "}\n",
        encoding="utf-8",
    )
    return script


def _write_manifest(
    path: Path,
    *,
    name: str,
    version: str,
    install_dir: Path,
    payload_name: str,
) -> None:
    path.write_text(
        json.dumps(
            {
                "name": name,
                "version": version,
                "install_directory": str(install_dir),
                "payload_archive": payload_name,
                "add_uninstaller": True,
                "start_menu": [
                    {"display_name": "Demo", "target": "app.exe", "icon": None}
                ],
                "install_hooks": {
                    "pre_install": [],
                    "post_install": [],
                    "pre_uninstall": [],
                    "post_uninstall": [],
                },
            }
        ),
        encoding="utf-8",
    )


def _registry_version(install_dir: Path) -> str | None:
    winreg = _winreg()

    matches = _registry_entries_for_install(install_dir)
    if not matches:
        return None
    root = r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, root + "\\" + matches[0][0]) as key:
        return str(winreg.QueryValueEx(key, "DisplayVersion")[0])


@unittest.skipUnless(os.name == "nt", "generated installer scripts target Windows")
class TestInstallerMoveRetry(unittest.TestCase):
    def _run_transient_move(
        self,
        temp_dir: Path,
        *,
        source: Path,
        destination: Path,
        directory_handle: bool = False,
        function: str = "Move-AppBuilderDirectoryWithRetry",
    ) -> str:
        script = _write_move_script(
            temp_dir,
            source=source,
            destination=destination,
            function=function,
        )
        with _NativeHandle(
            source if directory_handle else source / "locked.txt",
            directory=directory_handle,
        ) as holder:
            process, lines = _start_powershell(script)
            try:
                first_warning = _wait_for_line(
                    process, lines, "Retrying directory move", 15
                )
                holder.release()
                returncode, output = _finish_process(process, lines)
            finally:
                _cleanup_process(process, lines)
        self.assertEqual(0, returncode, output)
        return first_warning + output

    def test_transient_lock_allows_full_current_install_upgrade(self) -> None:
        with TemporaryDirectory() as temp_dir_str:
            temp_dir = Path(temp_dir_str)
            appdata_dir = temp_dir / "appdata"
            install_dir = temp_dir / "installed app"
            old_payload = temp_dir / "old.zip"
            old_manifest = temp_dir / "old.json"
            _write_payload(old_payload, {"app.exe": "old", "old.txt": "old"})
            _write_manifest(
                old_manifest,
                name="Demo",
                version="1.0",
                install_dir=install_dir,
                payload_name=old_payload.name,
            )
            old_extraction = _build_and_extract_installer(
                temp_dir,
                payload=old_payload,
                manifest=old_manifest,
                app_name="Demo",
                extraction_name="old-installer",
            )
            first = _run_install(old_extraction, appdata_dir=appdata_dir)
            self.assertEqual(0, first.returncode, first.stderr)
            self.addCleanup(_remove_registry_entries_for_install, install_dir)
            self.assertEqual("1.0", _registry_version(install_dir))
            shortcut = (
                appdata_dir
                / "Microsoft"
                / "Windows"
                / "Start Menu"
                / "Programs"
                / "Demo"
                / "Demo.lnk"
            )
            self.assertTrue(shortcut.exists())

            new_payload = temp_dir / "new.zip"
            new_manifest = temp_dir / "new.json"
            _write_payload(new_payload, {"app.exe": "new", "new.txt": "new"})
            _write_manifest(
                new_manifest,
                name="Demo",
                version="2.0",
                install_dir=install_dir,
                payload_name=new_payload.name,
            )
            new_extraction = _build_and_extract_installer(
                temp_dir,
                payload=new_payload,
                manifest=new_manifest,
                app_name="Demo",
                extraction_name="new-installer",
            )
            with _NativeHandle(install_dir / "old.txt") as holder:
                process = subprocess.Popen(
                    [
                        "cmd.exe",
                        "/D",
                        "/C",
                        "call",
                        str(new_extraction / "install.cmd"),
                        "--yes",
                    ],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    bufsize=1,
                    env=_installer_env(appdata_dir),
                    creationflags=_CREATE_NO_WINDOW,
                )
                lines = _ProcessLines(process)
                try:
                    first_warning = _wait_for_line(
                        process, lines, "Retrying directory move", 20
                    )
                    holder.release()
                    returncode, output = _finish_process(process, lines)
                finally:
                    _cleanup_process(process, lines)

            self.assertEqual(0, returncode, output)
            output = first_warning + output
            self.assertIn("Retrying directory move", output)
            self.assertEqual("new", (install_dir / "new.txt").read_text())
            self.assertFalse((install_dir / "old.txt").exists())
            self.assertEqual(
                "2.0",
                json.loads(
                    (install_dir / "app-builder-manifest.json").read_text(
                        encoding="utf-8-sig"
                    )
                )["version"],
            )
            self.assertEqual("2.0", _registry_version(install_dir))
            self.assertTrue(shortcut.exists())

    def test_persistent_lock_is_bounded_and_preserves_install_registration(
        self,
    ) -> None:
        with TemporaryDirectory() as temp_dir_str:
            temp_dir = Path(temp_dir_str)
            appdata_dir = temp_dir / "appdata"
            install_dir = temp_dir / "installed app"
            old_payload = temp_dir / "old.zip"
            old_manifest = temp_dir / "old.json"
            _write_payload(old_payload, {"app.exe": "old", "old.txt": "old"})
            _write_manifest(
                old_manifest,
                name="Demo",
                version="1.0",
                install_dir=install_dir,
                payload_name=old_payload.name,
            )
            old_extraction = _build_and_extract_installer(
                temp_dir,
                payload=old_payload,
                manifest=old_manifest,
                app_name="Demo",
                extraction_name="old-installer",
            )
            self.assertEqual(
                0, _run_install(old_extraction, appdata_dir=appdata_dir).returncode
            )
            self.addCleanup(_remove_registry_entries_for_install, install_dir)
            shortcut = (
                appdata_dir
                / "Microsoft"
                / "Windows"
                / "Start Menu"
                / "Programs"
                / "Demo"
                / "Demo.lnk"
            )
            original_manifest = (install_dir / "app-builder-manifest.json").read_bytes()
            original_shortcut = shortcut.read_bytes()
            original_registry = _registry_entries_for_install(install_dir)
            new_payload = temp_dir / "new.zip"
            new_manifest = temp_dir / "new.json"
            _write_payload(new_payload, {"app.exe": "new", "new.txt": "new"})
            _write_manifest(
                new_manifest,
                name="Demo",
                version="2.0",
                install_dir=install_dir,
                payload_name=new_payload.name,
            )
            new_extraction = _build_and_extract_installer(
                temp_dir,
                payload=new_payload,
                manifest=new_manifest,
                app_name="Demo",
                extraction_name="new-installer",
            )
            with _NativeHandle(install_dir / "old.txt") as holder:
                started = time.monotonic()
                process = subprocess.Popen(
                    [
                        "cmd.exe",
                        "/D",
                        "/C",
                        "call",
                        str(new_extraction / "install.cmd"),
                        "--yes",
                    ],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    env=_installer_env(appdata_dir),
                    creationflags=_CREATE_NO_WINDOW,
                )
                lines = _ProcessLines(process)
                returncode, output = _finish_process(process, lines, timeout=20)
                elapsed = time.monotonic() - started
                holder.release()
            self.assertNotEqual(0, returncode, output)
            self.assertLess(elapsed, 15, output)
            self.assertIn("after 7 attempts", output)
            self.assertRegex(output, r"Native error (5|32)")
            self.assertEqual("old", (install_dir / "old.txt").read_text())
            self.assertFalse((install_dir / "new.txt").exists())
            self.assertEqual(
                original_manifest,
                (install_dir / "app-builder-manifest.json").read_bytes(),
            )
            self.assertEqual(original_shortcut, shortcut.read_bytes())
            self.assertEqual(
                original_registry, _registry_entries_for_install(install_dir)
            )
            self.assertEqual("1.0", _registry_version(install_dir))

    def test_restore_transient_lock_moves_backup_after_retry(self) -> None:
        with TemporaryDirectory() as temp_dir_str:
            temp_dir = Path(temp_dir_str)
            source = temp_dir / "backup"
            source.mkdir()
            (source / "locked.txt").write_text("backup")
            destination = temp_dir / "installed"
            output = self._run_transient_move(
                temp_dir,
                source=source,
                destination=destination,
                function="Restore-AppBuilderDirectory",
            )
            self.assertIn("Retrying directory move", output)
            self.assertFalse(source.exists())
            self.assertEqual("backup", (destination / "locked.txt").read_text())

    def test_restore_persistent_lock_preserves_backup(self) -> None:
        with TemporaryDirectory() as temp_dir_str:
            temp_dir = Path(temp_dir_str)
            source = temp_dir / "backup"
            source.mkdir()
            (source / "locked.txt").write_text("backup")
            destination = temp_dir / "installed"
            script = _write_move_script(
                temp_dir,
                source=source,
                destination=destination,
                function="Restore-AppBuilderDirectory",
            )
            with _NativeHandle(source / "locked.txt") as holder:
                process, lines = _start_powershell(script)
                started = time.monotonic()
                returncode, output = _finish_process(process, lines, timeout=15)
                elapsed = time.monotonic() - started
                holder.release()
            self.assertNotEqual(0, returncode, output)
            self.assertLess(elapsed, 12, output)
            self.assertIn("after 7 attempts", output)
            self.assertRegex(output, r"Native error (5|32)")
            self.assertTrue(source.exists())
            self.assertFalse(destination.exists())

    def test_rename_probe_retries_reverse_move_after_native_lock(self) -> None:
        with TemporaryDirectory() as temp_dir_str:
            temp_dir = Path(temp_dir_str)
            source = temp_dir / "existing"
            source.mkdir()
            (source / "old.txt").write_text("old")
            barrier = temp_dir / "moved-path.txt"
            acknowledged = temp_dir / "acknowledged.txt"
            script = temp_dir / "probe.ps1"
            script.write_text(
                _powershell_common_functions()
                + "\n$ErrorActionPreference = 'Stop'\n"
                + f"$script:ProbeBarrier = {_powershell_quote(barrier)}\n"
                + f"$script:ProbeAcknowledged = {_powershell_quote(acknowledged)}\n"
                + "$script:ProbeOutboundComplete = $false\n"
                + "function Move-AppBuilderDirectory {\n"
                + "    param([string]$Source, [string]$Destination, [string]$Description)\n"
                + "    if (-not $script:ProbeOutboundComplete) {\n"
                + "        Move-AppBuilderDirectoryWithRetry $Source $Destination $Description\n"
                + "        $script:ProbeOutboundComplete = $true\n"
                + "        [IO.File]::WriteAllText($script:ProbeBarrier, $Destination)\n"
                + "        while (-not (Test-Path -LiteralPath $script:ProbeAcknowledged)) { Start-Sleep -Milliseconds 25 }\n"
                + "        return\n"
                + "    }\n"
                + "    Move-AppBuilderDirectoryWithRetry $Source $Destination $Description\n"
                + "}\n"
                + f"$Moved = Test-AppBuilderDirectoryMove {_powershell_quote(source)}\n"
                + 'if ($null -ne $Moved) { throw "probe left a moved directory: $Moved" }\n'
                + f"if (-not (Test-Path -LiteralPath {_powershell_quote(source / 'old.txt')})) {{ throw 'probe did not restore source' }}\n",
                encoding="utf-8",
            )
            process, lines = _start_powershell(script)
            try:
                _wait_for_path(barrier, process)
                moved_directory = Path(barrier.read_text(encoding="utf-8"))
                with _NativeHandle(moved_directory / "old.txt") as holder:
                    acknowledged.write_text("handle-ready", encoding="utf-8")
                    first_warning = _wait_for_line(
                        process, lines, "Retrying directory move", 15
                    )
                    holder.release()
                returncode, output = _finish_process(process, lines)
            finally:
                if process.poll() is None:
                    _terminate_process_tree(process)
                if process.poll() is not None:
                    try:
                        lines.join()
                    except AssertionError:
                        pass
                _close_process_streams(process)
            self.assertEqual(0, returncode, first_warning + output)
            self.assertIn("Retrying directory move", first_warning + output)
            self.assertEqual("old", (source / "old.txt").read_text())

    def test_occupied_destination_and_missing_source_fail_without_retry(self) -> None:
        with TemporaryDirectory() as temp_dir_str:
            temp_dir = Path(temp_dir_str)
            cases = ("occupied", "missing")
            for case in cases:
                with self.subTest(case=case):
                    source = temp_dir / f"{case}-source"
                    destination = temp_dir / f"{case}-destination"
                    source.mkdir()
                    (source / "file.txt").write_text("source")
                    if case == "occupied":
                        destination.mkdir()
                        (destination / "existing.txt").write_text("keep")
                    else:
                        shutil.rmtree(source)
                    script = _write_move_script(
                        temp_dir, source=source, destination=destination
                    )
                    process, lines = _start_powershell(script)
                    returncode, output = _finish_process(process, lines, timeout=10)
                    self.assertNotEqual(0, returncode, output)
                    self.assertIn("after 1 attempts", output)
                    self.assertNotIn("Retrying directory move", output)
                    self.assertIn("Exception", output)
                    if case == "occupied":
                        self.assertEqual("source", (source / "file.txt").read_text())
                        self.assertEqual(
                            "keep", (destination / "existing.txt").read_text()
                        )
                    else:
                        self.assertFalse(source.exists())

    def test_retry_classifier_accepts_5_and_32_through_wrappers_only(self) -> None:
        with TemporaryDirectory() as temp_dir_str:
            temp_dir = Path(temp_dir_str)
            script = temp_dir / "classifier-probe.ps1"
            script.write_text(
                _powershell_common_functions() + r"""
$cases = @(
    @('error-5', [IO.IOException]::new('native 5', 0x80070005), $true),
    @('wrapped-32', [Exception]::new('wrapper', [IO.IOException]::new('native 32', 0x80070020)), $true),
    @('unknown-123', [IO.IOException]::new('unknown', 0x8007007B), $false),
    @('unauthorized-5', [UnauthorizedAccessException]::new('access denied'), $true),
    @('non-win32-32', [IO.IOException]::new('wrong facility', 0x80130020), $false)
)
foreach ($Case in $cases) {
    $Failure = Get-AppBuilderDirectoryMoveFailure $Case[1]
    if ([bool]$Failure.Retryable -ne [bool]$Case[2]) {
        throw "$($Case[0]) retry classification was $($Failure.Retryable)"
    }
    Write-Output "$($Case[0])|$($Failure.Diagnostics)"
}
""",
                encoding="utf-8",
            )
            process = subprocess.run(
                [
                    _POWERSHELL,
                    "-NoLogo",
                    "-NoProfile",
                    "-NonInteractive",
                    "-ExecutionPolicy",
                    "Bypass",
                    "-File",
                    str(script),
                ],
                capture_output=True,
                text=True,
                creationflags=_CREATE_NO_WINDOW,
                check=False,
            )
            output = process.stdout + process.stderr
            self.assertEqual(0, process.returncode, output)
            self.assertIn("error-5|", output)
            self.assertIn("Native error 5", output)
            self.assertIn("wrapped-32|", output)
            self.assertIn("Native error 32", output)
            self.assertIn("unknown-123|", output)
            self.assertIn("unauthorized-5|", output)
            self.assertIn("non-win32-32|", output)
            self.assertNotIn("Retrying directory move", output)


if __name__ == "__main__":
    unittest.main()
