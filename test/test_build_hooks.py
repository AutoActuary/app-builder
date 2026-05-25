from __future__ import annotations

import json
import os
import subprocess
import sys
import unittest
import urllib.parse
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any
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


class _FakeHttpResponse:
    def __init__(self, payload: bytes = b"{}") -> None:
        self._payload = payload

    def __enter__(self) -> "_FakeHttpResponse":
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        return None

    def read(self) -> bytes:
        return self._payload


class _FakeUrlopen:
    def __init__(self) -> None:
        self.requests: list[Any] = []

    def __call__(self, request: Any) -> _FakeHttpResponse:
        self.requests.append(request)
        if len(self.requests) == 1:
            return _FakeHttpResponse(
                json.dumps(
                    {
                        "upload_url": "https://uploads.example/releases/1/assets{?name,label}",
                        "html_url": "https://github.com/AutoActuary/demo/releases/tag/1.2.3",
                    }
                ).encode("utf-8")
            )
        return _FakeHttpResponse()


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

        host_python = Path(sys.executable)
        self.assertEqual(
            [
                [host_python],
                [bundled_python, venv_python, host_python],
                [bundled_python, venv_python, host_python],
                [bundled_python, venv_python, host_python],
                [venv_python, bundled_python, host_python],
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

        host_python = Path(sys.executable)
        self.assertEqual(
            [
                [host_python],
                [venv_python, host_python],
                [venv_python, host_python],
                [venv_python, host_python],
                [venv_python, host_python],
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
            Path(sys.executable),
        ]
        self.assertEqual(
            [expected_candidates, expected_candidates, expected_candidates],
            [call.kwargs["python_candidates"] for call in run_hooks.call_args_list],
        )
        self.assertEqual(
            [[["pre-dist"]], [["post-dist"]], [["post-process"]]],
            [call.args[1] for call in run_hooks.call_args_list],
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
                Path(sys.executable),
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
            fake_urlopen = _FakeUrlopen()

            with (
                patch.dict(os.environ, {"GITHUB_TOKEN": "token"}),
                patch(
                    "app_builder.build.subprocess.run",
                    return_value=subprocess.CompletedProcess(
                        args=["git", "config", "--get", "remote.origin.url"],
                        returncode=0,
                        stdout="https://github.com/AutoActuary/demo.git\n",
                    ),
                ),
                patch("urllib.request.urlopen", side_effect=fake_urlopen),
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
        self.assertEqual(4, len(fake_urlopen.requests))
        create_body = json.loads(fake_urlopen.requests[0].data.decode("utf-8"))
        self.assertEqual(
            {"tag_name": "1.2.3", "name": "1.2.3", "draft": True},
            create_body,
        )
        uploaded_names = [
            urllib.parse.parse_qs(urllib.parse.urlparse(request.full_url).query)[
                "name"
            ][0]
            for request in fake_urlopen.requests[1:]
        ]
        self.assertEqual(
            [
                payload_archive.name,
                installer_archive.name,
                manifest_path.name,
            ],
            uploaded_names,
        )


if __name__ == "__main__":
    unittest.main()
