from __future__ import annotations

import unittest
from pathlib import Path
from unittest.mock import patch

from click.testing import CliRunner

from app_builder.main import main
from app_builder.poetry_dependencies import PoetryLock


class TestCliLock(unittest.TestCase):
    def setUp(self) -> None:
        self.project_root = Path("C:/project")
        self.lock = PoetryLock(
            packages=(),
            path=self.project_root / "poetry.lock",
            sha256="a" * 64,
        )

    def test_lock_refreshes_by_default(self) -> None:
        with (
            patch(
                "app_builder.main.find_project_root",
                return_value=self.project_root,
            ),
            patch(
                "app_builder.main.refresh_poetry_lock",
                return_value=self.lock,
            ) as refresh,
            patch("app_builder.main.ensure_poetry_lock") as check,
        ):
            result = CliRunner().invoke(main, ["lock"])

        self.assertEqual(0, result.exit_code, result.output)
        refresh.assert_called_once_with(self.project_root)
        check.assert_not_called()
        self.assertIn(f"Refreshed lock: {self.lock.path}", result.output)
        self.assertIn(f"SHA-256: {self.lock.sha256}", result.output)

    def test_lock_check_verifies_without_refreshing(self) -> None:
        with (
            patch(
                "app_builder.main.find_project_root",
                return_value=self.project_root,
            ),
            patch(
                "app_builder.main.ensure_poetry_lock",
                return_value=self.lock,
            ) as check,
            patch("app_builder.main.refresh_poetry_lock") as refresh,
        ):
            result = CliRunner().invoke(main, ["lock", "--check"])

        self.assertEqual(0, result.exit_code, result.output)
        check.assert_called_once_with(self.project_root)
        refresh.assert_not_called()
        self.assertIn(f"Lock is up to date: {self.lock.path}", result.output)
        self.assertIn(f"SHA-256: {self.lock.sha256}", result.output)

    def test_lock_refresh_can_be_selected_explicitly(self) -> None:
        with (
            patch(
                "app_builder.main.find_project_root",
                return_value=self.project_root,
            ),
            patch(
                "app_builder.main.refresh_poetry_lock",
                return_value=self.lock,
            ) as refresh,
            patch("app_builder.main.ensure_poetry_lock") as check,
        ):
            result = CliRunner().invoke(main, ["lock", "--refresh"])

        self.assertEqual(0, result.exit_code, result.output)
        refresh.assert_called_once_with(self.project_root)
        check.assert_not_called()

    def test_lock_check_failure_is_nonzero(self) -> None:
        with (
            patch(
                "app_builder.main.find_project_root",
                return_value=self.project_root,
            ),
            patch(
                "app_builder.main.ensure_poetry_lock",
                side_effect=RuntimeError("poetry.lock is stale"),
            ),
            patch("app_builder.main.refresh_poetry_lock") as refresh,
        ):
            result = CliRunner().invoke(main, ["lock", "--check"])

        self.assertNotEqual(0, result.exit_code)
        self.assertIsInstance(result.exception, RuntimeError)
        refresh.assert_not_called()

    def test_lock_help_describes_both_modes(self) -> None:
        result = CliRunner().invoke(main, ["lock", "--help"])

        self.assertEqual(0, result.exit_code, result.output)
        self.assertIn("--check / --refresh", result.output)
        self.assertIn("without changing it", result.output)


if __name__ == "__main__":
    unittest.main()
