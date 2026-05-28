from __future__ import annotations

import unittest
from pathlib import Path

from click.testing import CliRunner

from app_builder.main import main


class TestCliHelp(unittest.TestCase):
    def test_help_starts_with_html_help_link(self) -> None:
        result = CliRunner().invoke(main, ["--help"])

        self.assertEqual(0, result.exit_code)
        first_line = result.output.splitlines()[0]
        self.assertTrue(first_line.startswith("Full help: file:///"), first_line)
        self.assertIn("app-builder-help.html", first_line)

    def test_packaged_help_html_exists(self) -> None:
        help_path = (
            Path(__file__).resolve().parents[1]
            / "app_builder"
            / "assets"
            / "app-builder-help.html"
        )

        self.assertTrue(help_path.is_file())
        self.assertIn("app-builder Help", help_path.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
