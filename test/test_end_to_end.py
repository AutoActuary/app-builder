from __future__ import annotations

import json
import subprocess
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from zipfile import ZipFile

from app_builder.build import build_release


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

            manifest = json.loads(release.manifest_path.read_text(encoding="utf-8"))
            self.assertEqual("Demo App", manifest["name"])
            self.assertEqual("1.2.3", manifest["version"])

            with ZipFile(release.payload_archive) as payload_zip:
                self.assertEqual(
                    {"docs/README.md", "src/hello.py", "version.txt"},
                    set(payload_zip.namelist()),
                )

            with ZipFile(release.installer_archive) as installer_zip:
                self.assertIn("install.cmd", installer_zip.namelist())
                self.assertIn(release.payload_archive.name, installer_zip.namelist())
