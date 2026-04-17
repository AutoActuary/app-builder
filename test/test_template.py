from __future__ import annotations

import subprocess
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from app_builder.template import initialize_project


class TestTemplateInitialization(unittest.TestCase):
    def test_init_creates_template_and_assets(self) -> None:
        with TemporaryDirectory() as temp_dir_str:
            temp_dir = Path(temp_dir_str)
            subprocess.run(["git", "init"], cwd=temp_dir, check=True, capture_output=True)

            config_path = initialize_project(temp_dir, force=False)

            self.assertTrue(config_path.exists())
            self.assertTrue((temp_dir / "application-templates" / "icon.ico").exists())
            self.assertIn("installer:", config_path.read_text(encoding="utf-8"))
