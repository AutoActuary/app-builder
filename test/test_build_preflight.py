from __future__ import annotations

import subprocess
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from app_builder.build_preflight import validate_build_configuration
from app_builder.schema import (
    AppBuilderConfig,
    ConfigError,
    InstallerOptions,
    PythonBundledOptions,
    load_app_builder_config,
)


class TestBuildPreflight(unittest.TestCase):
    def test_accepts_normal_user_local_install_and_exact_runtime(self) -> None:
        with TemporaryDirectory() as temp_dir_str:
            project_root = Path(temp_dir_str)
            subprocess.run(
                ["git", "init"], cwd=project_root, check=True, capture_output=True
            )
            config = AppBuilderConfig(
                installer=InstallerOptions(
                    name="Demo App",
                    install_directory=r"%localappdata%\Acme\Demo App",
                )
            )

            validate_build_configuration(project_root, config, version="1.2.3")

    def test_rejects_dangerous_identity_install_root_and_runtime_prefix(self) -> None:
        with TemporaryDirectory() as temp_dir_str:
            project_root = Path(temp_dir_str)
            subprocess.run(
                ["git", "init"], cwd=project_root, check=True, capture_output=True
            )
            cases = (
                (
                    AppBuilderConfig(
                        installer=InstallerOptions(
                            name="Bad:Name",
                            install_directory=r"%localappdata%\Demo",
                        )
                    ),
                    "installer.name",
                ),
                (
                    AppBuilderConfig(
                        installer=InstallerOptions(
                            name="Demo", install_directory=r"%TEMP%\Demo"
                        )
                    ),
                    "rooted only",
                ),
                (
                    AppBuilderConfig(
                        installer=InstallerOptions(
                            name="Demo", install_directory=r"%LOCALAPPDATA%"
                        )
                    ),
                    "leading percent-style",
                ),
                (
                    AppBuilderConfig(
                        installer=InstallerOptions(
                            name="Demo", install_directory=r"%LOCALAPPDATA%\Demo"
                        ),
                        python_bundled=PythonBundledOptions(python_version="3.12"),
                    ),
                    "supported prerelease selector",
                ),
            )
            for config, expected in cases:
                with self.subTest(expected=expected):
                    with self.assertRaisesRegex(ValueError, expected):
                        validate_build_configuration(
                            project_root, config, version="1.2.3"
                        )

    def test_rejects_invalid_release_ref_and_empty_hook_argv(self) -> None:
        with TemporaryDirectory() as temp_dir_str:
            project_root = Path(temp_dir_str)
            subprocess.run(
                ["git", "init"], cwd=project_root, check=True, capture_output=True
            )
            config = AppBuilderConfig(
                installer=InstallerOptions(
                    name="Demo", install_directory=r"%LOCALAPPDATA%\Demo"
                )
            )
            with self.assertRaisesRegex(ValueError, "Git tag"):
                validate_build_configuration(project_root, config, version="bad..tag")

            config.build_hooks.pre_dist = [[]]
            with self.assertRaisesRegex(ValueError, r"argv\[0\]"):
                validate_build_configuration(project_root, config, version="1.2.3")

    def test_config_loader_rejects_non_exact_python_version(self) -> None:
        with self.assertRaisesRegex(ConfigError, "expected major.minor.patch"):
            load_app_builder_config(
                {
                    "python_bundled": {"python_version": "3.12"},
                    "installer": {
                        "name": "Demo",
                        "install_directory": r"%LOCALAPPDATA%\Demo",
                    },
                }
            )

    def test_rejects_write_directories_outside_project_and_protected_installs(
        self,
    ) -> None:
        with TemporaryDirectory() as temp_dir_str:
            project_root = Path(temp_dir_str)
            subprocess.run(
                ["git", "init"], cwd=project_root, check=True, capture_output=True
            )
            config = AppBuilderConfig(
                installer=InstallerOptions(
                    name="Demo",
                    install_directory=r"%LOCALAPPDATA%\Demo",
                    dist="../dist",
                )
            )
            with self.assertRaisesRegex(ValueError, "project-relative subdirectory"):
                validate_build_configuration(project_root, config, version="1.2.3")

            config.installer.dist = "dist"
            config.python_bundled = PythonBundledOptions(
                path="../python", python_version="3.12.10"
            )
            with self.assertRaisesRegex(ValueError, "project-relative subdirectory"):
                validate_build_configuration(project_root, config, version="1.2.3")

            config.python_bundled = None
            config.installer.install_directory = r"C:\Windows\Demo"
            with patch.dict("os.environ", {"WINDIR": r"C:\Windows"}, clear=False):
                with self.assertRaisesRegex(ValueError, "protected Windows"):
                    validate_build_configuration(project_root, config, version="1.2.3")

    def test_preflight_accepts_supported_prerelease_selectors(self) -> None:
        with TemporaryDirectory() as temp_dir_str:
            project_root = Path(temp_dir_str)
            subprocess.run(
                ["git", "init"], cwd=project_root, check=True, capture_output=True
            )
            for version in ("3.15.0b4", "3.15.0rc1", "3.15.0-beta", "3.15.0-rc.2"):
                with self.subTest(version=version):
                    validate_build_configuration(
                        project_root,
                        AppBuilderConfig(
                            installer=InstallerOptions(
                                name="Demo",
                                install_directory=r"%LOCALAPPDATA%\Demo",
                            ),
                            python_bundled=PythonBundledOptions(python_version=version),
                        ),
                        version="1.2.3",
                    )

    def test_rejects_install_directory_traversal_before_and_after_normalization(
        self,
    ) -> None:
        with TemporaryDirectory() as temp_dir_str:
            project_root = Path(temp_dir_str)
            subprocess.run(
                ["git", "init"], cwd=project_root, check=True, capture_output=True
            )
            config = AppBuilderConfig(
                installer=InstallerOptions(
                    name="Demo",
                    install_directory=r"%LOCALAPPDATA%\..\..\Windows\Demo",
                )
            )
            with self.assertRaisesRegex(ValueError, "parent-directory traversal"):
                validate_build_configuration(project_root, config, version="1.2.3")

            config.installer.install_directory = r"C:\harmless-name\.."
            with self.assertRaisesRegex(ValueError, "parent-directory traversal"):
                validate_build_configuration(project_root, config, version="1.2.3")


if __name__ == "__main__":
    unittest.main()
