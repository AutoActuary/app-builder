from __future__ import annotations

import json
import hashlib
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
from app_builder.python_runtime import PythonEnvironmentResult
from app_builder.release_preflight import PublicationPreflightResult
from app_builder.sevenzip import SEVENZIP_DLL_SHA256, SEVENZIP_EXE_SHA256


def _write_sample_icon(icon_path: Path) -> None:
    icon_path.write_bytes(
        files("app_builder").joinpath("assets").joinpath("app-builder.ico").read_bytes()
    )


def _sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


class TestEndToEndBuild(unittest.TestCase):
    def test_build_collects_and_selects_multiple_release_assets(self) -> None:
        with TemporaryDirectory() as temp_dir_str:
            project_root = Path(temp_dir_str)
            subprocess.run(
                ["git", "init"], cwd=project_root, check=True, capture_output=True
            )
            (project_root / "app.cmd").write_text("@echo off\n", encoding="utf-8")
            scripts = project_root / "scripts"
            scripts.mkdir()
            output_script = scripts / "create-outputs.py"
            output_script.write_text(
                "from pathlib import Path\n"
                "root = Path('dist/wheels')\n"
                "root.mkdir(parents=True, exist_ok=True)\n"
                "(root / 'demo-core.whl').write_bytes(b'core-current')\n"
                "(root / 'demo-ui.whl').write_bytes(b'ui-current')\n",
                encoding="utf-8",
            )
            wheels = project_root / "dist" / "wheels"
            wheels.mkdir(parents=True)
            first_wheel = wheels / "demo-core.whl"
            second_wheel = wheels / "demo-ui.whl"
            first_wheel.write_bytes(b"stale")
            second_wheel.write_bytes(b"stale")
            (project_root / "app_builder.yaml").write_text(
                """
app_builder_version: current
python_bundled: null
python_venv: null
installer:
  name: Multi Asset Demo
  install_directory: '%localappdata%\\MultiAssetDemo'
  dist: dist
  paths:
    include: [app.cmd]
outputs:
  - name: wheels
    pattern: wheels/*.whl
    min_matches: 2
    max_matches: 2
publications:
  github:
    outputs: [installer, manifest, checksums, wheels]
build_hooks:
  post_dist:
    - [scripts/create-outputs.py]
""".strip(),
                encoding="utf-8",
            )

            release = build_release(project_root, version="2.0.0")

            self.assertEqual(
                {"payload", "installer", "manifest", "checksums", "wheels"},
                {output.name for output in release.outputs},
            )
            self.assertEqual(
                {
                    release.installer_archive.name,
                    release.manifest_path.name,
                    release.checksums_path.name,
                    first_wheel.name,
                    second_wheel.name,
                },
                {path.name for path in release.publication_artifacts},
            )
            checksums = release.checksums_path.read_text(encoding="ascii")
            self.assertIn(first_wheel.name, checksums)
            self.assertIn(second_wheel.name, checksums)
            self.assertNotIn(release.checksums_path.name, checksums)
            self.assertEqual(b"core-current", first_wheel.read_bytes())
            self.assertEqual(b"ui-current", second_wheel.read_bytes())

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
            self.assertIsNotNone(release.build_log_path)
            assert release.build_log_path is not None
            build_log = release.build_log_path.read_text(encoding="utf-8")
            self.assertIn("Payload file selection", build_log)
            self.assertIn(f"{Path('src') / 'hello.py'} -> src/hello.py", build_log)
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
                self.assertIn("bin/install.ps1", installer_zip.namelist())
                self.assertIn("bin/uninstall.cmd", installer_zip.namelist())
                self.assertIn("bin/uninstall.ps1", installer_zip.namelist())
                self.assertIn(release.payload_archive.name, installer_zip.namelist())
                self.assertNotIn("bin/7z.exe", installer_zip.namelist())
                self.assertNotIn("bin/7z.dll", installer_zip.namelist())
                self.assertNotIn("install.ps1", installer_zip.namelist())
                self.assertNotIn("uninstall.ps1", installer_zip.namelist())
                self.assertNotIn("uninstall.cmd", installer_zip.namelist())
                self.assertNotIn(release.manifest_path.name, installer_zip.namelist())

    def test_build_rejects_missing_shortcut_target_or_icon(self) -> None:
        with TemporaryDirectory() as temp_dir_str:
            project_root = Path(temp_dir_str)
            subprocess.run(
                ["git", "init"], cwd=project_root, check=True, capture_output=True
            )
            (project_root / "app.cmd").write_text("@echo off\n", encoding="utf-8")
            (project_root / "unused.ico").write_bytes(b"not-used")
            config_path = project_root / "app_builder.yaml"
            config_path.write_text(
                """
app_builder_version: current
python_bundled: null
python_venv: null
installer:
  name: Shortcut Contract
  install_directory: '%localappdata%\\ShortcutContract'
  icon: ""
  paths:
    include: [app.cmd]
  start_menu:
    - target: missing.cmd
build_hooks: {}
""".strip(),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(FileNotFoundError, r"start_menu\[0\].target"):
                build_release(project_root, version="1.0.0")

            config_path.write_text(
                config_path.read_text(encoding="utf-8")
                .replace('icon: ""', "icon: unused.ico")
                .replace("target: missing.cmd", "target: app.cmd"),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(FileNotFoundError, r"start_menu\[0\].icon"):
                build_release(project_root, version="1.0.0")

    def test_build_excludes_dist_unless_explicitly_included(self) -> None:
        with TemporaryDirectory() as temp_dir_str:
            project_root = Path(temp_dir_str)
            subprocess.run(
                ["git", "init"], cwd=project_root, check=True, capture_output=True
            )
            (project_root / "app.cmd").write_text("@echo off\n", encoding="utf-8")
            dist = project_root / "dist"
            dist.mkdir()
            (dist / "stale.bin").write_bytes(b"stale")
            config_path = project_root / "app_builder.yaml"
            config_path.write_text(
                """
app_builder_version: current
python_bundled: null
python_venv: null
installer:
  name: Dist Boundary
  install_directory: '%localappdata%\\DistBoundary'
  icon: ""
  paths:
    include: [app.cmd, dist]
build_hooks: {}
""".strip(),
                encoding="utf-8",
            )

            release = build_release(project_root, version="1.0.0")
            with ZipFile(release.payload_archive) as payload_zip:
                self.assertNotIn("dist/stale.bin", payload_zip.namelist())

            config_path.write_text(
                config_path.read_text(encoding="utf-8").replace(
                    "include: [app.cmd, dist]",
                    "include: [app.cmd, dist]\n    include_dist: true",
                ),
                encoding="utf-8",
            )
            release = build_release(project_root, version="1.0.1")
            with ZipFile(release.payload_archive) as payload_zip:
                self.assertIn("dist/stale.bin", payload_zip.namelist())

    def test_post_dist_cannot_change_embedded_payload_contract(self) -> None:
        with TemporaryDirectory() as temp_dir_str:
            project_root = Path(temp_dir_str)
            subprocess.run(
                ["git", "init"], cwd=project_root, check=True, capture_output=True
            )
            (project_root / "app.cmd").write_text("@echo off\n", encoding="utf-8")
            (project_root / "mutate.py").write_text(
                "from pathlib import Path\n"
                "path = Path('dist/sealed-demo-1.0.0.zip')\n"
                "path.write_bytes(path.read_bytes() + b'changed')\n",
                encoding="utf-8",
            )
            (project_root / "app_builder.yaml").write_text(
                """
app_builder_version: current
python_bundled: null
python_venv: null
installer:
  name: Sealed Demo
  install_directory: '%localappdata%\\SealedDemo'
  icon: ""
  paths:
    include: [app.cmd]
build_hooks:
  post_dist:
    - [mutate.py]
""".strip(),
                encoding="utf-8",
            )

            with self.assertRaisesRegex(RuntimeError, "modified sealed release file"):
                build_release(project_root, version="1.0.0")

    def test_installer_manifest_uses_configured_python_hook_path(self) -> None:
        with TemporaryDirectory() as temp_dir_str:
            project_root = Path(temp_dir_str)
            subprocess.run(
                ["git", "init"], cwd=project_root, check=True, capture_output=True
            )
            python_path = project_root / "custom" / "runtime" / "Scripts" / "python.exe"
            python_path.parent.mkdir(parents=True)
            python_path.write_bytes(b"fixture")
            (project_root / "hook.py").write_text("print('hook')\n", encoding="utf-8")
            (project_root / "app_builder.yaml").write_text(
                """
app_builder_version: current
python_bundled: null
python_venv:
  python_version: 3.13.5
  path: custom/runtime
installer:
  name: Python Hook Paths
  install_directory: '%localappdata%\\PythonHookPaths'
  icon: ""
  paths:
    include: [custom/runtime, hook.py]
  install_hooks:
    pre_install:
      - [hook.py]
build_hooks: {}
""".strip(),
                encoding="utf-8",
            )
            environment = PythonEnvironmentResult(
                python_bundled=None,
                python_venv=python_path,
            )
            with patch(
                "app_builder.build._run_dependency_stages", return_value=environment
            ):
                release = build_release(project_root, version="1.0.0")

            manifest = json.loads(release.manifest_path.read_text(encoding="utf-8"))
            self.assertEqual(
                [r"custom\runtime\Scripts\python.exe"],
                manifest["hook_python_candidates"],
            )
            with ZipFile(release.installer_archive) as installer_zip:
                install_script = installer_zip.read("bin/install.ps1").decode("utf-8")
            self.assertIn("$Manifest.hook_python_candidates", install_script)
            self.assertNotIn(
                "Join-Path $WorkingDirectory 'venv\\Scripts\\python.exe'",
                install_script,
            )

    def test_installer_manifest_tracks_remapped_bundled_python_root(self) -> None:
        with TemporaryDirectory() as temp_dir_str:
            project_root = Path(temp_dir_str)
            subprocess.run(
                ["git", "init"], cwd=project_root, check=True, capture_output=True
            )
            bundled_root = project_root / "runtime"
            bundled_python = bundled_root / "python" / "python.exe"
            bundled_python.parent.mkdir(parents=True)
            bundled_python.write_bytes(b"fixture")
            (bundled_root / "pyvenv.cfg").write_text(
                f"home = {(bundled_root / 'python').as_posix()}\n"
                "include-system-site-packages = false\n",
                encoding="utf-8",
            )
            (project_root / "app_builder.yaml").write_text(
                """
app_builder_version: current
python_bundled:
  python_version: 3.13.5
  path: runtime
python_venv: null
installer:
  name: Bundled Python Paths
  install_directory: '%localappdata%\\BundledPythonPaths'
  icon: ""
  paths:
    include: [runtime]
    remap:
      - [runtime, app/runtime]
build_hooks: {}
""".strip(),
                encoding="utf-8",
            )
            environment = PythonEnvironmentResult(
                python_bundled=bundled_python,
                python_venv=None,
            )
            with patch(
                "app_builder.build._run_dependency_stages", return_value=environment
            ):
                release = build_release(project_root, version="1.0.0")

            manifest = json.loads(release.manifest_path.read_text(encoding="utf-8"))
            self.assertEqual("app/runtime", manifest["python_bundled_path"])

    def test_zip_release_rejects_unsafe_or_colliding_remap_destinations(self) -> None:
        with TemporaryDirectory() as temp_dir_str:
            project_root = Path(temp_dir_str)
            subprocess.run(
                ["git", "init"], cwd=project_root, check=True, capture_output=True
            )
            (project_root / "first.txt").write_text("first", encoding="utf-8")
            (project_root / "second.txt").write_text("second", encoding="utf-8")
            config_path = project_root / "app_builder.yaml"
            config_template = """
app_builder_version: current
python_bundled: null
python_venv: null
installer:
  name: Unsafe Demo
  install_directory: "%localappdata%\\\\UnsafeDemo"
  payload_format: zip
  dist: dist
  paths:
    include: [first.txt, second.txt]
    remap:
{remap}
build_hooks: {{}}
""".strip()

            cases = (
                ("      - [first.txt, ../outside.txt]", "Unsafe archive path"),
                (
                    "      - [first.txt, same.txt]\n" "      - [second.txt, SAME.txt]",
                    "destination collision",
                ),
                ("      - [first.txt, version.txt]", "reserved by app-builder"),
            )
            for remap, expected_error in cases:
                with self.subTest(remap=remap):
                    config_path.write_text(
                        config_template.format(remap=remap), encoding="utf-8"
                    )
                    with self.assertRaisesRegex(ValueError, expected_error):
                        build_release(project_root, version="1.0.0")

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

    @unittest.skipIf(os.name != "nt", "7z installer execution targets Windows")
    def test_build_release_with_7z_payload_installs_and_uninstalls(self) -> None:
        with TemporaryDirectory() as temp_dir_str:
            temp_dir = Path(temp_dir_str)
            project_root = temp_dir / "project"
            install_dir = temp_dir / "installed app"
            appdata_dir = temp_dir / "appdata"
            project_root.mkdir()
            subprocess.run(
                ["git", "init"], cwd=project_root, check=True, capture_output=True
            )
            (project_root / "app.cmd").write_text(
                "@echo off\necho hello\n", encoding="utf-8"
            )
            (project_root / "hooks").mkdir()
            (project_root / "hooks" / "post-install.cmd").write_text(
                "@echo off\n"
                'echo post-install>"%app_builder_install_directory%\\post-install.txt"\n',
                encoding="utf-8",
            )
            escaped_install_dir = str(install_dir).replace("\\", "\\\\")
            (project_root / "app_builder.yaml").write_text(
                f"""
app_builder_version: current
python_bundled: null
python_venv: null
installer:
  name: Sevenzip Demo
  install_directory: "{escaped_install_dir}"
  payload_format: 7z
  wait_on_exit: false
  dist: dist
  paths:
    include:
      - app.cmd
      - hooks
    remap:
      - [app.cmd, bin/app.cmd]
  install_hooks:
    post_install:
      - [hooks/post-install.cmd]
build_hooks: {{}}
""".strip(),
                encoding="utf-8",
            )

            release = build_release(project_root, version="7.0.0")

            self.assertEqual(".7z", release.payload_archive.suffix)
            with ZipFile(release.installer_archive) as installer_zip:
                names = set(installer_zip.namelist())
                self.assertIn(release.payload_archive.name, names)
                self.assertIn("bin/7z.exe", names)
                self.assertIn("bin/7z.dll", names)
                self.assertEqual(
                    SEVENZIP_EXE_SHA256,
                    _sha256_bytes(installer_zip.read("bin/7z.exe")),
                )
                self.assertEqual(
                    SEVENZIP_DLL_SHA256,
                    _sha256_bytes(installer_zip.read("bin/7z.dll")),
                )

            env = os.environ.copy()
            env["APPDATA"] = str(appdata_dir)
            env["TEMP"] = str(temp_dir / "runtime-temp")
            env["TMP"] = env["TEMP"]
            Path(env["TEMP"]).mkdir()
            subprocess.run(
                [
                    str(release.installer_archive),
                    "--yes",
                    "--no-wait",
                ],
                check=True,
                env=env,
            )
            self.assertTrue((install_dir / "bin" / "app.cmd").exists())
            self.assertEqual(
                "post-install",
                (install_dir / "post-install.txt").read_text(encoding="utf-8").strip(),
            )

            subprocess.run(
                [
                    "cmd.exe",
                    "/D",
                    "/C",
                    "call",
                    str(install_dir / "bin" / "uninstall.cmd"),
                    "--yes",
                ],
                check=True,
                env=env,
            )
            deadline = time.monotonic() + 10
            while install_dir.exists() and time.monotonic() < deadline:
                time.sleep(0.1)
            self.assertFalse(install_dir.exists())

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
  icon: ""
  install_directory: "{escaped_install_dir}"
  dist: dist
  wait_on_exit: false
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
                    if "--jq" not in args:
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
                patch(
                    "app_builder.build.run_publication_preflight",
                    return_value=PublicationPreflightResult(
                        head_commit="a" * 40,
                        origin_url="https://github.example/AutoActuary/demo.git",
                    ),
                ),
                patch("app_builder.build.subprocess.run", side_effect=fake_gh_run),
            ):
                release_url = build_module.upload_release_to_github(
                    project_root, release=release, draft=True
                )

            self.assertEqual("https://github.example/releases/9.8.7", release_url)
            self.assertEqual(
                "github-hook", (markers_dir / "github-hook.txt").read_text()
            )
            create_call = next(
                call for call in gh_calls if call[1:3] == ["release", "create"]
            )
            self.assertIn(str(release.payload_archive), create_call)
            self.assertIn(str(release.installer_archive), create_call)
            self.assertIn(str(release.manifest_path), create_call)
            self.assertIn(str(release.checksums_path), create_call)
            self.assertIn(str(release.release_notes_path), create_call)
            self.assertIn("a" * 40, create_call)
            self.assertIn("--draft", create_call)

            extraction_dir = temp_dir / "extracted-installer"
            extraction_dir.mkdir()
            with ZipFile(release.installer_archive) as installer_zip:
                installer_zip.extractall(extraction_dir)
            env = os.environ.copy()
            env["APPDATA"] = str(appdata_dir)
            subprocess.run(
                [
                    "cmd.exe",
                    "/D",
                    "/C",
                    "call",
                    str(extraction_dir / "install.cmd"),
                    "--yes",
                ],
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
                [
                    "cmd.exe",
                    "/D",
                    "/C",
                    "call",
                    str(install_dir / "bin" / "uninstall.cmd"),
                    "--yes",
                ],
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
