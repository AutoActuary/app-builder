from __future__ import annotations

import unittest
from pathlib import Path
from urllib.parse import unquote, urlparse

from click.testing import CliRunner

from app_builder.main import main


class TestCliHelp(unittest.TestCase):
    def test_help_starts_with_html_help_link(self) -> None:
        result = CliRunner().invoke(main, ["--help"])

        self.assertEqual(0, result.exit_code)
        first_line = result.output.splitlines()[0]
        self.assertTrue(first_line.startswith("Full help: file:///"), first_line)
        self.assertIn("app-builder-help.html", first_line)

    def test_docs_help_html_exists(self) -> None:
        help_path = (
            Path(__file__).resolve().parents[1]
            / "docs"
            / "app-builder-help.html"
        )

        self.assertTrue(help_path.is_file())
        self.assertIn("app-builder Help", help_path.read_text(encoding="utf-8"))

    def test_help_link_points_to_docs_copy(self) -> None:
        result = CliRunner().invoke(main, ["--help"])

        self.assertEqual(0, result.exit_code)
        first_line = result.output.splitlines()[0]
        url = first_line.removeprefix("Full help: ")
        parsed = urlparse(url)
        path_text = unquote(parsed.path)
        if len(path_text) >= 3 and path_text[0] == "/" and path_text[2] == ":":
            path_text = path_text[1:]
        help_path = Path(path_text)

        self.assertEqual("file", parsed.scheme)
        self.assertTrue(help_path.is_file())
        self.assertIn("docs", help_path.parts)

    def test_help_html_has_single_source_in_docs(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        docs_help = repo_root / "docs" / "app-builder-help.html"
        old_assets_help = repo_root / "app_builder" / "assets" / "app-builder-help.html"

        self.assertTrue(docs_help.is_file())
        self.assertFalse(old_assets_help.exists())


if __name__ == "__main__":
    unittest.main()
