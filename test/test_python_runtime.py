from __future__ import annotations

import base64
import json
import os
import tempfile
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
from zipfile import ZipFile

from click.testing import CliRunner

from app_builder.main import main
from app_builder.poetry_dependencies import DEV_GROUP, MAIN_GROUP, PoetryLock
from app_builder.python_runtime import (
    EXE_WRAP_VERSION,
    NuGetPythonPackage,
    PythonEnvironmentMaterializer,
    PythonVersionNotFoundError,
    _copy_bundled_runtime_support,
    _create_self_contained_venv,
    _download_cache_path,
    _exe_wrap_launcher_matches,
    _exe_wrap_python_config,
    _extract_nuget_python_package,
    _EXE_WRAP_DIGESTS,
    _EXE_WRAP_SOURCE_MARKER,
    _install_exe_wrap_python_launchers,
    _matches_version_pattern,
    _load_nuget_python_digest,
    _nuget_source_marker_matches,
    _nuget_python_download_url,
    _read_base_site_packages,
    _select_nuget_python_version,
    _resolve_exe_wrap_package,
    _self_contained_venv_matches,
    _self_contained_venv_python_executable,
    _venv_matches_bundled_python,
    _write_nuget_source_marker,
    _write_base_site_packages,
    ensure_python_environments,
)
from app_builder.schema import PythonVenvOptions

_TEST_NUGET_DIGEST = "sha512:" + "0" * 128


def _nuget_payload_member(relative_path: str) -> str:
    return "/".join(("tools", relative_path))


def _write_fake_exe_wrap_package(package_path: Path) -> None:
    with ZipFile(package_path, "w") as package:
        package.writestr("ExeWrap-console.exe", b"console-launcher")
        package.writestr("ExeWrap-windowed.exe", b"windowed-launcher")


class TestNuGetPythonSelection(unittest.TestCase):
    @patch("app_builder.python_runtime._load_nuget_json")
    def test_reads_sha512_digest_from_registration_catalog_metadata(
        self, load_json: object
    ) -> None:
        digest_bytes = bytes(range(64))
        assert hasattr(load_json, "side_effect")
        load_json.side_effect = [
            {"catalogEntry": "https://api.nuget.org/catalog/python.json"},
            {
                "packageHashAlgorithm": "SHA512",
                "packageHash": base64.b64encode(digest_bytes).decode("ascii"),
            },
        ]

        self.assertEqual(
            "sha512:" + digest_bytes.hex(),
            _load_nuget_python_digest("3.12.10"),
        )

    def test_matches_prefix_and_wildcard_versions(self) -> None:
        self.assertTrue(_matches_version_pattern("3.12", "3.12.10"))
        self.assertTrue(_matches_version_pattern("3.12.*", "3.12.10"))
        self.assertTrue(_matches_version_pattern("3.12.10", "3.12.10.0"))
        self.assertFalse(_matches_version_pattern("3.11", "3.12.10"))

    def test_selects_latest_stable_matching_nuget_version(self) -> None:
        versions = [
            "3.12.9",
            "3.12.10",
            "3.12.11-a1",
            "3.13.1",
        ]

        self.assertEqual(
            "3.12.10",
            _select_nuget_python_version(versions, "3.12"),
        )

    def test_missing_nuget_version_error_suggests_same_minor_versions(self) -> None:
        with self.assertRaises(PythonVersionNotFoundError) as error:
            _select_nuget_python_version(
                ["3.11.9", "3.12.9", "3.12.10", "3.13.1"],
                "3.12.99",
            )

        self.assertIn("NuGet package 'python'", str(error.exception))
        self.assertIn("3.12.10", str(error.exception))
        self.assertIn("3.12.9", str(error.exception))

    def test_nuget_download_url_uses_flat_container_package_layout(self) -> None:
        self.assertEqual(
            "https://api.nuget.org/v3-flatcontainer/python/3.12.10/python.3.12.10.nupkg",
            _nuget_python_download_url("3.12.10"),
        )


