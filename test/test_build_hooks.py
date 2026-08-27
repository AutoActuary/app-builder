from __future__ import annotations

import os
import subprocess
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import Mock, patch

from app_builder import build as build_module
from app_builder.config import load_project_config
from app_builder.python_runtime import PythonEnvironmentResult, python_executable
from app_builder.release_preflight import PublicationPreflightResult


def _write_config(project_root: Path, build_hooks: str) -> None:
    (project_root / "app.cmd").write_text("@echo off\n", encoding="utf-8")
    (project_root / "app_builder.yaml").write_text(
        f"""
app_builder_version: v1.0.0
python_bundled:
  path: bin/python
  python_version: 3.12.10
python_venv:
  path: venv
  python_version: 3.12.10
installer:
  name: Demo
  install_directory: "%localappdata%\\\\Demo"
  dist: dist
  paths:
    include: [app.cmd]
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
            events: list[str] = []
            materializer = Mock()

            def materialize_bundled() -> Path:
                events.append("materialize-bundled")
                return bundled_python

            def materialize_venv() -> Path:
                events.append("materialize-venv")
                return venv_python

            materializer.materialize_bundled.side_effect = materialize_bundled
            materializer.materialize_venv.side_effect = materialize_venv
            materializer.result.return_value = env_result

            with (
                patch(
                    "app_builder.build.PythonEnvironmentMaterializer",
                    return_value=materializer,
                ),
                patch(
                    "app_builder.build.run_hook_commands",
                    side_effect=lambda _root, commands, **_kwargs: events.append(
                        commands[0][0]
                    ),
                ) as run_hooks,
            ):
                self.assertEqual(
                    env_result, build_module._run_dependency_stages(project_root)
                )

        app_builder_python = Path(sys.executable).resolve()
        self.assertEqual(
            [
                [app_builder_python],
                [app_builder_python],
                [bundled_python, app_builder_python],
                [bundled_python, app_builder_python],
                [venv_python, bundled_python, app_builder_python],
            ],
            [call.kwargs["python_candidates"] for call in run_hooks.call_args_list],
        )
        self.assertEqual(
            [
                "pre-process",
                "pre-bundled",
                "materialize-bundled",
                "post-bundled",
                "pre-venv",
                "materialize-venv",
                "post-venv",
            ],
            events,
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
  python_version: 3.12.10
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
            materializer = Mock()
            materializer.materialize_bundled.return_value = None
            materializer.materialize_venv.return_value = venv_python
            materializer.result.return_value = env_result

            with (
                patch(
                    "app_builder.build.PythonEnvironmentMaterializer",
                    return_value=materializer,
                ),
                patch("app_builder.build.run_hook_commands") as run_hooks,
            ):
                self.assertEqual(
                    env_result, build_module._run_dependency_stages(project_root)
                )

        app_builder_python = Path(sys.executable).resolve()
        self.assertEqual(
            [
                [app_builder_python],
                [app_builder_python],
                [app_builder_python],
                [app_builder_python],
                [venv_python, app_builder_python],
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
            Path(sys.executable).resolve(),
        ]
        self.assertEqual(
            [expected_candidates, expected_candidates],
            [call.kwargs["python_candidates"] for call in run_hooks.call_args_list],
        )
        self.assertEqual(
            [[["pre-dist"]], [["post-dist"]]],
            [call.args[1] for call in run_hooks.call_args_list],
        )
        self.assertEqual(
            ["1.2.3", "1.2.3"],
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
                Path(sys.executable).resolve(),
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
            checksums_path = dist_dir / "demo-1.2.3-SHA256SUMS.txt"
            release_notes_path = dist_dir / "demo-1.2.3-release-notes.md"
            payload_archive.write_bytes(b"payload")
            installer_archive.write_bytes(b"installer")
            manifest_path.write_text('{"name": "Demo"}', encoding="utf-8")
            release = build_module.ReleaseResult(
                version="1.2.3",
                payload_archive=payload_archive,
                installer_archive=installer_archive,
                manifest_path=manifest_path,
                checksums_path=checksums_path,
                release_notes_path=release_notes_path,
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
                if args[1:3] == ["auth", "status"]:
                    return subprocess.CompletedProcess(
                        args=args, returncode=0, stdout="", stderr=""
                    )
                if args[1:3] == ["repo", "view"]:
                    return subprocess.CompletedProcess(
                        args=args,
                        returncode=0,
                        stdout="AutoActuary/demo\n",
                        stderr="",
                    )
                if args[1] == "api":
                    return subprocess.CompletedProcess(
                        args=args, returncode=1, stdout="", stderr="HTTP 404"
                    )
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
                patch(
                    "app_builder.build.run_publication_preflight",
                    return_value=PublicationPreflightResult(
                        head_commit="a" * 40,
                        origin_url="https://github.com/AutoActuary/demo.git",
                    ),
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
        create_call = next(
            call for call in gh_calls if call[1:3] == ["release", "create"]
        )
        self.assertEqual([gh_executable, "release", "create", "1.2.3"], create_call[:4])
        self.assertIn(str(payload_archive), create_call)
        self.assertIn(str(installer_archive), create_call)
        self.assertIn(str(manifest_path), create_call)
        self.assertIn(str(checksums_path), create_call)
        self.assertIn(str(release_notes_path), create_call)
        self.assertIn("a" * 40, create_call)
        self.assertIn("--draft", create_call)
        self.assertIn(
            [
                gh_executable,
                "release",
                "view",
                "1.2.3",
                "--repo",
                "AutoActuary/demo",
                "--json",
                "url",
                "--jq",
                ".url",
            ],
            gh_calls,
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
                checksums_path=project_root / "checksums.txt",
                release_notes_path=project_root / "release-notes.md",
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

    def test_existing_github_release_reconciles_notes_and_stale_assets(self) -> None:
        with TemporaryDirectory() as temp_dir_str:
            project_root = Path(temp_dir_str)
            _write_config(project_root, "  pre_github_release: []")
            dist_dir = project_root / "dist"
            dist_dir.mkdir()
            paths = {
                "payload": dist_dir / "demo-1.2.3.zip",
                "installer": dist_dir / "demo-1.2.3-installer.exe",
                "manifest": dist_dir / "demo-1.2.3-manifest.json",
                "checksums": dist_dir / "demo-1.2.3-SHA256SUMS.txt",
                "notes": dist_dir / "demo-1.2.3-release-notes.md",
            }
            for path in paths.values():
                path.write_text(path.name, encoding="utf-8")
            release = build_module.ReleaseResult(
                version="1.2.3",
                payload_archive=paths["payload"],
                installer_archive=paths["installer"],
                manifest_path=paths["manifest"],
                checksums_path=paths["checksums"],
                release_notes_path=paths["notes"],
            )
            gh_calls: list[list[str]] = []

            def fake_run(
                args: list[str],
                *,
                cwd: Path,
                capture_output: bool,
                text: bool,
            ) -> subprocess.CompletedProcess[str]:
                gh_calls.append(args)
                if args[1:3] == ["repo", "view"]:
                    stdout = "AutoActuary/demo\n"
                elif args[1] == "api":
                    stdout = '{"object":{"type":"commit","sha":"' + ("b" * 40) + '"}}'
                elif args[1:3] == ["release", "view"]:
                    stdout = (
                        '{"url":"https://github.example/releases/1.2.3",'
                        '"isDraft":false,"targetCommitish":"1.2.3",'
                        '"assets":[{"name":"demo-1.2.3.zip"},'
                        '{"name":"obsolete.zip"}]}'
                    )
                else:
                    stdout = ""
                return subprocess.CompletedProcess(
                    args=args, returncode=0, stdout=stdout, stderr=""
                )

            with (
                patch("app_builder.build._resolve_github_cli", return_value="gh.exe"),
                patch(
                    "app_builder.build.run_publication_preflight",
                    return_value=PublicationPreflightResult(
                        head_commit="b" * 40,
                        origin_url="https://github.example/demo.git",
                    ),
                ),
                patch("app_builder.build.subprocess.run", side_effect=fake_run),
                patch("app_builder.build.run_hook_commands"),
            ):
                url = build_module.upload_release_to_github(
                    project_root, release=release, draft=False
                )

        self.assertEqual("https://github.example/releases/1.2.3", url)
        self.assertIn(
            [
                "gh.exe",
                "release",
                "delete-asset",
                "1.2.3",
                "obsolete.zip",
                "--yes",
                "--repo",
                "AutoActuary/demo",
            ],
            gh_calls,
        )
        upload_call = next(
            call for call in gh_calls if call[1:3] == ["release", "upload"]
        )
        self.assertIn(str(paths["checksums"]), upload_call)
        edit_call = next(call for call in gh_calls if call[1:3] == ["release", "edit"])
        self.assertIn(str(paths["notes"]), edit_call)
        mutation_calls = [
            call
            for call in gh_calls
            if call[1:3]
            in (
                ["release", "view"],
                ["release", "upload"],
                ["release", "edit"],
                ["release", "delete-asset"],
            )
        ]
        self.assertTrue(mutation_calls)
        for call in mutation_calls:
            self.assertEqual("AutoActuary/demo", call[call.index("--repo") + 1])
        self.assertLess(gh_calls.index(upload_call), gh_calls.index(edit_call))
        delete_call = next(
            call for call in gh_calls if call[1:3] == ["release", "delete-asset"]
        )
        self.assertLess(gh_calls.index(edit_call), gh_calls.index(delete_call))

    def test_existing_tagless_draft_is_retargeted_to_verified_head(self) -> None:
        with TemporaryDirectory() as temp_dir_str:
            project_root = Path(temp_dir_str)
            _write_config(project_root, "  pre_github_release: []")
            dist_dir = project_root / "dist"
            dist_dir.mkdir()
            paths = [
                dist_dir / "demo-1.2.3.zip",
                dist_dir / "demo-1.2.3-installer.exe",
                dist_dir / "demo-1.2.3-manifest.json",
                dist_dir / "demo-1.2.3-SHA256SUMS.txt",
                dist_dir / "demo-1.2.3-release-notes.md",
            ]
            for path in paths:
                path.write_text(path.name, encoding="utf-8")
            release = build_module.ReleaseResult(
                version="1.2.3",
                payload_archive=paths[0],
                installer_archive=paths[1],
                manifest_path=paths[2],
                checksums_path=paths[3],
                release_notes_path=paths[4],
            )
            gh_calls: list[list[str]] = []

            def fake_run(
                args: list[str],
                *,
                cwd: Path,
                capture_output: bool,
                text: bool,
            ) -> subprocess.CompletedProcess[str]:
                gh_calls.append(args)
                if args[1:3] == ["repo", "view"]:
                    stdout, returncode, stderr = "AutoActuary/demo\n", 0, ""
                elif args[1] == "api":
                    stdout, returncode, stderr = "", 1, "HTTP 404"
                elif args[1:3] == ["release", "view"]:
                    stdout, returncode, stderr = (
                        '{"url":"https://github.example/draft",'
                        '"isDraft":true,"targetCommitish":"old-main",'
                        '"assets":[]}',
                        0,
                        "",
                    )
                else:
                    stdout, returncode, stderr = "", 0, ""
                return subprocess.CompletedProcess(args, returncode, stdout, stderr)

            with (
                patch("app_builder.build._resolve_github_cli", return_value="gh.exe"),
                patch(
                    "app_builder.build.run_publication_preflight",
                    return_value=PublicationPreflightResult(
                        head_commit="d" * 40,
                        origin_url="https://github.example/demo.git",
                    ),
                ),
                patch("app_builder.build.subprocess.run", side_effect=fake_run),
                patch("app_builder.build.run_hook_commands"),
            ):
                build_module.upload_release_to_github(
                    project_root, release=release, draft=True
                )

        edit_call = next(call for call in gh_calls if call[1:3] == ["release", "edit"])
        self.assertEqual("d" * 40, edit_call[edit_call.index("--target") + 1])

    def test_failed_replacement_upload_does_not_delete_stale_assets(self) -> None:
        with TemporaryDirectory() as temp_dir_str:
            project_root = Path(temp_dir_str)
            _write_config(project_root, "  pre_github_release: []")
            paths = [
                project_root / name
                for name in (
                    "payload.zip",
                    "installer.exe",
                    "manifest.json",
                    "checksums.txt",
                    "notes.md",
                )
            ]
            for path in paths:
                path.write_text(path.name, encoding="utf-8")
            release = build_module.ReleaseResult(
                version="1.2.3",
                payload_archive=paths[0],
                installer_archive=paths[1],
                manifest_path=paths[2],
                checksums_path=paths[3],
                release_notes_path=paths[4],
            )
            gh_calls: list[list[str]] = []

            def fake_run(
                args: list[str],
                *,
                cwd: Path,
                capture_output: bool,
                text: bool,
            ) -> subprocess.CompletedProcess[str]:
                gh_calls.append(args)
                if args[1:3] == ["repo", "view"]:
                    stdout, returncode, stderr = "AutoActuary/demo\n", 0, ""
                elif args[1] == "api":
                    stdout = '{"object":{"type":"commit","sha":"' + ("e" * 40) + '"}}'
                    returncode, stderr = 0, ""
                elif args[1:3] == ["release", "view"]:
                    stdout = (
                        '{"url":"https://github.example/release",'
                        '"isDraft":false,"targetCommitish":"1.2.3",'
                        '"assets":[{"name":"obsolete.zip"}]}'
                    )
                    returncode, stderr = 0, ""
                elif args[1:3] == ["release", "upload"]:
                    stdout, returncode, stderr = "", 1, "upload failed"
                else:
                    stdout, returncode, stderr = "", 0, ""
                return subprocess.CompletedProcess(args, returncode, stdout, stderr)

            with (
                patch("app_builder.build._resolve_github_cli", return_value="gh.exe"),
                patch(
                    "app_builder.build.run_publication_preflight",
                    return_value=PublicationPreflightResult(
                        head_commit="e" * 40,
                        origin_url="https://github.example/demo.git",
                    ),
                ),
                patch("app_builder.build.subprocess.run", side_effect=fake_run),
                patch("app_builder.build.run_hook_commands"),
            ):
                with self.assertRaisesRegex(RuntimeError, "upload failed"):
                    build_module.upload_release_to_github(
                        project_root, release=release, draft=False
                    )

        self.assertFalse(
            any(call[1:3] == ["release", "delete-asset"] for call in gh_calls)
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

    def test_github_tag_preflight_rejects_different_commit(self) -> None:
        response = subprocess.CompletedProcess(
            args=["gh.exe", "api"],
            returncode=0,
            stdout='{"object":{"type":"commit","sha":"' + ("c" * 40) + '"}}',
            stderr="",
        )
        with (
            TemporaryDirectory() as temp_dir_str,
            patch("app_builder.build._run_gh", return_value=response),
        ):
            with self.assertRaisesRegex(RuntimeError, "tag.*not HEAD"):
                build_module._validate_github_tag_target(
                    Path(temp_dir_str),
                    "gh.exe",
                    repository="AutoActuary/demo",
                    version="1.2.3",
                    head_commit="b" * 40,
                )


if __name__ == "__main__":
    unittest.main()
