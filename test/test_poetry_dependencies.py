from __future__ import annotations

import subprocess
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from app_builder.poetry_dependencies import (
    DEV_GROUP,
    MAIN_GROUP,
    LockedPackage,
    PoetryLock,
    ensure_poetry_lock,
    install_locked_poetry_dependencies,
    load_poetry_lock,
)


class TestPoetryDependencies(unittest.TestCase):
    def test_loads_locked_main_and_dev_requirements(self) -> None:
        with TemporaryDirectory() as temp_dir_str:
            project_root = Path(temp_dir_str)
            lock_path = project_root / "poetry.lock"
            lock_path.write_text(
                """
[[package]]
name = "attrs"
version = "23.2.0"
optional = false
python-versions = ">=3.8"
groups = ["main"]

[[package]]
name = "pytest"
version = "8.1.1"
optional = false
python-versions = ">=3.8"
groups = ["dev"]
markers = "python_version >= '3.11'"

[[package]]
name = "optional-extra"
version = "1.0.0"
optional = true
python-versions = ">=3.8"
groups = ["main"]
""".strip(),
                encoding="utf-8",
            )

            poetry_lock = load_poetry_lock(lock_path)

        self.assertEqual(
            ["attrs==23.2.0"],
            poetry_lock.requirements_for_groups(
                {MAIN_GROUP}, project_root=project_root
            ),
        )
        self.assertEqual(
            ["pytest==8.1.1; python_version >= '3.11'"],
            poetry_lock.requirements_for_groups({DEV_GROUP}, project_root=project_root),
        )

    def test_ensure_poetry_lock_uses_app_builder_python_environment(self) -> None:
        with TemporaryDirectory() as temp_dir_str:
            project_root = Path(temp_dir_str)
            (project_root / "pyproject.toml").write_text(
                "[tool.poetry]\nname = 'demo'\nversion = '0.1.0'\n",
                encoding="utf-8",
            )
            (project_root / "poetry.lock").write_text("", encoding="utf-8")

            with patch(
                "app_builder.poetry_dependencies.subprocess.run",
                return_value=subprocess.CompletedProcess(
                    args=[],
                    returncode=0,
                    stdout="",
                    stderr="",
                ),
            ) as run:
                ensure_poetry_lock(project_root)

        run.assert_called_once_with(
            [sys.executable, "-m", "poetry", "lock", "--no-interaction"],
            cwd=project_root,
            check=False,
            capture_output=True,
            text=True,
        )

    def test_missing_pyproject_is_user_readable(self) -> None:
        with TemporaryDirectory() as temp_dir_str:
            with self.assertRaisesRegex(
                FileNotFoundError,
                "Poetry dependencies must be declared in pyproject.toml",
            ):
                ensure_poetry_lock(Path(temp_dir_str))

    def test_installs_locked_group_with_no_dependency_resolution(self) -> None:
        project_root = Path("C:/project")
        python_executable = project_root / "bin" / "python" / "python" / "python.exe"
        poetry_lock = PoetryLock(
            packages=(
                LockedPackage(
                    name="attrs",
                    version="23.2.0",
                    groups=frozenset({MAIN_GROUP}),
                    optional=False,
                ),
                LockedPackage(
                    name="pytest",
                    version="8.1.1",
                    groups=frozenset({DEV_GROUP}),
                    optional=False,
                    source={
                        "type": "legacy",
                        "url": "https://packages.example.invalid/simple",
                    },
                ),
            )
        )

        with patch("app_builder.poetry_dependencies.subprocess.run") as run:
            install_locked_poetry_dependencies(
                project_root=project_root,
                python_executable=python_executable,
                poetry_lock=poetry_lock,
                groups={DEV_GROUP},
            )

        run.assert_called_once_with(
            [
                str(python_executable),
                "-E",
                "-m",
                "pip",
                "install",
                "--upgrade",
                "--no-deps",
                "--no-warn-script-location",
                "--disable-pip-version-check",
                "--extra-index-url",
                "https://packages.example.invalid/simple",
                "pytest==8.1.1",
            ],
            check=True,
        )


if __name__ == "__main__":
    unittest.main()
