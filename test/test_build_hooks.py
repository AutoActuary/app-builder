from __future__ import annotations

import os
import subprocess
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from app_builder import build as build_module
from app_builder.config import load_project_config
from app_builder.python_runtime import PythonEnvironmentResult, python_executable


def _write_config(project_root: Path, build_hooks: str) -> None:
    (project_root / "app_builder.yaml").write_text(
        f"""
app_builder_version: v1.0.0
python_bundled:
  path: bin/python
python_venv:
  path: venv
installer:
  name: Demo
  install_directory: "%localappdata%\\\\Demo"
  dist: dist
  paths:
    include: []
build_hooks:
{build_hooks}
""".strip(),
        encoding="utf-8",
    )


class TestBuildHookPythonSelection(unittest.TestCase):
    def test_dependency_stages_pass_stage_specific_python_candidates(self) -> None:
        with TemporaryDirectory() as temp_dir_str:
            project_root = Path(temp_dir_str)
            _write_config(
                project_root,
                """
  pre_process:
    - [pre-process]
  pre_python_bundled:
    - [pre-bundled]
  post_python_bundled:
    - [post-bundled]
  pre_python_venv:
    - [pre-venv]
  post_python_venv:
    - [post-venv]
""",
            )
            bundled_python = project_root / "bin" / "python" / "python" / "python.exe"
            venv_python = python_executable(project_root / "venv")
            env_result = PythonEnvironmentResult(
                python_bundled=bundled_python,
                python_venv=venv_python,
            )

            with (
                patch(
                    "app_builder.build.materialize_python_environments",
                    return_value=env_result,
                ),
                patch("app_builder.build.run_hook_commands") as run_hooks,
            ):
                self.assertEqual(
                    env_result, build_module._run_dependency_stages(project_root)
                )

        self.assertEqual(
            [
                [venv_python, bundled_python],
                [bundled_python, venv_python],
                [bundled_python, venv_python],
                [bundled_python, venv_python],
                [venv_python, bundled_python],
            ],
            [call.kwargs["python_candidates"] for call in run_hooks.call_args_list],
        )
        self.assertEqual(
            [
                [["pre-process"]],
                [["pre-bundled"]],
                [["post-bundled"]],
                [["pre-venv"]],
                [["post-venv"]],
            ],
            [call.args[1] for call in run_hooks.call_args_list],
        )

    def test_bundled_stage_hooks_fall_back_to_venv_when_no_bundled_python(
        self,
    ) -> None:
        with TemporaryDirectory() as temp_dir_str:
            project_root = Path(temp_dir_str)
            (project_root / "app_builder.yaml").write_text(
                """
app_builder_version: v1.0.0
python_bundled: null
python_venv:
  path: venv
installer:
  name: Demo
  install_directory: "%localappdata%\\\\Demo"
  dist: dist
  paths:
    include: []
build_hooks:
  pre_process:
    - [pre-process]
  pre_python_bundled:
    - [pre-bundled]
  post_python_bundled:
    - [post-bundled]
  pre_python_venv:
    - [pre-venv]
  post_python_venv:
    - [post-venv]
""".strip(),
                encoding="utf-8",
            )
            venv_python = python_executable(project_root / "venv")
            env_result = PythonEnvironmentResult(
                python_bundled=None,
                python_venv=venv_python,
            )

            with (
                patch(
                    "app_builder.build.materialize_python_environments",
                    return_value=env_result,
                ),
                patch("app_builder.build.run_hook_commands") as run_hooks,
            ):
                self.assertEqual(
                    env_result, build_module._run_dependency_stages(project_root)
                )

        self.assertEqual(
            [
                [venv_python],
                [venv_python],
                [venv_python],
                [venv_python],
                [venv_python],
            ],
            [call.kwargs["python_candidates"] for call in run_hooks.call_args_list],
        )

    def test_release_build_hooks_use_most_advanced_materialized_python(self) -> None:
        with TemporaryDirectory() as temp_dir_str:
            project_root = Path(temp_dir_str)
            _write_config(
                project_root,
                """
  pre_dist:
    - [pre-dist]
  post_dist:
    - [post-dist]
  post_process:
    - [post-process]
""",
            )
            bundled_python = project_root / "bin" / "python" / "python" / "python.exe"
            venv_python = python_executable(project_root / "venv")
            env_result = PythonEnvironmentResult(
                python_bundled=bundled_python,
                python_venv=venv_python,
            )

            with (
                patch(
                    "app_builder.build._run_dependency_stages",
                    return_value=env_result,
                ),
                patch("app_builder.build.run_hook_commands") as run_hooks,
            ):
                build_module.build_release(project_root, version="1.2.3")

        expected_candidates = [
            venv_python,
            bundled_python,
        ]
        self.assertEqual(
            [expected_candidates, expected_candidates, expected_candidates],
            [call.kwargs["python_candidates"] for call in run_hooks.call_args_list],
        )
        self.assertEqual(
            [[["pre-dist"]], [["post-dist"]], [["post-process"]]],
            [call.args[1] for call in run_hooks.call_args_list],
        )
        self.assertEqual(
            ["1.2.3", "1.2.3", "1.2.3"],
            [
                call.kwargs["environment"]["app_builder_version"]
                for call in run_hooks.call_args_list
            ],
        )

    def test_release_hook_candidates_can_be_derived_from_configured_paths(self) -> None:
        with TemporaryDirectory() as temp_dir_str:
            project_root = Path(temp_dir_str)
            _write_config(project_root, "  pre_process: []")
            _, config = load_project_config(project_root)

            candidates = build_module._runtime_hook_python_candidates(
                project_root, config
            )

        self.assertEqual(
            [
                python_executable(project_root / "venv"),
                project_root / "bin" / "python" / "python" / "python.exe",
            ],
            candidates,
        )

    def test_github_release_upload_smoke_uses_artifacts_without_real_network(
        self,
    ) -> None:
        with TemporaryDirectory() as temp_dir_str:
            project_root = Path(temp_dir_str)
            _write_config(
                project_root,
                """
  pre_github_release:
    - [pre-gh]
  post_github_release:
    - [post-gh]
""",
            )
            dist_dir = project_root / "dist"
            dist_dir.mkdir()
            payload_archive = dist_dir / "demo-1.2.3.zip"
            installer_archive = dist_dir / "demo-1.2.3-installer.exe"
            manifest_path = dist_dir / "demo-1.2.3-manifest.json"
            payload_archive.write_bytes(b"payload")
            installer_archive.write_bytes(b"installer")
            manifest_path.write_text('{"name": "Demo"}', encoding="utf-8")
            release = build_module.ReleaseResult(
                version="1.2.3",
                payload_archive=payload_archive,
                installer_archive=installer_archive,
                manifest_path=manifest_path,
            )
            gh_calls: list[list[str]] = []
            view_count = 0

            def fake_run(
                args: list[str],
                *,
                cwd: Path,
                capture_output: bool,
                text: bool,
            ) -> subprocess.CompletedProcess[str]:
                nonlocal view_count
                self.assertEqual(project_root, cwd)
                self.assertTrue(capture_output)
                self.assertTrue(text)
                gh_calls.append(args)
                if args[1:3] == ["release", "view"]:
                    view_count += 1
                    if view_count == 1:
                        return subprocess.CompletedProcess(
                            args=args,
                            returncode=1,
                            stdout="",
                            stderr="release not found",
                        )
                    return subprocess.CompletedProcess(
                        args=args,
                        returncode=0,
                        stdout="https://github.com/AutoActuary/demo/releases/tag/1.2.3\n",
                        stderr="",
                    )
                return subprocess.CompletedProcess(
                    args=args,
                    returncode=0,
                    stdout="",
                    stderr="",
                )

            gh_executable = r"C:\Tools\GitHub CLI\gh.exe"
            with (
                patch(
                    "app_builder.build._resolve_github_cli", return_value=gh_executable
                ),
                patch("app_builder.build.subprocess.run", side_effect=fake_run),
                patch("app_builder.build.run_hook_commands") as run_hooks,
            ):
                html_url = build_module.upload_release_to_github(
                    project_root, release=release, draft=True
                )

        self.assertEqual(
            "https://github.com/AutoActuary/demo/releases/tag/1.2.3", html_url
        )
        self.assertEqual(
            [[["pre-gh"]], [["post-gh"]]],
            [call.args[1] for call in run_hooks.call_args_list],
        )
        self.assertEqual(
            ["1.2.3", "1.2.3"],
            [
                call.kwargs["environment"]["app_builder_version"]
                for call in run_hooks.call_args_list
            ],
        )
        create_call = gh_calls[1]
        self.assertEqual([gh_executable, "release", "create", "1.2.3"], create_call[:4])
        self.assertIn(str(payload_archive), create_call)
        self.assertIn(str(installer_archive), create_call)
        self.assertIn(str(manifest_path), create_call)
        self.assertIn("--draft", create_call)
        self.assertEqual(
            [
                gh_executable,
                "release",
                "view",
                "1.2.3",
                "--json",
                "url",
                "--jq",
                ".url",
            ],
            gh_calls[2],
        )

    def test_github_release_requires_gh_cli(self) -> None:
        with TemporaryDirectory() as temp_dir_str:
            project_root = Path(temp_dir_str)
            _write_config(project_root, "  pre_github_release: []")
            release = build_module.ReleaseResult(
                version="1.2.3",
                payload_archive=project_root / "payload.zip",
                installer_archive=project_root / "installer.exe",
                manifest_path=project_root / "manifest.json",
            )

            with (
                patch("app_builder.build._where_github_cli_paths", return_value=[]),
                patch("app_builder.build.shutil.which", return_value=None),
                patch("app_builder.build._known_github_cli_paths", return_value=[]),
                patch("app_builder.build.run_hook_commands"),
            ):
                with self.assertRaisesRegex(
                    RuntimeError, "winget install --id GitHub.cli"
                ):
                    build_module.upload_release_to_github(
                        project_root, release=release, draft=False
                    )

    def test_github_cli_resolver_uses_known_locations(self) -> None:
        with TemporaryDirectory() as temp_dir_str:
            gh_executable = Path(temp_dir_str) / "GitHub CLI" / "gh.exe"
            gh_executable.parent.mkdir()
            gh_executable.write_text("", encoding="utf-8")

            with (
                patch("app_builder.build._where_github_cli_paths", return_value=[]),
                patch("app_builder.build.shutil.which", return_value=None),
                patch(
                    "app_builder.build._known_github_cli_paths",
                    return_value=[gh_executable],
                ),
            ):
                self.assertEqual(str(gh_executable), build_module._resolve_github_cli())


if __name__ == "__main__":
    unittest.main()
