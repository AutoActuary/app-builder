from __future__ import annotations

import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
from zipfile import ZipFile

from click.testing import CliRunner

from app_builder.main import main
from app_builder.python_runtime import (
    NuGetPythonPackage,
    PythonVersionNotFoundError,
    _copy_bundled_runtime_support,
    _download_package_to_temp,
    _extract_nuget_python_package,
    _matches_version_pattern,
    _nuget_source_marker_matches,
    _nuget_python_download_url,
    _read_base_site_packages,
    _select_nuget_python_version,
    _venv_matches_bundled_python,
    _write_nuget_source_marker,
    _write_base_site_packages,
)


def _nuget_payload_member(relative_path: str) -> str:
    return "/".join(("tools", relative_path))


class TestNuGetPythonSelection(unittest.TestCase):
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
    def test_download_package_uses_supplied_temporary_directory(self) -> None:
        with TemporaryDirectory() as temp_dir_str:
            temp_dir = Path(temp_dir_str)
            package = NuGetPythonPackage(
                version="3.12.10",
                download_url=_nuget_python_download_url("3.12.10"),
            )

            with patch("app_builder.python_runtime._download_file") as download:
                package_path = _download_package_to_temp(package, temp_dir)

            self.assertEqual(temp_dir / "python.3.12.10.nupkg", package_path)
            download.assert_called_once_with(package.download_url, package_path)

    def test_source_marker_records_nuget_package_origin(self) -> None:
        with TemporaryDirectory() as temp_dir_str:
            python_root = Path(temp_dir_str) / "bin" / "python"
            python_root.mkdir(parents=True)

            _write_nuget_source_marker(
                python_root,
                NuGetPythonPackage(
                    version="3.12.10",
                    download_url=_nuget_python_download_url("3.12.10"),
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
