from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from app_builder.config import load_config
from app_builder.fileset import build_remap_table, collect_files
from app_builder.schema import (
    AppBuilderConfig,
    ConfigError,
    PythonBundledOptions,
    PythonVenvOptions,
)


class TestConfigLoading(unittest.TestCase):
    def _load_yaml(self, text: str) -> AppBuilderConfig:
        with TemporaryDirectory() as temp_dir_str:
            temp_dir = Path(temp_dir_str)
            config_path = temp_dir / "app_builder.yaml"
            config_path.write_text(text.strip(), encoding="utf-8")
            return load_config(config_path)

    def test_loads_new_schema_without_pydantic(self) -> None:
        config = self._load_yaml(
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
"""
        )

        self.assertEqual("Demo", config.installer.name)
        self.assertIsNone(config.python_bundled)
        self.assertIsNone(config.python_venv)

    def test_hook_commands_are_argv_lists_and_remap_pairs_are_tuples(self) -> None:
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
  install_hooks:
    pre_install:
      - [cmd, /c, echo, install]
  paths:
    include: [src]
    remap:
      - [README.md, docs/README.md]
build_hooks:
  pre_process:
    - [python, scripts/build.py, --fast]
""".strip(),
                encoding="utf-8",
            )
            config = load_config(config_path)

        self.assertEqual(
            [["cmd", "/c", "echo", "install"]],
            config.installer.install_hooks.pre_install,
        )
        self.assertEqual(
            [["python", "scripts/build.py", "--fast"]],
            config.build_hooks.pre_process,
        )
        self.assertEqual(
            [("README.md", "docs/README.md")],
            config.installer.paths.remap,
        )

    def test_hook_commands_reject_bare_strings(self) -> None:
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
build_hooks:
  pre_process:
    - cmd /c echo invalid
""".strip(),
                encoding="utf-8",
            )

            with self.assertRaisesRegex(
                ConfigError,
                r"config\.build_hooks\.pre_process\[0\]: expected list, got str\.",
            ):
                load_config(config_path)

    def test_missing_defaults_materialize_as_dataclasses(self) -> None:
        config = self._load_yaml(
            """
installer:
  name: Demo
  install_directory: "%localappdata%\\\\Demo"
"""
        )

        self.assertIsInstance(config.python_bundled, PythonBundledOptions)
        self.assertIsInstance(config.python_venv, PythonVenvOptions)
        self.assertEqual([], config.build_hooks.pre_dist)
        self.assertEqual([], config.installer.paths.include)
        self.assertEqual([], config.installer.install_hooks.post_install)

    def test_unknown_top_level_keys_are_rejected(self) -> None:
        with self.assertRaisesRegex(
            ConfigError,
            r"config: unknown key 'surprise'\. Expected one of: .*'installer'",
        ):
            self._load_yaml(
                """
surprise: true
installer:
  name: Demo
  install_directory: "%localappdata%\\\\Demo"
"""
            )

    def test_unknown_nested_keys_are_rejected_with_path(self) -> None:
        with self.assertRaisesRegex(
            ConfigError,
            r"config\.installer: unknown key 'extra'\. Expected one of: .*'paths'",
        ):
            self._load_yaml(
                """
installer:
  name: Demo
  install_directory: "%localappdata%\\\\Demo"
  extra: value
"""
            )

    def test_non_nullable_null_is_rejected(self) -> None:
        with self.assertRaisesRegex(
            ConfigError,
            r"config\.installer: null is not allowed\. Expected mapping\.",
        ):
            self._load_yaml(
                """
installer: null
"""
            )

    def test_missing_required_fields_are_rejected(self) -> None:
        with self.assertRaisesRegex(
            ConfigError,
            r"config\.installer\.name: missing required value\. Expected string\.",
        ):
            self._load_yaml(
                """
installer:
  install_directory: "%localappdata%\\\\Demo"
"""
            )

    def test_hook_commands_accept_argv_lists(self) -> None:
        config = self._load_yaml(
            """
installer:
  name: Demo
  install_directory: "%localappdata%\\\\Demo"
build_hooks:
  pre_dist:
    - [scripts/pre-build.cmd]
    - [python, -m, pytest]
"""
        )

        self.assertEqual(
            [["scripts/pre-build.cmd"], ["python", "-m", "pytest"]],
            config.build_hooks.pre_dist,
        )

    def test_bare_hook_command_strings_are_rejected(self) -> None:
        with self.assertRaisesRegex(
            ConfigError,
            r"config\.build_hooks\.pre_dist\[0\]: expected list, got str\.",
        ):
            self._load_yaml(
                """
installer:
  name: Demo
  install_directory: "%localappdata%\\\\Demo"
build_hooks:
  pre_dist:
    - scripts/pre-build.cmd
"""
            )

    def test_bad_hook_command_shapes_are_rejected(self) -> None:
        with self.assertRaisesRegex(
            ConfigError,
            r"config\.build_hooks\.pre_dist\[0\]: expected list, got dict\.",
        ):
            self._load_yaml(
                """
installer:
  name: Demo
  install_directory: "%localappdata%\\\\Demo"
build_hooks:
  pre_dist:
    - command: scripts/pre-build.cmd
"""
            )

    def test_start_menu_entries_are_strict_mappings(self) -> None:
        config = self._load_yaml(
            """
installer:
  name: Demo
  install_directory: "%localappdata%\\\\Demo"
  start_menu:
    - target: application-templates/program.cmd
      display_name: Demo
      icon: application-templates/icon.ico
"""
        )

        self.assertEqual(
            "application-templates/program.cmd", config.installer.start_menu[0].target
        )
        self.assertEqual("Demo", config.installer.start_menu[0].display_name)

    def test_legacy_start_menu_shorthand_is_rejected(self) -> None:
        with self.assertRaisesRegex(
            ConfigError,
            r"config\.installer\.start_menu\[0\]: expected mapping, got str\.",
        ):
            self._load_yaml(
                """
installer:
  name: Demo
  install_directory: "%localappdata%\\\\Demo"
  start_menu:
    - application-templates/program.cmd
"""
            )

    def test_bad_remap_tuple_layout_is_rejected(self) -> None:
        with self.assertRaisesRegex(
            ConfigError,
            r"config\.installer\.paths\.remap\[0\]: expected 2 tuple items, got 1\.",
        ):
            self._load_yaml(
                """
installer:
  name: Demo
  install_directory: "%localappdata%\\\\Demo"
  paths:
    remap:
      - [README.md]
"""
            )

    def test_legacy_application_yaml_is_rejected(self) -> None:
        with TemporaryDirectory() as temp_dir_str:
            temp_dir = Path(temp_dir_str)
            config_path = temp_dir / "application.yaml"
            config_path.write_text(
                """
app-builder: v0.20.0
Application:
  name: Legacy
""".strip(),
                encoding="utf-8",
            )

            with self.assertRaisesRegex(
                ConfigError,
                r"config: legacy application\.yaml layout is not supported\.",
            ):
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
