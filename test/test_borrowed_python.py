from __future__ import annotations

import subprocess
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from app_builder.build import build_release
from app_builder.poetry_dependencies import MAIN_GROUP, PoetryLock
from app_builder.python_runtime import (
    _ensure_bundled_python,
    _write_dependency_state,
    borrowed_python_home,
    establish_bundled_python,
)
from app_builder.schema import PythonBundledOptions


class BorrowedRuntimeFixture:
    def __init__(self, root: Path) -> None:
        self.project_root = root / "worktree"
        self.runtime_root = self.project_root / "bin" / "python"
        self.source_root = root / "main" / "bin" / "python"
        self.home = self.source_root / "python"
        self.runtime_root.mkdir(parents=True)
        (self.runtime_root / "python").mkdir()
        self.home.mkdir(parents=True)
        (self.runtime_root / "python" / "python.exe").write_bytes(b"redirector")
        (self.home / "python.exe").write_bytes(b"python")
        (self.runtime_root / "pyvenv.cfg").write_text(
            f"home = {self.home}\ninclude-system-site-packages = false\n",
            encoding="utf-8",
        )

    @property
    def options(self) -> PythonBundledOptions:
        return PythonBundledOptions(
            path="bin/python",
            python_version="3.12.10",
        )


class TestBorrowedPython(unittest.TestCase):
    def test_borrowed_python_home_only_accepts_external_home(self) -> None:
        with TemporaryDirectory() as temp_dir_str:
            fixture = BorrowedRuntimeFixture(Path(temp_dir_str))
            self.assertEqual(
                fixture.home.resolve(), borrowed_python_home(fixture.runtime_root)
            )

            self_contained = fixture.project_root / "self-contained"
            self_contained.mkdir()
            (self_contained / "pyvenv.cfg").write_text(
                f"home = {self_contained / 'python'}\n",
                encoding="utf-8",
            )
            self.assertIsNone(borrowed_python_home(self_contained))

    def test_establish_preserves_healthy_borrowed_runtime(self) -> None:
        with TemporaryDirectory() as temp_dir_str:
            fixture = BorrowedRuntimeFixture(Path(temp_dir_str))
            expected_python = fixture.runtime_root / "python" / "python.exe"
            with (
                patch("app_builder.python_runtime._python_matches", return_value=True),
                patch("app_builder.python_runtime._prepare_runtime_launchers"),
                patch("app_builder.python_runtime.subprocess.run"),
                patch(
                    "app_builder.python_runtime._bundled_runtime_matches",
                    side_effect=AssertionError("borrowed runtime must not rebuild"),
                ),
                patch(
                    "app_builder.python_runtime._build_bundled_runtime_at",
                    side_effect=AssertionError("borrowed runtime must not rebuild"),
                ),
            ):
                actual_python = establish_bundled_python(
                    fixture.project_root,
                    fixture.options,
                )

            self.assertEqual(expected_python, actual_python)

    def test_unhealthy_borrowed_runtime_fails_without_rebuild(self) -> None:
        with TemporaryDirectory() as temp_dir_str:
            fixture = BorrowedRuntimeFixture(Path(temp_dir_str))
            (fixture.runtime_root / "python" / "python.exe").unlink()
            with (
                patch(
                    "app_builder.python_runtime._build_bundled_runtime_at",
                    side_effect=AssertionError("borrowed runtime must not rebuild"),
                ),
                self.assertRaisesRegex(
                    RuntimeError,
                    "missing its nested executable.*main checkout",
                ),
            ):
                establish_bundled_python(fixture.project_root, fixture.options)

    def test_borrowed_runtime_health_failure_does_not_rebuild(self) -> None:
        with TemporaryDirectory() as temp_dir_str:
            fixture = BorrowedRuntimeFixture(Path(temp_dir_str))
            with (
                patch("app_builder.python_runtime._python_matches", return_value=True),
                patch(
                    "app_builder.python_runtime.subprocess.run",
                    side_effect=subprocess.CalledProcessError(1, "python"),
                ),
                patch(
                    "app_builder.python_runtime._build_bundled_runtime_at",
                    side_effect=AssertionError("borrowed runtime must not rebuild"),
                ),
                self.assertRaisesRegex(RuntimeError, "missing, unhealthy"),
            ):
                establish_bundled_python(fixture.project_root, fixture.options)

    def test_dependency_install_is_local_when_external_state_differs(self) -> None:
        with TemporaryDirectory() as temp_dir_str:
            fixture = BorrowedRuntimeFixture(Path(temp_dir_str))
            desired_lock = PoetryLock(
                packages=(),
                sha256="desired-lock",
                content_hash="desired-content",
            )
            source_lock = PoetryLock(
                packages=(),
                sha256="source-lock",
                content_hash="source-content",
            )
            _write_dependency_state(fixture.runtime_root, desired_lock, {MAIN_GROUP})
            _write_dependency_state(fixture.source_root, source_lock, {MAIN_GROUP})
            source_state_before = (
                fixture.source_root / ".app-builder-dependencies.json"
            ).read_text()

            with (
                patch("app_builder.python_runtime._python_matches", return_value=True),
                patch("app_builder.python_runtime._prepare_runtime_launchers"),
                patch("app_builder.python_runtime._ensure_pip"),
                patch("app_builder.python_runtime.subprocess.run"),
                patch(
                    "app_builder.python_runtime.install_locked_poetry_dependencies"
                ) as install,
            ):
                actual_python = _ensure_bundled_python(
                    fixture.project_root,
                    fixture.options,
                    desired_lock,
                )

            self.assertEqual(
                fixture.runtime_root / "python" / "python.exe", actual_python
            )
            install.assert_called_once_with(
                project_root=fixture.project_root,
                python_executable=actual_python,
                poetry_lock=desired_lock,
                groups={MAIN_GROUP},
            )
            self.assertEqual(
                source_state_before,
                (fixture.source_root / ".app-builder-dependencies.json").read_text(),
            )
            self.assertTrue(
                (fixture.runtime_root / ".app-builder-dependencies.json").is_file()
            )
            self.assertFalse(
                (fixture.runtime_root / ".app-builder-python-source.json").exists()
            )

    def test_dependency_install_is_noop_only_when_both_states_match(self) -> None:
        with TemporaryDirectory() as temp_dir_str:
            fixture = BorrowedRuntimeFixture(Path(temp_dir_str))
            desired_lock = PoetryLock(
                packages=(),
                sha256="desired-lock",
                content_hash="desired-content",
            )
            _write_dependency_state(fixture.runtime_root, desired_lock, {MAIN_GROUP})
            _write_dependency_state(fixture.source_root, desired_lock, {MAIN_GROUP})

            with (
                patch("app_builder.python_runtime._python_matches", return_value=True),
                patch("app_builder.python_runtime._prepare_runtime_launchers"),
                patch("app_builder.python_runtime.subprocess.run"),
                patch(
                    "app_builder.python_runtime.install_locked_poetry_dependencies"
                ) as install,
            ):
                _ensure_bundled_python(
                    fixture.project_root,
                    fixture.options,
                    desired_lock,
                )

            install.assert_not_called()

    def test_release_rejects_borrowed_runtime_before_dependency_hooks(self) -> None:
        with TemporaryDirectory() as temp_dir_str:
            fixture = BorrowedRuntimeFixture(Path(temp_dir_str))
            (fixture.project_root / "app_builder.yaml").write_text(
                """
python_bundled:
  path: bin/python
  python_version: 3.12.10
python_venv: null
installer:
  name: Demo
  install_directory: '%localappdata%\\Demo'
""".strip(),
                encoding="utf-8",
            )
            with patch("app_builder.build._run_dependency_stages") as dependency_stages:
                with self.assertRaisesRegex(
                    RuntimeError,
                    "self-contained.*main checkout.*fresh self-contained runtime",
                ):
                    build_release(fixture.project_root, version="0.0.0-dev")

            dependency_stages.assert_not_called()


if __name__ == "__main__":
    unittest.main()
