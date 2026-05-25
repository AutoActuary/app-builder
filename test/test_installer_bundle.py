from __future__ import annotations

import json
import os
import subprocess
import time
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from zipfile import ZIP_STORED, ZipFile

from app_builder.exewrap import (
    EXE_WRAP_CONFIG_END_MARKER,
    EXE_WRAP_CONFIG_START_MARKER,
    EXE_WRAP_CONSOLE_X64_SHA256,
    vendored_console_launcher_bytes,
)
from app_builder.installer_bundle import (
    _render_bootstrap_config,
    create_exewrap_zip_installer,
)


class TestExeWrapInstallerBundle(unittest.TestCase):
    def test_vendored_console_launcher_matches_recorded_hash(self) -> None:
        launcher = vendored_console_launcher_bytes()

        self.assertGreater(len(launcher), 100_000)
        self.assertEqual(
            EXE_WRAP_CONSOLE_X64_SHA256,
            "f1a68e6b71dbe0db7db3e8c151dcb66c10d77469a219f1cb4fb365fe3a78cf10",
        )

    @unittest.skipIf(os.name != "nt", "Windows elevation heuristic check")
    def test_vendored_console_launcher_is_as_invoker(self) -> None:
        with TemporaryDirectory() as temp_dir_str:
            launcher = Path(temp_dir_str) / "demo-installer.exe"
            launcher.write_bytes(vendored_console_launcher_bytes())

            result = subprocess.run(
                [str(launcher)],
                capture_output=True,
                text=True,
                check=False,
            )

        self.assertEqual(1, result.returncode)
        self.assertIn("no embedded config found", result.stderr)

    def test_bootstrap_config_uses_powershell_single_quoted_exe_path(self) -> None:
        config = json.loads(_render_bootstrap_config().decode("utf-8"))

        command = config["command"]
        self.assertEqual("powershell.exe", command[0])
        self.assertEqual("-NoProfile", command[1])
        self.assertIn("-ExecutionPolicy", command)
        self.assertIn("Bypass", command)
        script = command[-1]
        self.assertIn("tar.exe -xf '@{exe_path}' -C $extractDir", script)
        self.assertIn("[guid]::NewGuid().ToString('N')", script)
        self.assertIn("finally", script)
        self.assertIn("Write-Error $_ -ErrorAction Continue", script)
        self.assertIn("Remove-Item -LiteralPath $extractDir", script)
        self.assertIn("exit $exitCode", script)

    def test_installer_exe_contains_exewrap_config_and_stored_zip(self) -> None:
        with TemporaryDirectory() as temp_dir_str:
            temp_dir = Path(temp_dir_str)
            payload = temp_dir / "demo-1.0.zip"
            manifest = temp_dir / "demo-1.0-manifest.json"
            installer = temp_dir / "demo-1.0-installer.exe"
            payload.write_text("payload", encoding="utf-8")
            manifest.write_text('{"name":"Demo"}', encoding="utf-8")

            create_exewrap_zip_installer(
                installer,
                payload_archive=payload,
                manifest_path=manifest,
                app_name="Demo",
                pause_on_exit=False,
                add_uninstaller=True,
                launcher=b"fake-launcher",
            )

            contents = installer.read_bytes()
            self.assertTrue(contents.startswith(b"fake-launcher"))
            start = contents.index(EXE_WRAP_CONFIG_START_MARKER)
            end = contents.index(EXE_WRAP_CONFIG_END_MARKER)
            config = json.loads(
                contents[start + len(EXE_WRAP_CONFIG_START_MARKER) : end].decode(
                    "utf-8"
                )
            )
            self.assertEqual("powershell.exe", config["command"][0])

            with ZipFile(installer) as installer_zip:
                self.assertEqual(
                    {
                        "demo-1.0.zip",
                        "demo-1.0-manifest.json",
                        "install.cmd",
                        "install.ps1",
                        "uninstall.cmd",
                        "uninstall.ps1",
                    },
                    set(installer_zip.namelist()),
                )
                for info in installer_zip.infolist():
                    self.assertEqual(ZIP_STORED, info.compress_type)
                self.assertIn(
                    "powershell.exe -NoProfile -ExecutionPolicy Bypass",
                    installer_zip.read("install.cmd").decode("utf-8"),
                )
                install_ps1 = installer_zip.read("install.ps1").decode("utf-8")
                self.assertIn("tar.exe -xf $PayloadPath -C $StagingDir", install_ps1)
                self.assertIn("New-AppBuilderStartMenuShortcuts", install_ps1)
                self.assertIn("Invoke-AppBuilderHookList", install_ps1)
                self.assertIn("app-builder-manifest.json", install_ps1)

    def test_installer_can_omit_uninstaller(self) -> None:
        with TemporaryDirectory() as temp_dir_str:
            temp_dir = Path(temp_dir_str)
            payload = temp_dir / "demo.zip"
            manifest = temp_dir / "manifest.json"
            installer = temp_dir / "installer.exe"
            payload.write_text("payload", encoding="utf-8")
            manifest.write_text("{}", encoding="utf-8")

            create_exewrap_zip_installer(
                installer,
                payload_archive=payload,
                manifest_path=manifest,
                app_name="Demo",
                pause_on_exit=False,
                add_uninstaller=False,
                launcher=b"fake-launcher",
            )

            with ZipFile(installer) as installer_zip:
                self.assertNotIn("uninstall.cmd", installer_zip.namelist())
                self.assertNotIn("uninstall.ps1", installer_zip.namelist())

    @unittest.skipIf(os.name != "nt", "generated installer scripts target Windows")
    def test_generated_scripts_install_and_uninstall_payload_on_windows(self) -> None:
        with TemporaryDirectory() as temp_dir_str:
            temp_dir = Path(temp_dir_str)
            payload = temp_dir / "demo.zip"
            manifest = temp_dir / "manifest.json"
            installer = temp_dir / "installer.exe"
            install_dir = temp_dir / "installed app"
            extraction_dir = temp_dir / "top-layer"
            extraction_dir.mkdir()

            hook_cmd = temp_dir / "post-install.cmd"
            hook_cmd.write_text(
                "@echo off\n"
                'echo post-install>"%app_builder_install_directory%\\post-install.txt"\n',
                encoding="utf-8",
            )
            with ZipFile(payload, "w") as payload_zip:
                payload_zip.writestr("hello.cmd", "@echo off\necho hello\n")
                payload_zip.write(hook_cmd, "post-install.cmd")
            manifest.write_text(
                json.dumps(
                    {
                        "name": "Demo",
                        "version": "1.0",
                        "install_directory": str(install_dir),
                        "payload_archive": payload.name,
                        "start_menu": [],
                        "install_hooks": {
                            "pre_install": [],
                            "post_install": [["post-install.cmd"]],
                            "pre_uninstall": [],
                            "post_uninstall": [],
                        },
                    }
                ),
                encoding="utf-8",
            )

            create_exewrap_zip_installer(
                installer,
                payload_archive=payload,
                manifest_path=manifest,
                app_name="Demo",
                pause_on_exit=False,
                add_uninstaller=True,
                launcher=b"fake-launcher",
            )

            with ZipFile(installer) as installer_zip:
                installer_zip.extractall(extraction_dir)

            subprocess.run(
                [
                    "cmd.exe",
                    "/D",
                    "/C",
                    "call",
                    str(extraction_dir / "install.cmd"),
                ],
                check=True,
            )
            self.assertTrue((install_dir / "hello.cmd").exists())
            self.assertEqual(
                "post-install",
                (install_dir / "post-install.txt").read_text(encoding="utf-8").strip(),
            )
            self.assertTrue((install_dir / "uninstall.cmd").exists())

            subprocess.run(
                ["cmd.exe", "/D", "/C", "call", str(install_dir / "uninstall.cmd")],
                check=True,
            )
            deadline = time.monotonic() + 10
            while install_dir.exists() and time.monotonic() < deadline:
                time.sleep(0.1)
            self.assertFalse(install_dir.exists())
