from __future__ import annotations

import json
import os
import subprocess
import time
import unittest
from importlib.resources import files
from pathlib import Path
from tempfile import TemporaryDirectory
from zipfile import ZIP_STORED, ZipFile

from app_builder.exewrap import (
    EXE_WRAP_CONFIG_END_MARKER,
    EXE_WRAP_CONFIG_START_MARKER,
    EXE_WRAP_CONSOLE_X64_SHA256,
    _read_icon_images,
    _render_icon_group_resource,
    stamp_exe_icon,
    vendored_console_launcher_bytes,
)
from app_builder.installer_bundle import (
    _contains_powershell_here_string_terminator,
    _render_bootstrap_config,
    create_exewrap_zip_installer,
)


def _write_sample_icon(icon_path: Path) -> None:
    icon_path.write_bytes(
        files("app_builder")
        .joinpath("assets")
        .joinpath("app-builder.ico")
        .read_bytes()
    )


def _expected_icon_group_resource(icon_path: Path) -> bytes:
    return _render_icon_group_resource(_read_icon_images(icon_path))


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

    @unittest.skipIf(os.name != "nt", "Windows icon resource update")
    def test_stamp_exe_icon_embeds_ico_group_resource(self) -> None:
        with TemporaryDirectory() as temp_dir_str:
            icon_path = Path(temp_dir_str) / "app.ico"
            _write_sample_icon(icon_path)
            expected_group = _expected_icon_group_resource(icon_path)

            stamped = stamp_exe_icon(vendored_console_launcher_bytes(), icon_path)

        self.assertIn(expected_group, stamped)

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

    def test_manifest_embedding_rejects_powershell_here_string_terminator(
        self,
    ) -> None:
        self.assertTrue(_contains_powershell_here_string_terminator("'@"))
        self.assertTrue(_contains_powershell_here_string_terminator("{\n'@\n}"))
        self.assertFalse(
            _contains_powershell_here_string_terminator('{"value": "\\n\'@\\n"}')
        )

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
                        "install.cmd",
                        "uninstall.cmd",
                    },
                    set(installer_zip.namelist()),
                )
                for info in installer_zip.infolist():
                    self.assertEqual(ZIP_STORED, info.compress_type)
                self.assertNotIn("demo-1.0-manifest.json", installer_zip.namelist())
                self.assertIn(
                    "powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass",
                    installer_zip.read("install.cmd").decode("utf-8"),
                )
                install_cmd = installer_zip.read("install.cmd").decode("utf-8")
                self.assertIn("$EmbeddedManifestJson = @'", install_cmd)
                self.assertIn('"name": "Demo"', install_cmd)
                self.assertIn("tar.exe -xf $PayloadPath -C $StagingDir", install_cmd)
                self.assertIn("Get-AppBuilderExistingInstallKind", install_cmd)
                self.assertIn("Test-AppBuilderLegacyInstall", install_cmd)
                self.assertIn("Invoke-AppBuilderLegacyPreUninstall", install_cmd)
                self.assertIn("Remove-AppBuilderBackupDirectory", install_cmd)
                self.assertIn("Restore-AppBuilderDirectory", install_cmd)
                self.assertIn(
                    "does not use payload files such as version.txt, python-version.txt, or gitinformation.json as install markers",
                    install_cmd,
                )
                self.assertIn("New-AppBuilderStartMenuShortcuts", install_cmd)
                self.assertIn("Invoke-AppBuilderHookList", install_cmd)
                self.assertIn("app-builder-manifest.json", install_cmd)
                uninstall_cmd = installer_zip.read("uninstall.cmd").decode("utf-8")
                self.assertIn("Copy-AppBuilderPostUninstallEntrypoints", uninstall_cmd)
                self.assertIn("Remove-AppBuilderInstallDirectory", uninstall_cmd)
                self.assertNotIn("Start-AppBuilderDirectoryCleanup", uninstall_cmd)

    @unittest.skipIf(os.name != "nt", "Windows icon resource update")
    def test_installer_exe_embeds_configured_icon(self) -> None:
        with TemporaryDirectory() as temp_dir_str:
            temp_dir = Path(temp_dir_str)
            payload = temp_dir / "demo-1.0.zip"
            manifest = temp_dir / "demo-1.0-manifest.json"
            installer = temp_dir / "demo-1.0-installer.exe"
            icon_path = temp_dir / "app.ico"
            payload.write_text("payload", encoding="utf-8")
            manifest.write_text('{"name":"Demo"}', encoding="utf-8")
            _write_sample_icon(icon_path)

            create_exewrap_zip_installer(
                installer,
                payload_archive=payload,
                manifest_path=manifest,
                app_name="Demo",
                pause_on_exit=False,
                add_uninstaller=True,
                icon_path=icon_path,
            )

            contents = installer.read_bytes()
            self.assertIn(_expected_icon_group_resource(icon_path), contents)
            self.assertIn(EXE_WRAP_CONFIG_START_MARKER, contents)
            with ZipFile(installer) as installer_zip:
                self.assertIn("install.cmd", installer_zip.namelist())

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
                self.assertNotIn("install.ps1", installer_zip.namelist())

    @unittest.skipIf(os.name != "nt", "generated installer scripts target Windows")
    def test_generated_scripts_install_and_uninstall_payload_on_windows(self) -> None:
        with TemporaryDirectory() as temp_dir_str:
            temp_dir = Path(temp_dir_str)
            payload = temp_dir / "demo.zip"
            manifest = temp_dir / "manifest.json"
            installer = temp_dir / "installer.exe"
            install_dir = temp_dir / "installed app"
            extraction_dir = temp_dir / "top-layer"
            appdata_dir = temp_dir / "appdata"
            env = os.environ.copy()
            env["APPDATA"] = str(appdata_dir)
            extraction_dir.mkdir()

            hook_cmd = temp_dir / "post-install.cmd"
            post_uninstall_cmd = temp_dir / "post-uninstall.cmd"
            post_uninstall_marker = temp_dir / "post-uninstall.txt"
            hook_cmd.write_text(
                "@echo off\n"
                'echo post-install>"%app_builder_install_directory%\\post-install.txt"\n',
                encoding="utf-8",
            )
            post_uninstall_cmd.write_text(
                "@echo off\n"
                'if exist "%app_builder_install_directory%\\hello.cmd" exit /b 8\n'
                'echo post-uninstall>"%~1"\n',
                encoding="utf-8",
            )
            with ZipFile(payload, "w") as payload_zip:
                payload_zip.writestr("hello.cmd", "@echo off\necho hello\n")
                payload_zip.write(hook_cmd, "post-install.cmd")
                payload_zip.write(post_uninstall_cmd, "post-uninstall.cmd")
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
                            "post_uninstall": [
                                ["post-uninstall.cmd", str(post_uninstall_marker)]
                            ],
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
                env=env,
            )
            self.assertTrue((install_dir / "hello.cmd").exists())
            self.assertEqual(
                "post-install",
                (install_dir / "post-install.txt").read_text(encoding="utf-8").strip(),
            )
            self.assertTrue((install_dir / "uninstall.cmd").exists())
            self.assertTrue((install_dir / "app-builder-manifest.json").exists())

            subprocess.run(
                ["cmd.exe", "/D", "/C", "call", str(install_dir / "uninstall.cmd")],
                check=True,
                env=env,
            )
            deadline = time.monotonic() + 10
            while (
                install_dir.exists() or not post_uninstall_marker.exists()
            ) and time.monotonic() < deadline:
                time.sleep(0.1)
            self.assertFalse(install_dir.exists())
            self.assertTrue(post_uninstall_marker.exists())
            self.assertEqual(
                "post-uninstall",
                post_uninstall_marker.read_text(encoding="utf-8").strip(),
            )

    @unittest.skipIf(os.name != "nt", "generated installer scripts target Windows")
    def test_installer_refuses_directory_with_only_non_contract_payload_files(
        self,
    ) -> None:
        with TemporaryDirectory() as temp_dir_str:
            temp_dir = Path(temp_dir_str)
            payload = temp_dir / "demo.zip"
            manifest = temp_dir / "manifest.json"
            installer = temp_dir / "installer.exe"
            install_dir = temp_dir / "installed app"
            extraction_dir = temp_dir / "top-layer"
            appdata_dir = temp_dir / "appdata"
            env = os.environ.copy()
            env["APPDATA"] = str(appdata_dir)
            extraction_dir.mkdir()
            install_dir.mkdir()
            (install_dir / "version.txt").write_text("0.9", encoding="utf-8")
            (install_dir / "python-version.txt").write_text(
                "pip freeze output", encoding="utf-8"
            )
            (install_dir / "gitinformation.json").write_text("{}", encoding="utf-8")
            with ZipFile(payload, "w") as payload_zip:
                payload_zip.writestr("hello.cmd", "@echo off\necho hello\n")
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
                            "post_install": [],
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

            result = subprocess.run(
                [
                    "cmd.exe",
                    "/D",
                    "/C",
                    "call",
                    str(extraction_dir / "install.cmd"),
                ],
                capture_output=True,
                text=True,
                env=env,
                check=False,
            )

            self.assertNotEqual(0, result.returncode)
            output = result.stderr + result.stdout
            self.assertIn("does not use payload", output)
            self.assertIn("version.txt", output)
            self.assertIn("python-version.txt", output)
            self.assertIn("gitinformation.json", output)
            self.assertIn("install markers", output)
            self.assertTrue((install_dir / "version.txt").exists())
            self.assertTrue((install_dir / "python-version.txt").exists())
            self.assertFalse((install_dir / "hello.cmd").exists())

    @unittest.skipIf(os.name != "nt", "generated installer scripts target Windows")
    def test_installer_adopts_legacy_directory_by_uninstall_contract(self) -> None:
        with TemporaryDirectory() as temp_dir_str:
            temp_dir = Path(temp_dir_str)
            payload = temp_dir / "demo.zip"
            manifest = temp_dir / "manifest.json"
            installer = temp_dir / "installer.exe"
            install_dir = temp_dir / "installed app"
            extraction_dir = temp_dir / "top-layer"
            appdata_dir = temp_dir / "appdata"
            env = os.environ.copy()
            env["APPDATA"] = str(appdata_dir)
            legacy_pre_marker = temp_dir / "legacy-pre-uninstall.txt"
            extraction_dir.mkdir()
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
                "@echo off\n" f'echo legacy-pre>"{legacy_pre_marker}"\n',
                encoding="utf-8",
            )
            (install_dir / "old-file.txt").write_text("old", encoding="utf-8")
            with ZipFile(payload, "w") as payload_zip:
                payload_zip.writestr("hello.cmd", "@echo off\necho hello\n")
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
                            "post_install": [],
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
                env=env,
            )

            self.assertTrue((install_dir / "hello.cmd").exists())
            self.assertTrue((install_dir / "app-builder-manifest.json").exists())
            self.assertFalse((install_dir / "old-file.txt").exists())
            self.assertEqual(
                "legacy-pre",
                legacy_pre_marker.read_text(encoding="utf-8").strip(),
            )

    @unittest.skipIf(os.name != "nt", "generated installer scripts target Windows")
    def test_installer_upgrades_matching_1x_install_and_runs_old_pre_uninstall(
        self,
    ) -> None:
        with TemporaryDirectory() as temp_dir_str:
            temp_dir = Path(temp_dir_str)
            install_dir = temp_dir / "installed app"
            appdata_dir = temp_dir / "appdata"
            env = os.environ.copy()
            env["APPDATA"] = str(appdata_dir)
            marker = temp_dir / "pre-uninstall.txt"
            first_extraction = temp_dir / "first"
            second_extraction = temp_dir / "second"
            first_extraction.mkdir()
            second_extraction.mkdir()

            first_payload = temp_dir / "demo-1.zip"
            first_hook = temp_dir / "pre-uninstall.cmd"
            first_hook.write_text(
                "@echo off\n" f'echo pre-uninstall>"{marker}"\n',
                encoding="utf-8",
            )
            with ZipFile(first_payload, "w") as payload_zip:
                payload_zip.writestr("hello.txt", "one")
                payload_zip.write(first_hook, "pre-uninstall.cmd")
            first_manifest = temp_dir / "manifest-1.json"
            first_manifest.write_text(
                json.dumps(
                    {
                        "name": "Demo",
                        "version": "1.0",
                        "install_directory": str(install_dir),
                        "payload_archive": first_payload.name,
                        "start_menu": [],
                        "install_hooks": {
                            "pre_install": [],
                            "post_install": [],
                            "pre_uninstall": [["pre-uninstall.cmd"]],
                            "post_uninstall": [],
                        },
                    }
                ),
                encoding="utf-8",
            )
            first_installer = temp_dir / "installer-1.exe"
            create_exewrap_zip_installer(
                first_installer,
                payload_archive=first_payload,
                manifest_path=first_manifest,
                app_name="Demo",
                pause_on_exit=False,
                add_uninstaller=True,
                launcher=b"fake-launcher",
            )
            with ZipFile(first_installer) as installer_zip:
                installer_zip.extractall(first_extraction)
            subprocess.run(
                ["cmd.exe", "/D", "/C", "call", str(first_extraction / "install.cmd")],
                check=True,
                env=env,
            )
            self.assertEqual("one", (install_dir / "hello.txt").read_text())

            second_payload = temp_dir / "demo-2.zip"
            with ZipFile(second_payload, "w") as payload_zip:
                payload_zip.writestr("hello.txt", "two")
            second_manifest = temp_dir / "manifest-2.json"
            second_manifest.write_text(
                json.dumps(
                    {
                        "name": "Demo",
                        "version": "2.0",
                        "install_directory": str(install_dir),
                        "payload_archive": second_payload.name,
                        "start_menu": [],
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
            second_installer = temp_dir / "installer-2.exe"
            create_exewrap_zip_installer(
                second_installer,
                payload_archive=second_payload,
                manifest_path=second_manifest,
                app_name="Demo",
                pause_on_exit=False,
                add_uninstaller=True,
                launcher=b"fake-launcher",
            )
            with ZipFile(second_installer) as installer_zip:
                installer_zip.extractall(second_extraction)

            subprocess.run(
                [
                    "cmd.exe",
                    "/D",
                    "/C",
                    "call",
                    str(second_extraction / "install.cmd"),
                ],
                check=True,
                env=env,
            )

            self.assertEqual("two", (install_dir / "hello.txt").read_text())
            self.assertEqual(
                "pre-uninstall", marker.read_text(encoding="utf-8").strip()
            )