class TestNuGetPythonExtraction(unittest.TestCase):
    def test_download_cache_path_uses_os_temp_download_cache(self) -> None:
        self.assertEqual(
            Path(
                tempfile.gettempdir(),
                "app-builder-downloads",
                "python.3.12.10.nupkg",
            ),
            _download_cache_path(_nuget_python_download_url("3.12.10")),
        )

    def test_source_marker_records_nuget_package_origin(self) -> None:
        with TemporaryDirectory() as temp_dir_str:
            python_root = Path(temp_dir_str) / "bin" / "python"
            python_root.mkdir(parents=True)

            _write_nuget_source_marker(
                python_root,
                NuGetPythonPackage(
                    version="3.12.10",
                    download_url=_nuget_python_download_url("3.12.10"),
                    digest=_TEST_NUGET_DIGEST,
                ),
            )

            self.assertTrue(_nuget_source_marker_matches(python_root, "3.12"))
            self.assertTrue(_nuget_source_marker_matches(python_root, "3.12.10"))
            self.assertFalse(_nuget_source_marker_matches(python_root, "3.11"))

    def test_extracts_nuget_payload_into_bundled_python_layout(self) -> None:
        with TemporaryDirectory() as temp_dir_str:
            temp_dir = Path(temp_dir_str)
            package_path = temp_dir / "python.3.12.10.nupkg"
            python_root = temp_dir / "bin" / "python"

            with ZipFile(package_path, "w") as package:
                package.writestr(_nuget_payload_member("python.exe"), "exe")
                package.writestr(_nuget_payload_member("python312.dll"), "dll")
                package.writestr(_nuget_payload_member("Lib/os.py"), "stdlib")
                package.writestr(
                    _nuget_payload_member("Lib/site-packages/pip/__init__.py"),
                    "pip",
                )
                package.writestr("ignored.txt", "ignored")

            _extract_nuget_python_package(package_path, python_root)

            self.assertTrue((python_root / "python" / "python.exe").exists())
            self.assertTrue((python_root / "python" / "python312.dll").exists())
            self.assertTrue((python_root / "python" / "Lib" / "os.py").exists())
            self.assertTrue(
                (python_root / "Lib" / "site-packages" / "pip" / "__init__.py").exists()
            )
            self.assertFalse(
                (
                    python_root
                    / "python"
                    / "Lib"
                    / "site-packages"
                    / "pip"
                    / "__init__.py"
                ).exists()
            )
            self.assertIn(
                "include-system-site-packages = false",
                (python_root / "pyvenv.cfg").read_text(encoding="utf-8"),
            )


class TestExeWrapPythonLaunchers(unittest.TestCase):
    @patch(
        "app_builder.python_runtime._exe_wrap_platform_tag",
        return_value="windows-x64",
    )
    def test_resolves_pinned_exe_wrap_release_asset(self, _platform: object) -> None:
        package = _resolve_exe_wrap_package()

        self.assertEqual("ExeWrap-v2.1.0-windows-x64.zip", package.asset_name)
        self.assertIn("/releases/download/v2.1.0/", package.download_url)
        self.assertEqual(
            "sha256:42c64c90d6620d4942b88e56b615679a8667eaa64902444aa7b21769998936cb",
            package.digest,
        )

    def test_stamps_scripts_python_launchers_with_venv_python_targets(self) -> None:
        with TemporaryDirectory() as temp_dir_str:
            temp_dir = Path(temp_dir_str)
            package_path = temp_dir / "ExeWrap.zip"
            venv_root = temp_dir / "venv"
            _write_fake_exe_wrap_package(package_path)

            _install_exe_wrap_python_launchers(venv_root, package_path=package_path)

            python_launcher = venv_root / "Scripts" / "python.exe"
            pythonw_launcher = venv_root / "Scripts" / "pythonw.exe"
            self.assertTrue(
                _exe_wrap_launcher_matches(
                    python_launcher, _exe_wrap_python_config("python.exe")
                )
            )
            self.assertTrue(
                _exe_wrap_launcher_matches(
                    pythonw_launcher, _exe_wrap_python_config("pythonw.exe")
                )
            )
            self.assertIn(b"console-launcher", python_launcher.read_bytes())
            self.assertIn(b"windowed-launcher", pythonw_launcher.read_bytes())
            self.assertIn(b"@{args}", python_launcher.read_bytes())


class TestBundledPythonCli(unittest.TestCase):
    def test_python_command_materializes_only_bundled_runtime(self) -> None:
        with TemporaryDirectory() as temp_dir_str:
            project_root = Path(temp_dir_str)
            (project_root / ".git").mkdir()
            bundled_python = project_root / "bin" / "python" / "python" / "python.exe"
            runner = CliRunner()
            current_dir = Path.cwd()
            try:
                os.chdir(project_root)
                with (
                    patch(
                        "app_builder.main.ensure_bundled_python",
                        return_value=bundled_python,
                    ) as ensure_bundled,
                    patch("app_builder.main.ensure_python_environments") as ensure_all,
                ):
                    result = runner.invoke(main, ["python"])
            finally:
                os.chdir(current_dir)

        self.assertEqual(0, result.exit_code, result.output)
        ensure_bundled.assert_called_once_with(project_root.resolve())
        ensure_all.assert_not_called()
        self.assertIn(str(bundled_python), result.output)


