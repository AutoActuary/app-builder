from __future__ import annotations

import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from click.testing import CliRunner

from app_builder.main import main
from app_builder_meta.environment import (
    AppBuilderEnvironment,
    _read_environment,
    get_environment,
)


class TestAppBuilderEnvironment(unittest.TestCase):
    def tearDown(self) -> None:
        get_environment.cache_clear()

    def test_explicit_root_derives_tool_caches_and_preserves_overrides(self) -> None:
        warnings: list[str] = []
        with TemporaryDirectory() as temp_dir_str:
            temp_dir = Path(temp_dir_str)
            environment = _read_environment(
                {
                    "APP_BUILDER_CACHE_ROOT": str(temp_dir / "shared"),
                    "APP_BUILDER_INSTALL_ROOT": str(temp_dir / "install"),
                    "PIP_CACHE_DIR": str(temp_dir / "custom-pip"),
                },
                warning_sink=warnings.append,
            )

            self.assertEqual((temp_dir / "shared").resolve(), environment.cache_root)
            self.assertEqual(
                (temp_dir / "custom-pip").resolve(), environment.pip_cache_dir
            )
            self.assertEqual(
                (temp_dir / "shared" / "poetry").resolve(),
                environment.poetry_cache_dir,
            )
            self.assertEqual((temp_dir / "install").resolve(), environment.install_root)
            subprocess_environment = environment.subprocess_environment(
                {"PATH": "test-path"}
            )

        self.assertEqual([], warnings)
        self.assertEqual("test-path", subprocess_environment["PATH"])
        self.assertEqual(
            str(environment.cache_root),
            subprocess_environment["APP_BUILDER_CACHE_ROOT"],
        )
        self.assertEqual(
            str(environment.pip_cache_dir),
            subprocess_environment["PIP_CACHE_DIR"],
        )
        self.assertEqual(
            str(environment.poetry_cache_dir),
            subprocess_environment["POETRY_CACHE_DIR"],
        )

    def test_default_root_leaves_pip_and_poetry_on_native_defaults(self) -> None:
        environment = _read_environment({}, warning_sink=lambda _message: None)

        self.assertFalse(environment.cache_root_is_explicit)
        self.assertIsNone(environment.pip_cache_dir)
        self.assertIsNone(environment.poetry_cache_dir)

    def test_unknown_app_builder_variable_warns_with_suggestion(self) -> None:
        warnings: list[str] = []

        _read_environment(
            {
                "APP_BUILDER_CAHCE_ROOT": "C:/misspelled",
                "app_builder_name": "hook context",
            },
            warning_sink=warnings.append,
        )

        self.assertEqual(1, len(warnings))
        self.assertIn("APP_BUILDER_CAHCE_ROOT", warnings[0])
        self.assertIn("APP_BUILDER_CACHE_ROOT", warnings[0])

    def test_get_environment_is_lazy_and_cached(self) -> None:
        with TemporaryDirectory() as temp_dir_str:
            get_environment.cache_clear()
            with patch.dict(
                os.environ,
                {"APP_BUILDER_CACHE_ROOT": temp_dir_str},
                clear=False,
            ):
                first = get_environment()
                second = get_environment()

        self.assertIs(first, second)
        self.assertEqual(Path(temp_dir_str).resolve(), first.cache_root)

    def test_download_keys_separate_equal_filenames_from_different_urls(self) -> None:
        environment = AppBuilderEnvironment(
            cache_root=Path("C:/cache"),
            install_root=Path("C:/app-builder"),
            pip_cache_dir=None,
            poetry_cache_dir=None,
        )

        first = environment.download_path("https://one.invalid/files/runtime.zip")
        second = environment.download_path("https://two.invalid/files/runtime.zip")

        self.assertNotEqual(first, second)
        self.assertEqual("runtime.zip", first.name)
        self.assertEqual("runtime.zip", second.name)

    def test_cache_commands_report_the_resolved_contract(self) -> None:
        with TemporaryDirectory() as temp_dir_str:
            cache_root = Path(temp_dir_str) / "cache"
            environment = AppBuilderEnvironment(
                cache_root=cache_root,
                install_root=Path(temp_dir_str) / "app-builder",
                pip_cache_dir=cache_root / "pip",
                poetry_cache_dir=cache_root / "poetry",
            )
            runner = CliRunner()
            with patch("app_builder.main.get_environment", return_value=environment):
                path_result = runner.invoke(main, ["cache", "path"])
                info_result = runner.invoke(main, ["cache", "info"])

        self.assertEqual(0, path_result.exit_code, path_result.output)
        self.assertEqual(str(cache_root), path_result.output.strip())
        self.assertEqual(0, info_result.exit_code, info_result.output)
        self.assertIn(f"Downloads: {cache_root / 'downloads'}", info_result.output)
        self.assertIn(f"pip: {cache_root / 'pip'}", info_result.output)


if __name__ == "__main__":
    unittest.main()
