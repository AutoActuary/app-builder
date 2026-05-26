from __future__ import annotations

import os
import subprocess
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

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
        config = self._load_yaml("""
app_builder_version: v1.0.0
python_bundled: null
python_venv: null
installer:
  name: Demo
  install_directory: "%localappdata%\\\\Demo"
  paths:
    include: [src]
build_hooks: {}
""")

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
        config = self._load_yaml("""
installer:
  name: Demo
  install_directory: "%localappdata%\\\\Demo"
""")

        self.assertIsInstance(config.python_bundled, PythonBundledOptions)
        self.assertIsInstance(config.python_venv, PythonVenvOptions)
        self.assertEqual([], config.build_hooks.pre_dist)
        self.assertEqual([], config.installer.paths.include)
        self.assertEqual([], config.installer.install_hooks.post_install)

    def test_python_dependency_fields_are_not_configured_in_yaml(self) -> None:
        with self.assertRaisesRegex(
            ConfigError,
            r"config\.python_bundled: expected mapping or null, got dict\.",
        ):
            self._load_yaml("""
python_bundled:
  requirements: [pyyaml]
installer:
  name: Demo
  install_directory: "%localappdata%\\\\Demo"
""")

        with self.assertRaisesRegex(
            ConfigError,
            r"config\.python_venv: expected mapping or null, got dict\.",
        ):
            self._load_yaml("""
python_venv:
  requirements_files: [requirements-dev.txt]
installer:
  name: Demo
  install_directory: "%localappdata%\\\\Demo"
""")

    def test_unknown_top_level_keys_are_rejected(self) -> None:
        with self.assertRaisesRegex(
            ConfigError,
            r"config: unknown key 'surprise'\. Expected one of: .*'installer'",
        ):
            self._load_yaml("""
surprise: true
installer:
  name: Demo
  install_directory: "%localappdata%\\\\Demo"
""")

    def test_unknown_nested_keys_are_rejected_with_path(self) -> None:
        with self.assertRaisesRegex(
            ConfigError,
            r"config\.installer: unknown key 'extra'\. Expected one of: .*'paths'",
        ):
            self._load_yaml("""
installer:
  name: Demo
  install_directory: "%localappdata%\\\\Demo"
  extra: value
""")

    def test_non_nullable_null_is_rejected(self) -> None:
        with self.assertRaisesRegex(
            ConfigError,
            r"config\.installer: null is not allowed\. Expected mapping\.",
        ):
            self._load_yaml("""
installer: null
""")

    def test_missing_required_fields_are_rejected(self) -> None:
        with self.assertRaisesRegex(
            ConfigError,
            r"config\.installer\.name: missing required value\. Expected string\.",
        ):
            self._load_yaml("""
installer:
  install_directory: "%localappdata%\\\\Demo"
""")

    def test_hook_commands_accept_argv_lists(self) -> None:
        config = self._load_yaml("""
installer:
  name: Demo
  install_directory: "%localappdata%\\\\Demo"
build_hooks:
  pre_dist:
    - [scripts/pre-build.cmd]
    - [python, -m, pytest]
""")

        self.assertEqual(
            [["scripts/pre-build.cmd"], ["python", "-m", "pytest"]],
            config.build_hooks.pre_dist,
        )

    def test_bare_hook_command_strings_are_rejected(self) -> None:
        with self.assertRaisesRegex(
            ConfigError,
            r"config\.build_hooks\.pre_dist\[0\]: expected list, got str\.",
        ):
            self._load_yaml("""
installer:
  name: Demo
  install_directory: "%localappdata%\\\\Demo"
build_hooks:
  pre_dist:
    - scripts/pre-build.cmd
""")

    def test_bad_hook_command_shapes_are_rejected(self) -> None:
        with self.assertRaisesRegex(
            ConfigError,
            r"config\.build_hooks\.pre_dist\[0\]: expected list, got dict\.",
        ):
            self._load_yaml("""
installer:
  name: Demo
  install_directory: "%localappdata%\\\\Demo"
build_hooks:
  pre_dist:
    - command: scripts/pre-build.cmd
""")

    def test_start_menu_entries_are_strict_mappings(self) -> None:
        config = self._load_yaml("""
installer:
  name: Demo
  install_directory: "%localappdata%\\\\Demo"
  start_menu:
    - target: application-templates/program.cmd
      display_name: Demo
      icon: application-templates/icon.ico
""")

        self.assertEqual(
            "application-templates/program.cmd", config.installer.start_menu[0].target
        )
        self.assertEqual("Demo", config.installer.start_menu[0].display_name)

    def test_legacy_start_menu_shorthand_is_rejected(self) -> None:
        with self.assertRaisesRegex(
            ConfigError,
            r"config\.installer\.start_menu\[0\]: expected mapping, got str\.",
        ):
            self._load_yaml("""
installer:
  name: Demo
  install_directory: "%localappdata%\\\\Demo"
  start_menu:
    - application-templates/program.cmd
""")

    def test_bad_remap_tuple_layout_is_rejected(self) -> None:
        with self.assertRaisesRegex(
            ConfigError,
            r"config\.installer\.paths\.remap\[0\]: expected 2 tuple items, got 1\.",
        ):
            self._load_yaml("""
installer:
  name: Demo
  install_directory: "%localappdata%\\\\Demo"
  paths:
    remap:
      - [README.md]
""")

    def test_bad_payload_format_is_rejected(self) -> None:
        with self.assertRaisesRegex(
            ConfigError,
            r"config\.installer\.payload_format: expected one of: 'zip', '7z'\.",
        ):
            self._load_yaml("""
installer:
  name: Demo
  install_directory: "%localappdata%\\\\Demo"
  payload_format: rar
  paths:
    include: []
""")

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

    def test_interpolates_env_app_version_and_config_values(self) -> None:
        with TemporaryDirectory() as temp_dir_str:
            temp_dir = Path(temp_dir_str)
            config_path = temp_dir / "app_builder.yaml"
            config_path.write_text(
                """
installer:
  name: Demo ${APP.VERSION}
  install_directory: "${ENV.LOCALAPPDATA}\\\\${CONFIG.installer.name}"
  paths:
    include:
      - "src-${APP.VERSION}"
    remap:
      - ["README.md", "docs/${CONFIG.installer.name}.md"]
build_hooks:
  pre_dist:
    - [cmd.exe, /C, echo, "${CONFIG.installer.install_directory}"]
""".strip(),
                encoding="utf-8",
            )

            with patch.dict(
                os.environ, {"LOCALAPPDATA": r"C:\Users\Test\AppData\Local"}
            ):
                config = load_config(config_path, app_version="1.2.3")

        self.assertEqual("Demo 1.2.3", config.installer.name)
        self.assertEqual(
            r"C:\Users\Test\AppData\Local\Demo 1.2.3",
            config.installer.install_directory,
        )
        self.assertEqual(["src-1.2.3"], config.installer.paths.include)
        self.assertEqual(
            [("README.md", "docs/Demo 1.2.3.md")],
            config.installer.paths.remap,
        )
        self.assertEqual(
            [
                [
                    "cmd.exe",
                    "/C",
                    "echo",
                    r"C:\Users\Test\AppData\Local\Demo 1.2.3",
                ]
            ],
            config.build_hooks.pre_dist,
        )

    def test_interpolates_git_values(self) -> None:
        with TemporaryDirectory() as temp_dir_str:
            temp_dir = Path(temp_dir_str)
            subprocess.run(
                ["git", "init"], cwd=temp_dir, check=True, capture_output=True
            )
            (temp_dir / "README.md").write_text("demo\n", encoding="utf-8")
            (temp_dir / "app_builder.yaml").write_text(
                """
installer:
  name: "Demo ${GIT.DESCRIBE}"
  install_directory: "%localappdata%\\\\Demo-${GIT.SHORT_COMMIT}"
  paths:
    include:
      - README.md
      - "${GIT.COMMIT}"
      - "${GIT.BRANCH}"
      - "${GIT.TAG}"
      - "${GIT.IS_DIRTY}"
build_hooks: {}
""".strip(),
                encoding="utf-8",
            )
            subprocess.run(["git", "add", "."], cwd=temp_dir, check=True)
            subprocess.run(
                [
                    "git",
                    "-c",
                    "user.email=test@example.com",
                    "-c",
                    "user.name=Test User",
                    "commit",
                    "-m",
                    "initial",
                ],
                cwd=temp_dir,
                check=True,
                capture_output=True,
            )
            subprocess.run(["git", "tag", "v1.2.3"], cwd=temp_dir, check=True)
            commit = subprocess.run(
                ["git", "rev-parse", "HEAD"],
                cwd=temp_dir,
                check=True,
                capture_output=True,
                text=True,
            ).stdout.strip()
            short_commit = subprocess.run(
                ["git", "rev-parse", "--short", "HEAD"],
                cwd=temp_dir,
                check=True,
                capture_output=True,
                text=True,
            ).stdout.strip()
            branch = subprocess.run(
                ["git", "symbolic-ref", "--short", "HEAD"],
                cwd=temp_dir,
                check=True,
                capture_output=True,
                text=True,
            ).stdout.strip()

            config = load_config(temp_dir / "app_builder.yaml")

        self.assertEqual("Demo v1.2.3", config.installer.name)
        self.assertEqual(
            rf"%localappdata%\Demo-{short_commit}",
            config.installer.install_directory,
        )
        self.assertEqual(
            ["README.md", commit, branch, "v1.2.3", "false"],
            config.installer.paths.include,
        )

    def test_missing_interpolation_variable_is_rejected(self) -> None:
        with TemporaryDirectory() as temp_dir_str:
            config_path = Path(temp_dir_str) / "app_builder.yaml"
            config_path.write_text(
                """
installer:
  name: "${ENV.APP_BUILDER_TEST_MISSING}"
  install_directory: "%localappdata%\\\\Demo"
""".strip(),
                encoding="utf-8",
            )

            with self.assertRaisesRegex(
                ConfigError,
                "environment variable 'APP_BUILDER_TEST_MISSING' is not set",
            ):
                load_config(config_path)

    def test_config_reference_to_non_string_is_rejected(self) -> None:
        with self.assertRaisesRegex(
            ConfigError,
            r"CONFIG\.installer\.paths\.include resolved to list; only string values can be interpolated",
        ):
            self._load_yaml("""
installer:
  name: "${CONFIG.installer.paths.include}"
  install_directory: "%localappdata%\\\\Demo"
  paths:
    include: [src]
""")

    def test_circular_config_references_are_rejected(self) -> None:
        with self.assertRaisesRegex(
            ConfigError,
            "circular interpolation reference detected",
        ):
            self._load_yaml("""
installer:
  name: "${CONFIG.installer.install_directory}"
  install_directory: "${CONFIG.installer.name}"
""")


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
