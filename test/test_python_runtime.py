from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any, Mapping

from app_builder.python_runtime import (
    _copy_bundled_runtime_support,
    _matches_version_pattern,
    _read_base_site_packages,
    _select_winpython_download_url,
    _venv_matches_bundled_python,
    _write_base_site_packages,
)


class TestWinPythonSelection(unittest.TestCase):
    def test_matches_prefix_and_wildcard_versions(self) -> None:
        self.assertTrue(_matches_version_pattern("3.12", "3.12.10"))
        self.assertTrue(_matches_version_pattern("3.12.*", "3.12.10"))
        self.assertTrue(_matches_version_pattern("3.12.10", "3.12.10.0"))
        self.assertFalse(_matches_version_pattern("3.11", "3.12.10"))

    def test_selects_matching_winpython_asset(self) -> None:
        releases: list[Mapping[str, Any]] = [
            {
                "assets": [
                    {
                        "name": "Winpython64-3.11.9.0dot.exe",
                        "browser_download_url": "https://example.invalid/3.11.exe",
                    },
                    {
                        "name": "Winpython64-3.12.10.0dot.exe",
                        "browser_download_url": "https://example.invalid/3.12.exe",
                    },
                ]
            }
        ]

        self.assertEqual(
            "https://example.invalid/3.12.exe",
            _select_winpython_download_url(releases, "3.12.10"),
        )


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
            ]:
                file_path.parent.mkdir(parents=True, exist_ok=True)
                file_path.write_text("x", encoding="utf-8")
            (bundled_root / "pyvenv.cfg").write_text("x", encoding="utf-8")

            _copy_bundled_runtime_support(bundled_root, venv_root)

            self.assertTrue((venv_root / "Scripts" / "pip.exe").exists())
            self.assertTrue((venv_root / "tools" / "helper.dll").exists())
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
