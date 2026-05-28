from __future__ import annotations

import json
import os
import subprocess
import time
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from zipfile import ZipFile

from app_builder.installer_bundle import create_exewrap_zip_installer


def _write_manifest(
    path: Path,
    *,
    name: str,
    version: str,
    install_dir: Path,
    payload_name: str,
    install_hooks: dict[str, list[list[str]]] | None = None,
) -> None:
    path.write_text(
        json.dumps(
            {
                "name": name,
                "version": version,
                "install_directory": str(install_dir),
                "payload_archive": payload_name,
                "start_menu": [],
                "install_hooks": install_hooks
                or {
                    "pre_install": [],
                    "post_install": [],
                    "pre_uninstall": [],
                    "post_uninstall": [],
                },
            }
        ),
        encoding="utf-8",
    )


def _write_payload(path: Path, files: dict[str, str]) -> None:
    with ZipFile(path, "w") as payload_zip:
        for archive_name, contents in files.items():
            payload_zip.writestr(archive_name, contents)


def _build_and_extract_installer(
    temp_dir: Path,
    *,
    payload: Path,
    manifest: Path,
    app_name: str = "Demo",
    extraction_name: str = "top-layer",
) -> Path:
    installer = temp_dir / f"{extraction_name}.exe"
    extraction_dir = temp_dir / extraction_name
    extraction_dir.mkdir()
    create_exewrap_zip_installer(
        installer,
        payload_archive=payload,
        manifest_path=manifest,
        app_name=app_name,
        pause_on_exit=False,
        add_uninstaller=True,
        launcher=b"fake-launcher",
    )
    with ZipFile(installer) as installer_zip:
        installer_zip.extractall(extraction_dir)
    return extraction_dir


def _installer_env(appdata_dir: Path, temp_dir: Path | None = None) -> dict[str, str]:
    env = os.environ.copy()
    env["APPDATA"] = str(appdata_dir)
    if temp_dir is not None:
        env["TEMP"] = str(temp_dir)
        env["TMP"] = str(temp_dir)
    return env


def _run_install(
    extraction_dir: Path, *, appdata_dir: Path, temp_dir: Path | None = None
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["cmd.exe", "/D", "/C", "call", str(extraction_dir / "install.cmd"), "--yes"],
        capture_output=True,
        text=True,
        env=_installer_env(appdata_dir, temp_dir),
        check=False,
    )


def _run_uninstall(
    uninstall_cmd: Path, *, appdata_dir: Path, temp_dir: Path | None = None
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["cmd.exe", "/D", "/C", "call", str(uninstall_cmd), "--yes"],
        capture_output=True,
        text=True,
        env=_installer_env(appdata_dir, temp_dir),
        check=False,
    )


