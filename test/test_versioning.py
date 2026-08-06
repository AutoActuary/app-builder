from __future__ import annotations

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from app_builder.versioning import resolve_app_builder_version


class TestAppBuilderVersioning(unittest.TestCase):
    def test_installed_manifest_version_overrides_package_metadata(self) -> None:
        with TemporaryDirectory() as temp_dir_str:
            install_root = Path(temp_dir_str)
            package_dir = install_root / "app_builder"
            package_dir.mkdir()
            (install_root / "app-builder-manifest.json").write_text(
                json.dumps({"name": "app-builder", "version": "1.7.3"}),
                encoding="utf-8",
            )

            with patch("app_builder.versioning.version", return_value="1.2.0"):
                resolved = resolve_app_builder_version(package_dir)

        self.assertEqual("1.7.3", resolved)

    def test_unrelated_or_corrupt_manifest_does_not_override_metadata(self) -> None:
        with TemporaryDirectory() as temp_dir_str:
            install_root = Path(temp_dir_str)
            package_dir = install_root / "app_builder"
            package_dir.mkdir()
            manifest = install_root / "app-builder-manifest.json"
            for content in ('{"name":"Other","version":"9.0"}', "{"):
                with self.subTest(content=content):
                    manifest.write_text(content, encoding="utf-8")
                    with patch("app_builder.versioning.version", return_value="1.2.0"):
                        self.assertEqual(
                            "1.2.0", resolve_app_builder_version(package_dir)
                        )

    def test_source_pyproject_version_precedes_installed_metadata(self) -> None:
        with TemporaryDirectory() as temp_dir_str:
            project_root = Path(temp_dir_str)
            package_dir = project_root / "app_builder"
            package_dir.mkdir()
            (project_root / "pyproject.toml").write_text(
                '[project]\nname = "app-builder"\nversion = "1.8.0"\n',
                encoding="utf-8",
            )

            with patch("app_builder.versioning.version", return_value="1.2.0"):
                resolved = resolve_app_builder_version(package_dir)

        self.assertEqual("1.8.0", resolved)


if __name__ == "__main__":
    unittest.main()
