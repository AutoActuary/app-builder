from __future__ import annotations

import json
import os
import subprocess
import time
import unittest
from importlib.resources import files
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any, cast
from unittest.mock import patch
from zipfile import ZipFile

from app_builder import build as build_module
from app_builder.build import build_release
from app_builder.exewrap import _read_icon_images, _render_icon_group_resource


def _write_sample_icon(icon_path: Path) -> None:
    icon_path.write_bytes(
        files("app_builder")
        .joinpath("assets")
        .joinpath("app-builder.ico")
        .read_bytes()
    )


class TestEndToEndBuild(unittest.TestCase):
    def test_build_release_for_demo_app(self) -> None:
        with TemporaryDirectory() as temp_dir_str:
            project_root = Path(temp_dir_str)
            subprocess.run(
                ["git", "init"], cwd=project_root, check=True, capture_output=True
            )
            (project_root / "src").mkdir()
            (project_root / "src" / "hello.py").write_text(
                "print('hello world')\n", encoding="utf-8"
            )
            (project_root / "README.md").write_text("demo\n", encoding="utf-8")
            (project_root / "app_builder.yaml").write_text(
                """
app_builder_version: v1.0.0
python_bundled: null
python_venv: null
installer:
  name: Demo App
  install_directory: "%localappdata%\\\\DemoApp"
  dist: dist
  paths:
    include:
      - src
      - README.md
    remap:
      - [README.md, docs/README.md]
build_hooks: {}
""".strip(),
                encoding="utf-8",
            )

            release = build_release(project_root, version="1.2.3")

            self.assertTrue(release.payload_archive.exists())
            self.assertTrue(release.installer_archive.exists())
            self.assertTrue(release.manifest_path.exists())
            self.assertEqual(".exe", release.installer_archive.suffix)

            manifest = json.loads(release.manifest_path.read_text(encoding="utf-8"))
            self.assertEqual("Demo App", manifest["name"])
            self.assertEqual("1.2.3", manifest["version"])
            self.assertEqual(r"%localappdata%\DemoApp", manifest["install_directory"])
            self.assertEqual([], manifest["start_menu"])

            with ZipFile(release.payload_archive) as payload_zip:
                self.assertEqual(
                    {"docs/README.md", "src/hello.py", "version.txt"},
                    set(payload_zip.namelist()),
                )

            with ZipFile(release.installer_archive) as installer_zip:
                self.assertIn("install.cmd", installer_zip.namelist())
                self.assertIn("uninstall.cmd", installer_zip.namelist())
                self.assertIn(release.payload_archive.name, installer_zip.namelist())
                self.assertNotIn("install.ps1", installer_zip.namelist())
                self.assertNotIn("uninstall.ps1", installer_zip.namelist())
                self.assertNotIn(release.manifest_path.name, installer_zip.namelist())

    def test_build_release_reports_missing_custom_installer_icon(self) -> None:
        with TemporaryDirectory() as temp_dir_str:
            project_root = Path(temp_dir_str)
            subprocess.run(
                ["git", "init"], cwd=project_root, check=True, capture_output=True
            )
            (project_root / "app.cmd").write_text(
                "@echo off\necho hi\n", encoding="utf-8"
            )
            (project_root / "app_builder.yaml").write_text(
                """
app_builder_version: v1.0.0
python_bundled: null
python_venv: null
installer:
  name: Missing Icon Demo
  install_directory: "%localappdata%\\\\MissingIconDemo"
  icon: icons/missing.ico
  dist: dist
  paths:
    include:
      - app.cmd
build_hooks: {}
""".strip(),
                encoding="utf-8",
            )

            with self.assertRaisesRegex(
                FileNotFoundError,
                "Configured installer.icon does not exist",
            ):
                build_release(project_root, version="1.0.0")

    @unittest.skipIf(os.name != "nt", "Windows icon resource update")
    def test_build_release_uses_installer_icon_for_shortcuts_and_exe(self) -> None:
        with TemporaryDirectory() as temp_dir_str:
            project_root = Path(temp_dir_str)
            subprocess.run(
                ["git", "init"], cwd=project_root, check=True, capture_output=True
            )
            (project_root / "app.cmd").write_text(
                "@echo off\necho hi\n", encoding="utf-8"
            )
            icon_path = project_root / "app.ico"
            _write_sample_icon(icon_path)
            (project_root / "app_builder.yaml").write_text(
                """
app_builder_version: v1.0.0
python_bundled: null
python_venv: null
installer:
  name: Icon Demo
  install_directory: "%localappdata%\\\\IconDemo"
  icon: app.ico
  dist: dist
  paths:
    include:
      - app.cmd
      - app.ico
  start_menu:
    - target: app.cmd
      display_name: Icon Demo
build_hooks: {}
""".strip(),
                encoding="utf-8",
            )

            release = build_release(project_root, version="1.0.0")
            manifest = json.loads(release.manifest_path.read_text(encoding="utf-8"))
            expected_group = _render_icon_group_resource(_read_icon_images(icon_path))
            installer_bytes = release.installer_archive.read_bytes()

        self.assertEqual("app.ico", manifest["start_menu"][0]["icon"])
        self.assertIn(expected_group, installer_bytes)

    @unittest.skipIf(os.name != "nt", "installer execution targets Windows")
    def test_complex_clone_build_install_uninstall_and_github_release(self) -> None:
        with TemporaryDirectory() as temp_dir_str:
            temp_dir = Path(temp_dir_str)
            project_root = temp_dir / "autory-complexity-clone"
            install_dir = temp_dir / "installed clone"
            appdata_dir = temp_dir / "appdata"
            markers_dir = temp_dir / "markers"
            project_root.mkdir()
            markers_dir.mkdir()
            subprocess.run(
                ["git", "init"], cwd=project_root, check=True, capture_output=True
            )
            for directory in ("scripts", "src_py", "native", "docs"):
                (project_root / directory).mkdir()
            (project_root / "README.md").write_text("complex clone\n", encoding="utf-8")
            (project_root / "src_py" / "demo.py").write_text(
                "VALUE = 'python-side'\n", encoding="utf-8"
            )
            (project_root / "native" / "runner.rs").write_text(
                'fn main() { println!("native-side"); }\n', encoding="utf-8"
            )
            (project_root / "scripts" / "generate_assets.py").write_text(
                """
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

root = Path.cwd()
generated = root / "build" / "generated"
generated.mkdir(parents=True, exist_ok=True)
python_source = (root / "src_py" / "demo.py").read_text(encoding="utf-8")
native_source = (root / "native" / "runner.rs").read_text(encoding="utf-8")
digest = hashlib.sha256((python_source + native_source).encode("utf-8")).hexdigest()
(generated / "demo-python.cmd").write_text(
    "@echo off\\necho python-side %app_builder_name%\\n",
    encoding="utf-8",
)
(generated / "demo-native.exe").write_bytes(("native-side:" + digest).encode("utf-8"))
(generated / "post-install.cmd").write_text(
    "@echo off\\n"
    "if not exist \\"%app_builder_install_directory%\\\\bin\\\\demo-native.exe\\" exit /b 9\\n"
    "echo post-install>\\"%app_builder_install_directory%\\\\post-install.txt\\"\\n",
    encoding="utf-8",
)
(generated / "pre-uninstall.cmd").write_text(
    "@echo off\\n"
    "if not exist \\"%app_builder_install_directory%\\\\bin\\\\demo-native.exe\\" exit /b 10\\n"
    "echo pre-uninstall>%~1\\n",
    encoding="utf-8",
)
(generated / "post-uninstall.cmd").write_text(
    "@echo off\\n"
    "if exist \\"%app_builder_install_directory%\\\\bin\\\\demo-native.exe\\" exit /b 11\\n"
    "echo post-uninstall>%~1\\n",
    encoding="utf-8",
)
(generated / "compiled-manifest.json").write_text(
    json.dumps(
        {
            "app": os.environ["app_builder_name"],
            "install_directory": os.environ["app_builder_install_directory"],
            "digest": digest,
        },
        indent=2,
    ),
    encoding="utf-8",
)
(generated / "scratch.tmp").write_text("excluded\\n", encoding="utf-8")
""".strip(),
                encoding="utf-8",
            )
            (project_root / "scripts" / "verify_dist.py").write_text(
                """
from pathlib import Path

root = Path.cwd()
required = [
    root / "build" / "generated" / "demo-python.cmd",
    root / "build" / "generated" / "demo-native.exe",
    root / "build" / "generated" / "compiled-manifest.json",
]
missing = [str(path) for path in required if not path.exists()]
if missing:
    raise SystemExit("missing generated files: " + ", ".join(missing))
""".strip(),
                encoding="utf-8",
            )
            (project_root / "scripts" / "mark_github.py").write_text(
                f"""
from pathlib import Path

Path({str(markers_dir / "github-hook.txt")!r}).write_text("github-hook", encoding="utf-8")
""".strip(),
                encoding="utf-8",
            )
            escaped_install_dir = str(install_dir).replace("\\", "\\\\")
            escaped_pre_uninstall_marker = str(
                markers_dir / "pre-uninstall.txt"
            ).replace("\\", "\\\\")
            escaped_post_uninstall_marker = str(
                markers_dir / "post-uninstall.txt"
            ).replace("\\", "\\\\")
            (project_root / "app_builder.yaml").write_text(
                f"""
app_builder_version: v1.0.0
python_bundled: null
python_venv: null
installer:
  name: Complex Clone
  install_directory: "{escaped_install_dir}"
  dist: dist
  pause_on_exit: false
  paths:
    include:
      - README.md
      - src_py
      - native
      - build/generated
    exclude:
      - build/generated/*.tmp
    remap:
      - [README.md, docs/README.md]
      - [src_py, py]
      - [native, sources/native]
      - [build/generated/demo-python.cmd, bin/demo-python.cmd]
      - [build/generated/demo-native.exe, bin/demo-native.exe]
      - [build/generated/compiled-manifest.json, metadata/compiled-manifest.json]
      - [build/generated/post-install.cmd, hooks/post-install.cmd]
      - [build/generated/pre-uninstall.cmd, hooks/pre-uninstall.cmd]
      - [build/generated/post-uninstall.cmd, hooks/post-uninstall.cmd]
  start_menu:
    - target: bin/demo-python.cmd
      display_name: Complex Clone
  install_hooks:
    post_install:
      - [hooks/post-install.cmd]
    pre_uninstall:
      - [hooks/pre-uninstall.cmd, "{escaped_pre_uninstall_marker}"]
    post_uninstall:
      - [hooks/post-uninstall.cmd, "{escaped_post_uninstall_marker}"]
build_hooks:
  pre_dist:
    - [python, scripts/generate_assets.py]
  post_dist:
    - [python, scripts/verify_dist.py]
  pre_github_release:
    - [python, scripts/mark_github.py]
""".strip(),
                encoding="utf-8",
            )

            release = build_release(project_root, version="9.8.7")

            with ZipFile(release.payload_archive) as payload_zip:
                names = set(payload_zip.namelist())
            self.assertIn("bin/demo-python.cmd", names)
            self.assertIn("bin/demo-native.exe", names)
            self.assertIn("metadata/compiled-manifest.json", names)
            self.assertIn("hooks/post-install.cmd", names)
            self.assertIn("hooks/pre-uninstall.cmd", names)
            self.assertIn("hooks/post-uninstall.cmd", names)
            self.assertIn("docs/README.md", names)
            self.assertIn("py/demo.py", names)
            self.assertIn("sources/native/runner.rs", names)
            self.assertIn("version.txt", names)
            self.assertNotIn("build/generated/scratch.tmp", names)

            gh_calls: list[list[str]] = []
            real_subprocess_run = subprocess.run

            def fake_gh_run(
                args: list[str],
                *,
                cwd: Path | None = None,
                capture_output: bool = False,
                text: bool = False,
                **kwargs: Any,
            ) -> subprocess.CompletedProcess[str]:
                if args[0] != "gh.exe":
                    return cast(
                        subprocess.CompletedProcess[str],
                        real_subprocess_run(
                            args,
                            cwd=cwd,
                            capture_output=capture_output,
                            text=text,
                            **kwargs,
                        ),
                    )
                self.assertIsNotNone(cwd)
                self.assertEqual(project_root, cwd)
                self.assertTrue(capture_output)
                self.assertTrue(text)
                gh_calls.append(args)
                if args[1:3] == ["release", "view"]:
                    if len(gh_calls) == 1:
                        return subprocess.CompletedProcess(
                            args=args, returncode=1, stdout="", stderr="missing"
                        )
                    return subprocess.CompletedProcess(
                        args=args,
                        returncode=0,
                        stdout="https://github.example/releases/9.8.7\n",
                        stderr="",
                    )
                return subprocess.CompletedProcess(
                    args=args, returncode=0, stdout="", stderr=""
                )

            with (
                patch("app_builder.build._resolve_github_cli", return_value="gh.exe"),
                patch("app_builder.build.subprocess.run", side_effect=fake_gh_run),
            ):
                release_url = build_module.upload_release_to_github(
                    project_root, release=release, draft=True
                )

            self.assertEqual("https://github.example/releases/9.8.7", release_url)
            self.assertEqual(
                "github-hook", (markers_dir / "github-hook.txt").read_text()
            )
            create_call = gh_calls[1]
            self.assertIn(str(release.payload_archive), create_call)
            self.assertIn(str(release.installer_archive), create_call)
            self.assertIn(str(release.manifest_path), create_call)
            self.assertIn("--draft", create_call)

            extraction_dir = temp_dir / "extracted-installer"
            extraction_dir.mkdir()
            with ZipFile(release.installer_archive) as installer_zip:
                installer_zip.extractall(extraction_dir)
            env = os.environ.copy()
            env["APPDATA"] = str(appdata_dir)
            subprocess.run(
                ["cmd.exe", "/D", "/C", "call", str(extraction_dir / "install.cmd")],
                check=True,
                env=env,
            )
            self.assertTrue((install_dir / "bin" / "demo-python.cmd").exists())
            self.assertTrue((install_dir / "bin" / "demo-native.exe").exists())
            self.assertEqual(
                "post-install",
                (install_dir / "post-install.txt").read_text(encoding="utf-8").strip(),
            )
            self.assertTrue(
                (
                    appdata_dir
                    / "Microsoft"
                    / "Windows"
                    / "Start Menu"
                    / "Programs"
                    / "Complex Clone"
                    / "Complex Clone.lnk"
                ).exists()
            )

            subprocess.run(
                ["cmd.exe", "/D", "/C", "call", str(install_dir / "uninstall.cmd")],
                check=True,
                env=env,
            )
            deadline = time.monotonic() + 10
            while (
                install_dir.exists()
                or not (markers_dir / "post-uninstall.txt").exists()
            ) and time.monotonic() < deadline:
                time.sleep(0.1)
            self.assertFalse(install_dir.exists())
            self.assertEqual(
                "pre-uninstall",
                (markers_dir / "pre-uninstall.txt").read_text(encoding="utf-8").strip(),
            )
            self.assertEqual(
                "post-uninstall",
                (markers_dir / "post-uninstall.txt")
                .read_text(encoding="utf-8")
                .strip(),
            )