class TestPoetryDependencyPlacement(unittest.TestCase):
    def test_materializer_exposes_real_bundled_and_venv_boundaries(self) -> None:
        with TemporaryDirectory() as temp_dir_str:
            project_root = Path(temp_dir_str)
            (project_root / "app_builder.yaml").write_text(
                """
python_bundled:
  path: bin/python
python_venv:
  path: venv
installer:
  name: Demo
  install_directory: "%localappdata%\\\\Demo"
""".strip(),
                encoding="utf-8",
            )
            bundled_python = project_root / "bin" / "python" / "python" / "python.exe"
            venv_python = project_root / "venv" / "Scripts" / "python.exe"

            with (
                patch(
                    "app_builder.python_runtime.ensure_poetry_lock",
                    return_value=PoetryLock(packages=()),
                ),
                patch(
                    "app_builder.python_runtime._ensure_bundled_python",
                    return_value=bundled_python,
                ) as ensure_bundled,
                patch(
                    "app_builder.python_runtime._create_venv_from_bundled_python",
                    return_value=venv_python,
                ) as create_venv,
                patch("app_builder.python_runtime.install_locked_poetry_dependencies"),
            ):
                materializer = PythonEnvironmentMaterializer(project_root)

                self.assertEqual(
                    bundled_python,
                    materializer.materialize_bundled(),
                )
                ensure_bundled.assert_called_once()
                create_venv.assert_not_called()

                self.assertEqual(venv_python, materializer.materialize_venv())
                create_venv.assert_called_once_with(
                    project_root / "venv",
                    project_root / "bin" / "python",
                )

                result = materializer.result()

        self.assertEqual(bundled_python, result.python_bundled)
        self.assertEqual(venv_python, result.python_venv)

    def test_main_group_installs_to_bundled_python_and_dev_group_to_venv(self) -> None:
        with TemporaryDirectory() as temp_dir_str:
            project_root = Path(temp_dir_str)
            (project_root / "app_builder.yaml").write_text(
                """
python_bundled:
  path: bin/python
python_venv:
  path: venv
installer:
  name: Demo
  install_directory: "%localappdata%\\\\Demo"
""".strip(),
                encoding="utf-8",
            )
            bundled_python = project_root / "bin" / "python" / "python" / "python.exe"
            venv_python = project_root / "venv" / "Scripts" / "python.exe"
            poetry_lock = PoetryLock(packages=())

            with (
                patch(
                    "app_builder.python_runtime.ensure_poetry_lock",
                    return_value=poetry_lock,
                ) as ensure_lock,
                patch(
                    "app_builder.python_runtime.establish_bundled_python",
                    return_value=bundled_python,
                ),
                patch("app_builder.python_runtime._ensure_pip"),
                patch(
                    "app_builder.python_runtime._create_venv_from_bundled_python",
                    return_value=venv_python,
                ),
                patch(
                    "app_builder.python_runtime.install_locked_poetry_dependencies"
                ) as install_locked,
            ):
                result = ensure_python_environments(project_root)

        self.assertEqual(bundled_python, result.python_bundled)
        self.assertEqual(venv_python, result.python_venv)
        ensure_lock.assert_called_once_with(project_root)
        self.assertEqual(
            [
                {
                    "project_root": project_root,
                    "python_executable": bundled_python,
                    "poetry_lock": poetry_lock,
                    "groups": {MAIN_GROUP},
                },
                {
                    "project_root": project_root,
                    "python_executable": venv_python,
                    "poetry_lock": poetry_lock,
                    "groups": {DEV_GROUP},
                },
            ],
            [call.kwargs for call in install_locked.call_args_list],
        )

    def test_venv_only_materializes_self_contained_python_for_all_groups(self) -> None:
        with TemporaryDirectory() as temp_dir_str:
            project_root = Path(temp_dir_str)
            (project_root / "app_builder.yaml").write_text(
                """
python_bundled: null
python_venv:
  path: venv
  python_version: 3.12.10
installer:
  name: Demo
  install_directory: "%localappdata%\\\\Demo"
""".strip(),
                encoding="utf-8",
            )
            venv_python = project_root / "venv" / "Scripts" / "python.exe"
            poetry_lock = PoetryLock(packages=())

            with (
                patch(
                    "app_builder.python_runtime.ensure_poetry_lock",
                    return_value=poetry_lock,
                ),
                patch(
                    "app_builder.python_runtime._create_self_contained_venv",
                    return_value=venv_python,
                ) as create_venv,
                patch(
                    "app_builder.python_runtime.install_locked_poetry_dependencies"
                ) as install_locked,
            ):
                result = ensure_python_environments(project_root)

        self.assertIsNone(result.python_bundled)
        self.assertEqual(venv_python, result.python_venv)
        create_venv.assert_called_once()
        self.assertEqual(project_root / "venv", create_venv.call_args.args[0])
        self.assertEqual("3.12.10", create_venv.call_args.args[1].python_version)
        install_locked.assert_called_once_with(
            project_root=project_root,
            python_executable=venv_python,
            poetry_lock=poetry_lock,
            groups={MAIN_GROUP, DEV_GROUP},
        )


