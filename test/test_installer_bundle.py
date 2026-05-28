from __future__ import annotations

import json
import os
import subprocess
import time
import unittest
from importlib.resources import files
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any, cast
from zipfile import ZIP_STORED, ZipFile

from app_builder.exewrap import (
    EXE_WRAP_CONFIG_END_MARKER,
    EXE_WRAP_CONFIG_START_MARKER,
    EXE_WRAP_CONSOLE_X64_SHA256,
    _read_icon_images,
    _render_icon_group_resource,
    stamp_exe_icon,
    stamp_exe_wrap_config,
    vendored_console_launcher_bytes,
)
from app_builder.installer_bundle import (
    _contains_powershell_here_string_terminator,
    _json_for_embedded_powershell,
    _render_bootstrap_hooks_powershell,
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


def _load_exewrap_config_for_assertion(config: bytes | str) -> dict[str, Any]:
    text = config.decode("utf-8") if isinstance(config, bytes) else config
    return cast(dict[str, Any], json.loads(text))


class TestExeWrapInstallerBundle(unittest.TestCase):
    def test_vendored_console_launcher_matches_recorded_hash(self) -> None:
        launcher = vendored_console_launcher_bytes()

        self.assertGreater(len(launcher), 100_000)
        self.assertEqual(
            EXE_WRAP_CONSOLE_X64_SHA256,
            "520b83bc9663ff9dcdae075fac2e37292eb14572b82a9388db8bcec9d0237393",
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

    @unittest.skipIf(os.name != "nt", "ExeWrap runtime smoke targets Windows")
    def test_vendored_launcher_json_args_round_trips_to_powershell(self) -> None:
        with TemporaryDirectory() as temp_dir_str:
            temp_dir = Path(temp_dir_str)
            marker = temp_dir / "args.json"
            launcher = temp_dir / "args-installer.exe"
            script = (
                "& { "
                "$Argv = '@{args_as_json}' | ConvertFrom-Json; "
                "($Argv | ConvertTo-Json -Compress) | "
                "Set-Content -LiteralPath $env:ARG_MARKER -Encoding UTF8; "
                "exit 0 "
                "}"
            )
            config = json.dumps(
                {
                    "command": [
                        "powershell.exe",
                        "-NoProfile",
                        "-ExecutionPolicy",
                        "Bypass",
                        "-Command",
                        script,
                    ]
                },
                separators=(",", ":"),
            ).encode("utf-8")
            launcher.write_bytes(stamp_exe_wrap_config(config))
            env = os.environ.copy()
            env["ARG_MARKER"] = str(marker)

            result = subprocess.run(
                [
                    str(launcher),
                    "--yes",
                    "space arg",
                    "quote'arg",
                    "semi;arg",
                    "amp&arg",
                    "dollar$arg",
                    "tick`arg",
                ],
                capture_output=True,
                text=True,
                env=env,
                check=False,
            )

            self.assertEqual(0, result.returncode, result.stderr)
            self.assertEqual(
                [
                    "--yes",
                    "space arg",
                    "quote'arg",
                    "semi;arg",
                    "amp&arg",
                    "dollar$arg",
                    "tick`arg",
                ],
                json.loads(marker.read_text(encoding="utf-8-sig")),
            )

    @unittest.skipIf(os.name != "nt", "Windows icon resource update")
    def test_stamp_exe_icon_embeds_ico_group_resource(self) -> None:
        with TemporaryDirectory() as temp_dir_str:
            icon_path = Path(temp_dir_str) / "app.ico"
            _write_sample_icon(icon_path)
            expected_group = _expected_icon_group_resource(icon_path)

            stamped = stamp_exe_icon(vendored_console_launcher_bytes(), icon_path)

        self.assertIn(expected_group, stamped)

    def test_bootstrap_config_uses_powershell_single_quoted_exe_path(self) -> None:
        config = _load_exewrap_config_for_assertion(_render_bootstrap_config())

        command = config["command"]
        self.assertEqual("powershell.exe", command[0])
        self.assertEqual("-NoProfile", command[1])
        self.assertIn("-ExecutionPolicy", command)
        self.assertIn("Bypass", command)
        script = command[-1]
        self.assertIn("tar.exe -xf '@{exe_path}' -C $extractDir", script)
        self.assertIn("bin\\install.ps1", script)
        self.assertIn("$InstallerArgsJson = '@{args_as_json}'", script)
        self.assertIn(
            "[string[]]$InstallerArgs = $InstallerArgsJson | ConvertFrom-Json",
            script,
        )
        self.assertIn("bin\\install.ps1') @InstallerArgs", script)
        self.assertIn("[guid]::NewGuid().ToString('N')", script)
        self.assertIn("finally", script)
        self.assertIn("Write-Error $_ -ErrorAction Continue", script)
        self.assertIn("Remove-Item -LiteralPath $extractDir", script)
        self.assertIn("exit $exitCode", script)

    def test_bootstrap_config_injects_pre_extract_hooks_before_extraction(
        self,
    ) -> None:
        config = _load_exewrap_config_for_assertion(
            _render_bootstrap_config(
                [
                    ["Write-Host", "I'm before extraction"],
                    [
                        "cmd.exe",
                        "/D",
                        "/S",
                        "/C",
                        "echo explicit cmd is allowed",
                    ],
                ]
            )
        )

        script = config["command"][-1]
        self.assertIn("ConvertFrom-Json", script)
        self.assertIn("Invoke-AppBuilderBootstrapCommand", script)
        self.assertIn("I\\u0027m before extraction", script)
        self.assertNotIn("I'm before extraction", script)
        self.assertIn("cmd.exe", script)
        self.assertLess(
            script.index("Invoke-AppBuilderBootstrapCommand $RawCommand"),
            script.index("tar.exe -xf '@{exe_path}'"),
        )

    def test_json_for_embedded_powershell_rewrites_apostrophes(self) -> None:
        payload = _json_for_embedded_powershell(
            [["Write-Host", "I'm safe"], ["Write-Host", "line\n'@\nline"]],
            compact=True,
        )

        self.assertIn("I\\u0027m safe", payload)
        self.assertIn("\\u0027@", payload)
        self.assertNotIn("I'm safe", payload)
        self.assertFalse(_contains_powershell_here_string_terminator(payload))

    @unittest.skipIf(os.name != "nt", "PowerShell bootstrap execution")
    def test_bootstrap_pre_extract_hooks_execute_argv_without_powershell_injection(
        self,
    ) -> None:
        script = _render_bootstrap_hooks_powershell(
            [
                [
                    "Write-Output",
                    "literal; Write-Error should-not-run; I'm data",
                ],
                ["cmd.exe", "/D", "/S", "/C", "echo explicit-cmd"],
            ]
        )

        result = subprocess.run(
            [
                "powershell.exe",
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-Command",
                script,
            ],
            capture_output=True,
            text=True,
            check=False,
        )

        self.assertEqual("", result.stderr)
        self.assertEqual(0, result.returncode)
        self.assertIn("literal; Write-Error should-not-run; I'm data", result.stdout)
        self.assertIn("explicit-cmd", result.stdout)

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
            config = _load_exewrap_config_for_assertion(
                contents[start + len(EXE_WRAP_CONFIG_START_MARKER) : end]
            )
            self.assertEqual("powershell.exe", config["command"][0])

            with ZipFile(installer) as installer_zip:
                self.assertEqual(
                    {
                        "demo-1.0.zip",
                        "install.cmd",
                        "bin/install.ps1",
                        "bin/uninstall.cmd",
                        "bin/uninstall.ps1",
                    },
                    set(installer_zip.namelist()),
                )
                self.assertEqual(
                    [
                        "install.cmd",
                        "bin/install.ps1",
                        "bin/uninstall.cmd",
                        "bin/uninstall.ps1",
                        "demo-1.0.zip",
                    ],
                    installer_zip.namelist(),
                )
                for info in installer_zip.infolist():
                    self.assertEqual(ZIP_STORED, info.compress_type)
                self.assertNotIn("demo-1.0-manifest.json", installer_zip.namelist())
                self.assertIn(
                    'powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0bin\\install.ps1" %*',
                    installer_zip.read("install.cmd").decode("utf-8"),
                )
                install_ps1 = installer_zip.read("bin/install.ps1").decode("utf-8")
                self.assertIn("$EmbeddedManifestJson = @'", install_ps1)
                self.assertIn('"name": "Demo"', install_ps1)
                self.assertIn(
                    "Expand-AppBuilderPayloadArchive $PayloadPath $StagingDir $InstallerRoot",
                    install_ps1,
                )
                self.assertIn("tar.exe -xf $PayloadPath -C $Destination", install_ps1)
                self.assertIn("bin\\7z.exe", install_ps1)
                self.assertIn("Bundled 7z.exe is missing", install_ps1)
                self.assertIn("Get-AppBuilderExistingInstallKind", install_ps1)
                self.assertIn("Test-AppBuilderLegacyInstall", install_ps1)
                self.assertIn("Invoke-AppBuilderLegacyPreUninstall", install_ps1)
                self.assertIn("Remove-AppBuilderBackupDirectory", install_ps1)
                self.assertIn("Restore-AppBuilderDirectory", install_ps1)
                self.assertIn(
                    "does not use payload files such as version.txt, python-version.txt, or gitinformation.json as install markers",
                    install_ps1,
                )
                self.assertIn("New-AppBuilderStartMenuShortcuts", install_ps1)
                self.assertIn("Invoke-AppBuilderHookList", install_ps1)
                self.assertIn("app-builder-manifest.json", install_ps1)
                self.assertIn("Confirm-AppBuilderAction", install_ps1)
                self.assertIn("Continue installing", install_ps1)
                self.assertIn("Wait-AppBuilderBeforeExit", install_ps1)
                self.assertIn("--yes", install_ps1)
                self.assertIn("--no-wait", install_ps1)
                self.assertNotIn("-noninteractive", install_ps1)
                self.assertNotIn("--no-prompt", install_ps1)
                self.assertNotIn("-nowait", install_ps1)
                self.assertNotIn("--cli", install_ps1)
                self.assertNotIn("-cli", install_ps1)
                self.assertIn("Press Enter to close now", install_ps1)
                self.assertIn("[ConsoleKey]::Enter", install_ps1)
                self.assertNotIn("Press any key", install_ps1)
                uninstall_cmd = installer_zip.read("bin/uninstall.cmd").decode("utf-8")
                self.assertIn("-File \"%~dp0uninstall.ps1\" %*", uninstall_cmd)
                uninstall_ps1 = installer_zip.read("bin/uninstall.ps1").decode("utf-8")
                self.assertIn("Copy-AppBuilderPostUninstallEntrypoints", uninstall_ps1)
                self.assertIn("Remove-AppBuilderInstallDirectory", uninstall_ps1)
                self.assertIn("Continue uninstalling", uninstall_ps1)
                self.assertNotIn("Start-AppBuilderDirectoryCleanup", uninstall_ps1)

    def test_manifest_embedding_rewrites_apostrophes_in_generated_scripts(
        self,
    ) -> None:
        with TemporaryDirectory() as temp_dir_str:
            temp_dir = Path(temp_dir_str)
            payload = temp_dir / "demo-1.0.zip"
            manifest = temp_dir / "demo-1.0-manifest.json"
            installer = temp_dir / "demo-1.0-installer.exe"
            payload.write_text("payload", encoding="utf-8")
            manifest.write_text(
                json.dumps(
                    {
                        "name": "I'm Demo",
                        "install_hooks": {
                            "pre_install": [["Write-Host", "it's ok"]]
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
                install_ps1 = installer_zip.read("bin/install.ps1").decode("utf-8")
                uninstall_ps1 = installer_zip.read("bin/uninstall.ps1").decode(
                    "utf-8"
                )

        self.assertIn("I\\u0027m Demo", install_ps1)
        self.assertIn("it\\u0027s ok", install_ps1)
        self.assertNotIn("I'm Demo", install_ps1)
        self.assertNotIn("it's ok", install_ps1)
        self.assertNotIn("I\\u0027m Demo", uninstall_ps1)

    def test_installer_can_include_extra_top_layer_files(self) -> None:
        with TemporaryDirectory() as temp_dir_str:
            temp_dir = Path(temp_dir_str)
            payload = temp_dir / "demo.7z"
            manifest = temp_dir / "manifest.json"
            installer = temp_dir / "installer.exe"
            sevenzip_exe = temp_dir / "7z.exe"
            sevenzip_dll = temp_dir / "7z.dll"
            payload.write_text("payload", encoding="utf-8")
            manifest.write_text("{}", encoding="utf-8")
            sevenzip_exe.write_text("exe", encoding="utf-8")
            sevenzip_dll.write_text("dll", encoding="utf-8")

            create_exewrap_zip_installer(
                installer,
                payload_archive=payload,
                manifest_path=manifest,
                app_name="Demo",
                pause_on_exit=False,
                add_uninstaller=True,
                top_layer_files={
                    sevenzip_exe: "bin/7z.exe",
                    sevenzip_dll: "bin/7z.dll",
                },
                launcher=b"fake-launcher",
            )

            with ZipFile(installer) as installer_zip:
                self.assertIn("demo.7z", installer_zip.namelist())
                self.assertEqual("exe", installer_zip.read("bin/7z.exe").decode())
                self.assertEqual("dll", installer_zip.read("bin/7z.dll").decode())

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
                self.assertNotIn("bin/uninstall.cmd", installer_zip.namelist())
                self.assertNotIn("bin/uninstall.ps1", installer_zip.namelist())
                self.assertIn("bin/install.ps1", installer_zip.namelist())

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
                    "--yes",
                ],
                check=True,
                env=env,
            )
            self.assertTrue((install_dir / "hello.cmd").exists())
            self.assertEqual(
                "post-install",
                (install_dir / "post-install.txt").read_text(encoding="utf-8").strip(),
            )
            self.assertTrue((install_dir / "bin" / "uninstall.cmd").exists())
            self.assertTrue((install_dir / "bin" / "uninstall.ps1").exists())
            self.assertTrue((install_dir / "app-builder-manifest.json").exists())

            subprocess.run(
                [
                    "cmd.exe",
                    "/D",
                    "/C",
                    "call",
                    str(install_dir / "bin" / "uninstall.cmd"),
                    "--yes",
                ],
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
                    "--yes",
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
                    "--yes",
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
                [
                    "cmd.exe",
                    "/D",
                    "/C",
                    "call",
                    str(first_extraction / "install.cmd"),
                    "--yes",
                ],
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
                    "--yes",
                ],
                check=True,
                env=env,
            )

            self.assertEqual("two", (install_dir / "hello.txt").read_text())
            self.assertEqual(
                "pre-uninstall", marker.read_text(encoding="utf-8").strip()
            )
