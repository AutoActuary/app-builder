from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from zipfile import ZipFile

from app_builder.build import _render_meta_launcher_config, build_release
from app_builder.exewrap import EXE_WRAP_CONFIG_START_MARKER
from scripts.build_legacy_0x_bridge import _render_legacy_bridge_launcher_config


class TestAppBuilderMetaLauncher(unittest.TestCase):
    def test_meta_launcher_config_preserves_cwd_and_passes_args(self) -> None:
        config = _render_meta_launcher_config().decode("utf-8")

        self.assertNotIn('"cwd"', config)
        self.assertIn('"@{exe_dir}\\\\bin\\\\python\\\\python\\\\python.exe"', config)
        self.assertIn('"-P"', config)
        self.assertIn('"app_builder_meta"', config)
        self.assertIn("@{args}", config)
        self.assertIn('"APP_BUILDER_INSTALL_ROOT": "@{exe_dir}"', config)
        self.assertIn('"PYTHONPATH": "@{exe_dir}"', config)
        self.assertGreater(config.rfind('"command"'), config.rfind('"env"'))

    def test_legacy_bridge_launcher_config_preserves_cwd_and_uses_exe_dir(self) -> None:
        config = _render_legacy_bridge_launcher_config().decode("utf-8")

        self.assertNotIn('"cwd"', config)
        self.assertNotIn("@{install_root}", config)
        self.assertNotIn("@{bridge_dir}", config)
        self.assertIn(
            '"@{exe_dir}\\\\..\\\\bin\\\\python\\\\python\\\\python.exe"', config
        )
        self.assertIn('"@{exe_dir}\\\\app-builder-legacy.py"', config)
        self.assertIn('"PYTHONPATH": "@{exe_dir}\\\\site-packages;@{exe_dir}"', config)
        self.assertGreater(config.rfind('"command"'), config.rfind('"env"'))

    def test_app_builder_dogfood_payload_contains_meta_launcher(self) -> None:
        with TemporaryDirectory() as temp_dir_str:
            project_root = Path(temp_dir_str)
            (project_root / "README.md").write_text("app-builder\n", encoding="utf-8")
            (project_root / "app_builder.yaml").write_text(
                """
app_builder_version: current
python_bundled: null
python_venv: null
installer:
  name: app-builder
  install_directory: "%localappdata%\\\\app-builder"
  dist: dist
  paths:
    include:
      - README.md
build_hooks: {}
""".strip(),
                encoding="utf-8",
            )

            release = build_release(project_root, version="1.0.0")

            with ZipFile(release.payload_archive) as payload_zip:
                names = set(payload_zip.namelist())
                launcher = payload_zip.read("app-builder.exe")

        self.assertIn("app-builder.exe", names)
        self.assertIn(EXE_WRAP_CONFIG_START_MARKER, launcher)
        embedded_config = launcher.rsplit(EXE_WRAP_CONFIG_START_MARKER, 1)[1].decode(
            "utf-8"
        )
        self.assertNotIn('"cwd"', embedded_config)
        self.assertIn('"app_builder_meta"', embedded_config)
        self.assertGreater(
            embedded_config.rfind('"command"'), embedded_config.rfind('"env"')
        )


if __name__ == "__main__":
    unittest.main()
