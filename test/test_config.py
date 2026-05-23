from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from app_builder.config import load_config
from app_builder.fileset import build_remap_table, collect_files
from app_builder.schema import ConfigError


class TestConfigLoading(unittest.TestCase):
    def test_loads_new_schema_without_pydantic(self) -> None:
        with TemporaryDirectory() as temp_dir_str:
            temp_dir = Path(temp_dir_str)
            config_path = temp_dir / "app_builder.yaml"
            config_path.write_text(
                """
app_builder_version: v1.0.0
python_bundled: null
python_venv: null
installer:
  name: Demo
  install_directory: "%localappdata%\\\\Demo"
  paths:
    include: [src]
build_hooks: {}
""".strip(),
                encoding="utf-8",
            )
            config = load_config(config_path)

        self.assertEqual("Demo", config.installer.name)
        self.assertIsNone(config.python_bundled)
        self.assertIsNone(config.python_venv)

    def test_legacy_application_yaml_is_rejected(self) -> None:
        with TemporaryDirectory() as temp_dir_str:
            temp_dir = Path(temp_dir_str)
            config_path = temp_dir / "application.yaml"
            config_path.write_text(
                """
app-builder: v0.20.0
application:
  name: Legacy
""".strip(),
                encoding="utf-8",
            )

            with self.assertRaises(ConfigError):
                load_config(config_path)


class TestFileset(unittest.TestCase):
    def test_collect_and_remap_files(self) -> None:
        with TemporaryDirectory() as temp_dir_str:
            temp_dir = Path(temp_dir_str)
            (temp_dir / "src").mkdir()
            (temp_dir / "src" / "main.py").write_text(
                "print('hello')", encoding="utf-8"
            )
            (temp_dir / "README.md").write_text("docs", encoding="utf-8")

            files = collect_files(temp_dir, ["src", "README.md"], [])
            remap = build_remap_table(
                temp_dir, files, [("README.md", "docs/README.md")]
            )

        self.assertEqual(
            {
                "docs/README.md",
                "src/main.py",
            },
            {path.as_posix() for path in remap.values()},
        )