@unittest.skipIf(os.name != "nt", "generated installer scripts target Windows")
class TestInstallerFailureModes(unittest.TestCase):
    def test_corrupt_existing_manifest_refuses_and_preserves_directory(self) -> None:
        with TemporaryDirectory() as temp_dir_str:
            temp_dir = Path(temp_dir_str)
            appdata_dir = temp_dir / "appdata"
            install_dir = temp_dir / "installed app"
            start_menu_dir = (
                appdata_dir
                / "Microsoft"
                / "Windows"
                / "Start Menu"
                / "Programs"
                / "Demo"
            )
            start_menu_dir.mkdir(parents=True)
            (start_menu_dir / "old-shortcut.lnk").write_text(
                "old shortcut", encoding="utf-8"
            )
            install_dir.mkdir()
            (install_dir / "app-builder-manifest.json").write_text(
                "{", encoding="utf-8"
            )
            (install_dir / "old.txt").write_text("old", encoding="utf-8")
            payload = temp_dir / "payload.zip"
            _write_payload(payload, {"new.txt": "new"})
            manifest = temp_dir / "manifest.json"
            _write_manifest(
                manifest,
                name="Demo",
                version="2.0",
                install_dir=install_dir,
                payload_name=payload.name,
            )
            extraction_dir = _build_and_extract_installer(
                temp_dir, payload=payload, manifest=manifest
            )

            result = _run_install(extraction_dir, appdata_dir=appdata_dir)

            self.assertNotEqual(0, result.returncode)
            self.assertIn("manifest is corrupt", result.stderr)
            self.assertIn("unreadable", result.stderr)
            self.assertEqual("old", (install_dir / "old.txt").read_text())
            self.assertFalse((install_dir / "new.txt").exists())

    def test_existing_manifest_for_different_app_refuses_without_mutation(self) -> None:
        with TemporaryDirectory() as temp_dir_str:
            temp_dir = Path(temp_dir_str)
            appdata_dir = temp_dir / "appdata"
            install_dir = temp_dir / "installed app"
            start_menu_dir = (
                appdata_dir
                / "Microsoft"
                / "Windows"
                / "Start Menu"
                / "Programs"
                / "Demo"
            )
            start_menu_dir.mkdir(parents=True)
            (start_menu_dir / "old-shortcut.lnk").write_text(
                "old shortcut", encoding="utf-8"
            )
            install_dir.mkdir()
            _write_manifest(
                install_dir / "app-builder-manifest.json",
                name="Other App",
                version="1.0",
                install_dir=install_dir,
                payload_name="old.zip",
            )
            (install_dir / "old.txt").write_text("old", encoding="utf-8")
            payload = temp_dir / "payload.zip"
            _write_payload(payload, {"new.txt": "new"})
            manifest = temp_dir / "manifest.json"
            _write_manifest(
                manifest,
                name="Demo",
                version="2.0",
                install_dir=install_dir,
                payload_name=payload.name,
            )
            extraction_dir = _build_and_extract_installer(
                temp_dir, payload=payload, manifest=manifest
            )

            result = _run_install(extraction_dir, appdata_dir=appdata_dir)

            self.assertNotEqual(0, result.returncode)
            self.assertIn("different app-builder app", result.stderr)
            self.assertEqual("old", (install_dir / "old.txt").read_text())
            self.assertFalse((install_dir / "new.txt").exists())

    def test_failing_pre_install_does_not_touch_existing_install(self) -> None:
        with TemporaryDirectory() as temp_dir_str:
            temp_dir = Path(temp_dir_str)
            appdata_dir = temp_dir / "appdata"
            install_dir = temp_dir / "installed app"
            start_menu_dir = (
                appdata_dir
                / "Microsoft"
                / "Windows"
                / "Start Menu"
                / "Programs"
                / "Demo"
            )
            start_menu_dir.mkdir(parents=True)
            (start_menu_dir / "old-shortcut.lnk").write_text(
                "old shortcut", encoding="utf-8"
            )
            install_dir.mkdir()
            _write_manifest(
                install_dir / "app-builder-manifest.json",
                name="Demo",
                version="1.0",
                install_dir=install_dir,
                payload_name="old.zip",
            )
            (install_dir / "old.txt").write_text("old", encoding="utf-8")
            payload = temp_dir / "payload.zip"
            _write_payload(payload, {"fail-pre.cmd": "@echo off\nexit /b 23\n"})
            manifest = temp_dir / "manifest.json"
            _write_manifest(
                manifest,
                name="Demo",
                version="2.0",
                install_dir=install_dir,
                payload_name=payload.name,
                install_hooks={
                    "pre_install": [["fail-pre.cmd"]],
                    "post_install": [],
                    "pre_uninstall": [],
                    "post_uninstall": [],
                },
            )
            extraction_dir = _build_and_extract_installer(
                temp_dir, payload=payload, manifest=manifest
            )

            result = _run_install(extraction_dir, appdata_dir=appdata_dir)

            self.assertNotEqual(0, result.returncode)
            self.assertEqual("old", (install_dir / "old.txt").read_text())
            self.assertFalse((install_dir / "fail-pre.cmd").exists())
            self.assertEqual(
                "old shortcut",
                (start_menu_dir / "old-shortcut.lnk").read_text(encoding="utf-8"),
            )

    def test_failing_current_pre_uninstall_preserves_existing_install(self) -> None:
        with TemporaryDirectory() as temp_dir_str:
            temp_dir = Path(temp_dir_str)
            appdata_dir = temp_dir / "appdata"
            install_dir = temp_dir / "installed app"
            install_dir.mkdir()
            (install_dir / "fail-uninstall.cmd").write_text(
                "@echo off\nexit /b 42\n", encoding="utf-8"
            )
            _write_manifest(
                install_dir / "app-builder-manifest.json",
                name="Demo",
                version="1.0",
                install_dir=install_dir,
                payload_name="old.zip",
                install_hooks={
                    "pre_install": [],
                    "post_install": [],
                    "pre_uninstall": [["fail-uninstall.cmd"]],
                    "post_uninstall": [],
                },
            )
            (install_dir / "old.txt").write_text("old", encoding="utf-8")
            payload = temp_dir / "payload.zip"
            _write_payload(payload, {"new.txt": "new"})
            manifest = temp_dir / "manifest.json"
            _write_manifest(
                manifest,
                name="Demo",
                version="2.0",
                install_dir=install_dir,
                payload_name=payload.name,
            )
            extraction_dir = _build_and_extract_installer(
                temp_dir, payload=payload, manifest=manifest
            )

            result = _run_install(extraction_dir, appdata_dir=appdata_dir)

            self.assertNotEqual(0, result.returncode)
            self.assertEqual("old", (install_dir / "old.txt").read_text())
            self.assertTrue((install_dir / "app-builder-manifest.json").exists())
            self.assertFalse((install_dir / "new.txt").exists())

    def test_locked_existing_file_prevents_upgrade_and_preserves_install(self) -> None:
        with TemporaryDirectory() as temp_dir_str:
            temp_dir = Path(temp_dir_str)
            appdata_dir = temp_dir / "appdata"
            install_dir = temp_dir / "installed app"
            start_menu_dir = (
                appdata_dir
                / "Microsoft"
                / "Windows"
                / "Start Menu"
                / "Programs"
                / "Demo"
            )
            start_menu_dir.mkdir(parents=True)
            (start_menu_dir / "old-shortcut.lnk").write_text(
                "old shortcut", encoding="utf-8"
            )
            install_dir.mkdir()
            _write_manifest(
                install_dir / "app-builder-manifest.json",
                name="Demo",
                version="1.0",
                install_dir=install_dir,
                payload_name="old.zip",
            )
            locked_file = install_dir / "locked.txt"
            locked_file.write_text("old locked", encoding="utf-8")
            payload = temp_dir / "payload.zip"
            _write_payload(payload, {"new.txt": "new"})
            manifest = temp_dir / "manifest.json"
            _write_manifest(
                manifest,
                name="Demo",
                version="2.0",
                install_dir=install_dir,
                payload_name=payload.name,
            )
            extraction_dir = _build_and_extract_installer(
                temp_dir, payload=payload, manifest=manifest
            )

            with locked_file.open("r", encoding="utf-8") as _locked_handle:
                result = _run_install(extraction_dir, appdata_dir=appdata_dir)

            self.assertNotEqual(0, result.returncode)
            self.assertIn("Failed to move existing install directory", result.stderr)
            self.assertEqual("old locked", locked_file.read_text(encoding="utf-8"))
            self.assertFalse((install_dir / "new.txt").exists())
            self.assertEqual(
                "old shortcut",
                (start_menu_dir / "old-shortcut.lnk").read_text(encoding="utf-8"),
            )

    def test_legacy_like_directory_with_wrong_app_contract_is_refused(self) -> None:
        with TemporaryDirectory() as temp_dir_str:
            temp_dir = Path(temp_dir_str)
            appdata_dir = temp_dir / "appdata"
            install_dir = temp_dir / "installed app"
            (install_dir / "bin").mkdir(parents=True)
            (install_dir / "scripts").mkdir()
            (install_dir / "bin" / "Uninstall Other App.bat").write_text(
                "@echo off\nexit /b 0\n",
                encoding="utf-8",
            )
            (install_dir / "Uninstall Other App.lnk").write_text(
                "wrong legacy shortcut marker",
                encoding="utf-8",
            )
            (install_dir / "old.txt").write_text("old", encoding="utf-8")
            payload = temp_dir / "payload.zip"
            _write_payload(payload, {"new.txt": "new"})
            manifest = temp_dir / "manifest.json"
            _write_manifest(
                manifest,
                name="Demo",
                version="2.0",
                install_dir=install_dir,
                payload_name=payload.name,
            )
            extraction_dir = _build_and_extract_installer(
                temp_dir, payload=payload, manifest=manifest
            )

            result = _run_install(extraction_dir, appdata_dir=appdata_dir)

            self.assertNotEqual(0, result.returncode)
            self.assertIn("not", result.stderr)
            self.assertIn("recognized app-builder install", result.stderr)
            self.assertEqual("old", (install_dir / "old.txt").read_text())
            self.assertFalse((install_dir / "new.txt").exists())

    def test_failing_post_install_rolls_back_matching_1x_upgrade(self) -> None:
        with TemporaryDirectory() as temp_dir_str:
            temp_dir = Path(temp_dir_str)
            appdata_dir = temp_dir / "appdata"
            install_dir = temp_dir / "installed app"
            start_menu_dir = (
                appdata_dir
                / "Microsoft"
                / "Windows"
                / "Start Menu"
                / "Programs"
                / "Demo"
            )
            start_menu_dir.mkdir(parents=True)
            (start_menu_dir / "old-shortcut.lnk").write_text(
                "old shortcut", encoding="utf-8"
            )
            install_dir.mkdir()
            _write_manifest(
                install_dir / "app-builder-manifest.json",
                name="Demo",
                version="1.0",
                install_dir=install_dir,
                payload_name="old.zip",
            )
            (install_dir / "old.txt").write_text("old", encoding="utf-8")
            payload = temp_dir / "payload.zip"
            _write_payload(
                payload,
                {
                    "new.txt": "new",
                    "fail-post.cmd": "@echo off\nexit /b 19\n",
                },
            )
            manifest = temp_dir / "manifest.json"
            _write_manifest(
                manifest,
                name="Demo",
                version="2.0",
                install_dir=install_dir,
                payload_name=payload.name,
                install_hooks={
                    "pre_install": [],
                    "post_install": [["fail-post.cmd"]],
                    "pre_uninstall": [],
                    "post_uninstall": [],
                },
            )
            extraction_dir = _build_and_extract_installer(
                temp_dir, payload=payload, manifest=manifest
            )

            result = _run_install(extraction_dir, appdata_dir=appdata_dir)

            self.assertNotEqual(0, result.returncode)
            self.assertEqual("old", (install_dir / "old.txt").read_text())
            self.assertFalse((install_dir / "new.txt").exists())
            self.assertEqual(
                "old shortcut",
                (start_menu_dir / "old-shortcut.lnk").read_text(encoding="utf-8"),
            )
            self.assertFalse((start_menu_dir / "Uninstall Demo.lnk").exists())

    def test_legacy_pre_uninstall_failure_preserves_legacy_directory(self) -> None:
        with TemporaryDirectory() as temp_dir_str:
            temp_dir = Path(temp_dir_str)
            appdata_dir = temp_dir / "appdata"
            install_dir = temp_dir / "installed app"
            (install_dir / "bin").mkdir(parents=True)
            (install_dir / "scripts").mkdir()
            (install_dir / "bin" / "Uninstall Demo.bat").write_text(
                "@echo off\nexit /b 0\n",
                encoding="utf-8",
            )
            (install_dir / "Uninstall Demo.lnk").write_text(
                "legacy shortcut marker",
                encoding="utf-8",
            )
            (install_dir / "scripts" / "pre-uninstall.cmd").write_text(
                "@echo off\nexit /b 31\n",
                encoding="utf-8",
            )
            (install_dir / "old.txt").write_text("old", encoding="utf-8")
            payload = temp_dir / "payload.zip"
            _write_payload(payload, {"new.txt": "new"})
            manifest = temp_dir / "manifest.json"
            _write_manifest(
                manifest,
                name="Demo",
                version="2.0",
                install_dir=install_dir,
                payload_name=payload.name,
            )
            extraction_dir = _build_and_extract_installer(
                temp_dir, payload=payload, manifest=manifest
            )

            result = _run_install(extraction_dir, appdata_dir=appdata_dir)

            self.assertNotEqual(0, result.returncode)
            self.assertIn("Legacy pre-uninstall hook failed", result.stderr)
            self.assertEqual("old", (install_dir / "old.txt").read_text())
            self.assertFalse((install_dir / "new.txt").exists())

    def test_failed_post_uninstall_retains_temp_error_diagnostics(self) -> None:
        with TemporaryDirectory() as temp_dir_str:
            temp_dir = Path(temp_dir_str)
            appdata_dir = temp_dir / "appdata"
            runtime_temp = temp_dir / "runtime-temp"
            runtime_temp.mkdir()
            install_dir = temp_dir / "installed app"
            payload = temp_dir / "payload.zip"
            _write_payload(
                payload,
                {
                    "app.cmd": "@echo off\necho app\n",
                    "hooks/post-uninstall.cmd": "@echo off\nexit /b 77\n",
                },
            )
            manifest = temp_dir / "manifest.json"
            _write_manifest(
                manifest,
                name="Demo",
                version="1.0",
                install_dir=install_dir,
                payload_name=payload.name,
                install_hooks={
                    "pre_install": [],
                    "post_install": [],
                    "pre_uninstall": [],
                    "post_uninstall": [["hooks/post-uninstall.cmd"]],
                },
            )
            extraction_dir = _build_and_extract_installer(
                temp_dir, payload=payload, manifest=manifest
            )

            install_result = _run_install(
                extraction_dir,
                appdata_dir=appdata_dir,
                temp_dir=runtime_temp,
            )
            self.assertEqual(0, install_result.returncode, install_result.stderr)

            uninstall_result = _run_uninstall(
                install_dir / "bin" / "uninstall.cmd",
                appdata_dir=appdata_dir,
                temp_dir=runtime_temp,
            )

            self.assertEqual(0, uninstall_result.returncode, uninstall_result.stderr)
            error_files: list[Path] = []
            deadline = time.monotonic() + 10
            while time.monotonic() < deadline:
                error_files = [
                    path / "error.txt"
                    for path in runtime_temp.glob("app-builder-post-uninstall-*")
                    if (path / "error.txt").exists()
                ]
                if (not install_dir.exists()) and error_files:
                    break
                time.sleep(0.1)

            self.assertFalse(install_dir.exists())
            self.assertTrue(error_files)
            self.assertIn(
                "post_uninstall command failed",
                error_files[0].read_text(encoding="utf-8"),
            )
            renamed_temp = runtime_temp.with_name("runtime-temp-renamed")
            deadline = time.monotonic() + 10
            while time.monotonic() < deadline:
                try:
                    runtime_temp.rename(renamed_temp)
                    renamed_temp.rename(runtime_temp)
                    break
                except PermissionError:
                    time.sleep(0.1)
            else:
                self.fail("post-uninstall cleanup process kept the temp directory busy")