class TestSelfContainedVenvSupport(unittest.TestCase):
    def test_creates_self_contained_venv_from_nuget_python_layout(self) -> None:
        with TemporaryDirectory() as temp_dir_str:
            temp_dir = Path(temp_dir_str)
            package_path = temp_dir / "python.3.12.10.nupkg"
            venv_root = temp_dir / "venv"
            with ZipFile(package_path, "w") as package:
                package.writestr(_nuget_payload_member("python.exe"), "exe")
                package.writestr(_nuget_payload_member("pythonw.exe"), "exe")
                package.writestr(_nuget_payload_member("python312.dll"), "dll")
                package.writestr(_nuget_payload_member("Lib/os.py"), "stdlib")
                package.writestr(
                    _nuget_payload_member("Lib/site-packages/pip/__init__.py"),
                    "pip",
                )
                package.writestr(_nuget_payload_member("Scripts/pip.exe"), "pip")

            with (
                patch(
                    "app_builder.python_runtime._resolve_nuget_python_package",
                    return_value=NuGetPythonPackage(
                        version="3.12.10",
                        download_url="https://example.invalid/python.3.12.10.nupkg",
                        digest=_TEST_NUGET_DIGEST,
                    ),
                ),
                patch(
                    "app_builder.python_runtime._ensure_downloaded_file",
                    return_value=package_path,
                ),
                patch("app_builder.python_runtime._ensure_pip") as ensure_pip,
                patch(
                    "app_builder.python_runtime._install_exe_wrap_python_launchers"
                ) as install_launchers,
            ):
                python = _create_self_contained_venv(
                    venv_root,
                    PythonVenvOptions(path="venv", python_version="3.12.10"),
                )

            self.assertEqual(venv_root / "Scripts" / "python.exe", python)
            self.assertTrue((venv_root / "python" / "python.exe").exists())
            self.assertTrue((venv_root / "python" / "pythonw.exe").exists())
            self.assertTrue((venv_root / "python" / "Lib" / "os.py").exists())
            self.assertTrue(
                (venv_root / "Lib" / "site-packages" / "pip" / "__init__.py").exists()
            )
            self.assertFalse(
                (
                    venv_root
                    / "python"
                    / "Lib"
                    / "site-packages"
                    / "pip"
                    / "__init__.py"
                ).exists()
            )
            self.assertIn(
                "home =",
                (venv_root / "pyvenv.cfg").read_text(encoding="utf-8"),
            )
            self.assertTrue(_nuget_source_marker_matches(venv_root, "3.12"))
            ensure_pip.assert_called_once_with(
                _self_contained_venv_python_executable(venv_root)
            )
            install_launchers.assert_called_once_with(venv_root)

    def test_self_contained_venv_validation_checks_wrappers(self) -> None:
        with TemporaryDirectory() as temp_dir_str:
            venv_root = Path(temp_dir_str) / "venv"
            real_python = _self_contained_venv_python_executable(venv_root)
            real_python.parent.mkdir(parents=True)
            real_python.write_text("python", encoding="utf-8")
            (venv_root / "Scripts").mkdir()
            (venv_root / "pyvenv.cfg").write_text(
                f"home = {(venv_root / 'python').resolve().as_posix()}\n",
                encoding="utf-8",
            )
            _write_nuget_source_marker(
                venv_root,
                NuGetPythonPackage(
                    version="3.12.10",
                    download_url="https://example.invalid/python.3.12.10.nupkg",
                    digest=_TEST_NUGET_DIGEST,
                ),
            )
            (venv_root / "Scripts" / "python.exe").write_bytes(
                b"base" + _exe_wrap_python_config("python.exe")
            )
            (venv_root / "Scripts" / "pythonw.exe").write_bytes(
                b"base" + _exe_wrap_python_config("pythonw.exe")
            )

            with patch("app_builder.python_runtime._python_matches", return_value=True):
                self.assertFalse(_self_contained_venv_matches(venv_root, "3.12"))

            (venv_root / "Scripts" / "python.exe").write_bytes(
                b"base"
                + b"8c0e8d4c-32af-4fd8-9c68-6a0f97efeb6a"
                + _exe_wrap_python_config("python.exe")
            )
            (venv_root / "Scripts" / "pythonw.exe").write_bytes(
                b"base"
                + b"8c0e8d4c-32af-4fd8-9c68-6a0f97efeb6a"
                + _exe_wrap_python_config("pythonw.exe")
            )
            platform_tag = "windows-x64"
            (venv_root / _EXE_WRAP_SOURCE_MARKER).write_text(
                json.dumps(
                    {
                        "version": EXE_WRAP_VERSION,
                        "asset_name": f"ExeWrap-{EXE_WRAP_VERSION}-{platform_tag}.zip",
                        "digest": _EXE_WRAP_DIGESTS[platform_tag],
                    }
                ),
                encoding="utf-8",
            )

            with (
                patch("app_builder.python_runtime._python_matches", return_value=True),
                patch(
                    "app_builder.python_runtime._exe_wrap_platform_tag",
                    return_value=platform_tag,
                ),
            ):
                self.assertTrue(_self_contained_venv_matches(venv_root, "3.12"))


