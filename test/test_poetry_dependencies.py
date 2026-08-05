from __future__ import annotations

import subprocess
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import ANY, patch

from app_builder.poetry_dependencies import (
    DEV_GROUP,
    MAIN_GROUP,
    LockedPackage,
    PoetryLock,
    ensure_poetry_lock,
    install_locked_poetry_dependencies,
    load_poetry_lock,
    refresh_poetry_lock,
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

    def test_ensure_poetry_lock_verifies_without_refreshing(self) -> None:
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
            [sys.executable, "-m", "poetry", "check", "--lock"],
            cwd=project_root,
            env=ANY,
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(
            "false",
            run.call_args.kwargs["env"]["POETRY_VIRTUALENVS_CREATE"],
        )
        self.assertEqual("1", run.call_args.kwargs["env"]["POETRY_NO_INTERACTION"])

    def test_refresh_poetry_lock_is_explicit(self) -> None:
        with TemporaryDirectory() as temp_dir_str:
            project_root = Path(temp_dir_str)
            (project_root / "pyproject.toml").write_text(
                "[tool.poetry]\nname = 'demo'\nversion = '0.1.0'\n",
                encoding="utf-8",
            )
            (project_root / "poetry.lock").write_text("", encoding="utf-8")
            with patch(
                "app_builder.poetry_dependencies.subprocess.run",
                return_value=subprocess.CompletedProcess([], 0, "", ""),
            ) as run:
                refresh_poetry_lock(project_root)

        self.assertEqual(
            [sys.executable, "-m", "poetry", "lock", "--no-interaction"],
            run.call_args.args[0],
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
                    files=(("attrs.whl", "sha256:" + "a" * 64),),
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
                    files=(("pytest.whl", "sha256:" + "b" * 64),),
                ),
            )
        )

        requirement_text = ""

        def capture_run(command: list[str], *, check: bool) -> None:
            nonlocal requirement_text
            requirement_path = Path(command[command.index("--requirement") + 1])
            requirement_text = requirement_path.read_text(encoding="utf-8")

        with patch(
            "app_builder.poetry_dependencies.subprocess.run",
            side_effect=capture_run,
        ) as run:
            install_locked_poetry_dependencies(
                project_root=project_root,
                python_executable=python_executable,
                poetry_lock=poetry_lock,
                groups={DEV_GROUP},
            )

        run.assert_called_once()
        command = run.call_args.args[0]
        self.assertIn("--require-hashes", command)
        self.assertIn("--requirement", command)
        self.assertIn("https://packages.example.invalid/simple", command)
        self.assertIn("pytest==8.1.1", requirement_text)
        self.assertIn("--hash=sha256:" + "b" * 64, requirement_text)
        self.assertIn(" \\\n    --hash=sha256:", requirement_text)
        self.assertNotIn("\n+", requirement_text)

    def test_missing_lock_tells_user_to_refresh_explicitly(self) -> None:
        with TemporaryDirectory() as temp_dir_str:
            project_root = Path(temp_dir_str)
            (project_root / "pyproject.toml").write_text(
                "[tool.poetry]\n", encoding="utf-8"
            )
            with self.assertRaisesRegex(FileNotFoundError, "app-builder lock"):
                ensure_poetry_lock(project_root)

    def test_rejects_mutable_file_and_directory_dependencies(self) -> None:
        for source_type in ("file", "directory"):
            with self.subTest(source_type=source_type):
                poetry_lock = PoetryLock(
                    packages=(
                        LockedPackage(
                            name="local-demo",
                            version="1.0.0",
                            groups=frozenset({MAIN_GROUP}),
                            optional=False,
                            source={"type": source_type, "url": "../local-demo"},
                        ),
                    )
                )
                with (
                    patch("app_builder.poetry_dependencies.subprocess.run") as run,
                    self.assertRaisesRegex(RuntimeError, "mutable.*source"),
                ):
                    install_locked_poetry_dependencies(
                        project_root=Path("C:/project"),
                        python_executable=Path("C:/python.exe"),
                        poetry_lock=poetry_lock,
                        groups={MAIN_GROUP},
                    )
                run.assert_not_called()


if __name__ == "__main__":
    unittest.main()
