from __future__ import annotations

import json
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
            "e272dcbb319cd4e1c18da20211cb8f6e17b9c2b386b1eb68c63e53ac17d9540a",
        )

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
                        "uninstall.cmd",
                    },
                    set(installer_zip.namelist()),
                )
                for info in installer_zip.infolist():
                    self.assertEqual(ZIP_STORED, info.compress_type)
                self.assertIn(
                    "Payload archive: demo-1.0.zip",
                    installer_zip.read("install.cmd").decode("utf-8"),
                )

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