class TestBundledPythonVenvSupport(unittest.TestCase):
    def test_copies_autory_style_runtime_support_files(self) -> None:
        with TemporaryDirectory() as temp_dir_str:
            temp_dir = Path(temp_dir_str)
            bundled_root = temp_dir / "bin" / "python"
            venv_root = temp_dir / "venv"

            for file_path in [
                bundled_root / "Scripts" / "pip.exe",
                bundled_root / "Scripts" / "python.exe",
                bundled_root / "Lib" / "site-packages" / "package.txt",
                bundled_root / "python" / "python.exe",
                bundled_root / "tools" / "helper.dll",
                bundled_root / "support" / "helper.dll",
            ]:
                file_path.parent.mkdir(parents=True, exist_ok=True)
                file_path.write_text("x", encoding="utf-8")
            (bundled_root / "pyvenv.cfg").write_text("x", encoding="utf-8")

            _copy_bundled_runtime_support(bundled_root, venv_root)

            self.assertTrue((venv_root / "Scripts" / "pip.exe").exists())
            self.assertTrue((venv_root / "support" / "helper.dll").exists())
            self.assertFalse((venv_root / "tools" / "helper.dll").exists())
            self.assertFalse((venv_root / "Scripts" / "python.exe").exists())
            self.assertFalse(
                (venv_root / "Lib" / "site-packages" / "package.txt").exists()
            )
            self.assertFalse((venv_root / "python" / "python.exe").exists())
            self.assertFalse((venv_root / "pyvenv.cfg").exists())

    def test_venv_validation_checks_base_python_and_site_packages(self) -> None:
        with TemporaryDirectory() as temp_dir_str:
            temp_dir = Path(temp_dir_str)
            bundled_root = temp_dir / "bin" / "python"
            venv_root = temp_dir / "venv"
            base_python = bundled_root / "python" / "python.exe"
            base_site_packages = bundled_root / "Lib" / "site-packages"

            base_python.parent.mkdir(parents=True)
            base_python.write_text("x", encoding="utf-8")
            base_site_packages.mkdir(parents=True)
            venv_root.mkdir()
            (venv_root / "pyvenv.cfg").write_text(
                f"executable = {base_python}\n",
                encoding="utf-8",
            )

            _write_base_site_packages(venv_root, base_site_packages)

            self.assertEqual(base_site_packages, _read_base_site_packages(venv_root))
            self.assertTrue(_venv_matches_bundled_python(venv_root, bundled_root))
