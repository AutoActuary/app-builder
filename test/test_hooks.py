from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from app_builder.hooks import run_hook_commands


class TestHookCommandExecution(unittest.TestCase):
    def test_python_file_hook_uses_first_existing_candidate(self) -> None:
        with TemporaryDirectory() as temp_dir_str:
            project_root = Path(temp_dir_str)
            script = project_root / "scripts" / "hook.py"
            script.parent.mkdir()
            script.write_text("print('hook')\n", encoding="utf-8")
            missing_venv_python = project_root / "venv" / "Scripts" / "python.exe"
            bundled_python = project_root / "bin" / "python" / "python" / "python.exe"
            bundled_python.parent.mkdir(parents=True)
            bundled_python.write_text("", encoding="utf-8")

            with patch("app_builder.hooks.subprocess.run") as subprocess_run:
                run_hook_commands(
                    project_root,
                    [["scripts/hook.py", "--name", "Demo App"]],
                    environment={"CUSTOM": "1"},
                    python_candidates=[missing_venv_python, bundled_python],
                )

        args, kwargs = subprocess_run.call_args
        self.assertEqual(
            [str(bundled_python), str(script.resolve()), "--name", "Demo App"],
            args[0],
        )
        self.assertEqual(project_root, kwargs["cwd"])
        self.assertEqual("1", kwargs["env"]["CUSTOM"])
        self.assertTrue(kwargs["check"])

    def test_python_file_hook_requires_configured_project_python(self) -> None:
        with TemporaryDirectory() as temp_dir_str:
            project_root = Path(temp_dir_str)
            script = project_root / "hook.py"
            script.write_text("print('hook')\n", encoding="utf-8")
            missing_python = project_root / "venv" / "Scripts" / "python.exe"

            with patch("app_builder.hooks.subprocess.run") as subprocess_run:
                with self.assertRaisesRegex(RuntimeError, "Python runtime configured"):
                    run_hook_commands(
                        project_root,
                        [["hook.py"]],
                        environment={},
                        python_candidates=[missing_python],
                    )

        subprocess_run.assert_not_called()

    def test_powershell_file_hook_uses_execution_policy_bypass(self) -> None:
        with TemporaryDirectory() as temp_dir_str:
            project_root = Path(temp_dir_str)
            script = project_root / "scripts" / "install.ps1"
            script.parent.mkdir()
            script.write_text("Write-Host hook\n", encoding="utf-8")

            with patch("app_builder.hooks.subprocess.run") as subprocess_run:
                run_hook_commands(
                    project_root,
                    [["scripts/install.ps1", "-Name", "Demo"]],
                    environment={},
                    python_candidates=[],
                )

        args, kwargs = subprocess_run.call_args
        self.assertEqual(
            [
                "powershell.exe",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(script.resolve()),
                "-Name",
                "Demo",
            ],
            args[0],
        )
        self.assertEqual(project_root, kwargs["cwd"])

    def test_argv_commands_bypass_shell_execution(self) -> None:
        with TemporaryDirectory() as temp_dir_str:
            project_root = Path(temp_dir_str)

            with patch("app_builder.hooks.subprocess.run") as subprocess_run:
                run_hook_commands(
                    project_root,
                    [["python", "-m", "pytest"]],
                    environment={},
                    python_candidates=[],
                )

        args, kwargs = subprocess_run.call_args
        self.assertEqual(["python", "-m", "pytest"], args[0])
        self.assertEqual(project_root, kwargs["cwd"])

    def test_explicit_python_executable_is_not_overridden(self) -> None:
        with TemporaryDirectory() as temp_dir_str:
            project_root = Path(temp_dir_str)
            explicit_python = project_root / "custom-python" / "python.exe"
            explicit_python.parent.mkdir()
            explicit_python.write_text("", encoding="utf-8")
            script = project_root / "scripts" / "hook.py"
            script.parent.mkdir()
            script.write_text("print('hook')\n", encoding="utf-8")
            fallback_python = project_root / "bin" / "python" / "python" / "python.exe"
            fallback_python.parent.mkdir(parents=True)
            fallback_python.write_text("", encoding="utf-8")

            with patch("app_builder.hooks.subprocess.run") as subprocess_run:
                run_hook_commands(
                    project_root,
                    [[str(explicit_python), str(script)]],
                    environment={},
                    python_candidates=[fallback_python],
                )

        args, _ = subprocess_run.call_args
        self.assertEqual([str(explicit_python), str(script)], args[0])


if __name__ == "__main__":
    unittest.main()
