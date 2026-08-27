from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
from urllib.parse import unquote, urlparse

from click.testing import CliRunner

from app_builder.main import _help_html_url, main


class TestCliHelp(unittest.TestCase):
    def test_help_starts_with_html_help_link(self) -> None:
        result = CliRunner().invoke(main, ["--help"])

        self.assertEqual(0, result.exit_code)
        first_line = result.output.splitlines()[0]
        self.assertTrue(first_line.startswith("Full help: file:///"), first_line)
        self.assertIn("app-builder-help.html", first_line)

    def test_docs_help_html_exists(self) -> None:
        help_path = (
            Path(__file__).resolve().parents[1] / "docs" / "app-builder-help.html"
        )

        self.assertTrue(help_path.is_file())
        help_html = help_path.read_text(encoding="utf-8")
        self.assertIn("app-builder Help", help_html)
        self.assertIn("From Project To Installation", help_html)
        self.assertIn("Project folder", help_html)
        self.assertIn("Publishing Is Optional", help_html)
        self.assertNotIn("<h3>Config</h3>", help_html)

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

    def test_wheel_data_file_location_is_used_outside_source_checkout(self) -> None:
        with TemporaryDirectory() as temp_dir_str:
            prefix = Path(temp_dir_str) / "venv"
            package_file = prefix / "Lib" / "site-packages" / "app_builder" / "main.py"
            installed_help = (
                prefix / "share" / "app-builder" / "docs" / "app-builder-help.html"
            )
            installed_help.parent.mkdir(parents=True)
            installed_help.write_text("installed help", encoding="utf-8")

            with (
                patch("app_builder.main.__file__", str(package_file)),
                patch("app_builder.main.sys.prefix", str(prefix)),
            ):
                help_url = _help_html_url()

        self.assertEqual(installed_help.resolve().as_uri(), help_url)

    def test_user_site_wheel_data_file_location_is_used(self) -> None:
        with TemporaryDirectory() as temp_dir_str:
            prefix = Path(temp_dir_str) / "system"
            user_data = Path(temp_dir_str) / "user"
            package_file = prefix / "Lib" / "site-packages" / "app_builder" / "main.py"
            installed_help = (
                user_data / "share" / "app-builder" / "docs" / "app-builder-help.html"
            )
            installed_help.parent.mkdir(parents=True)
            installed_help.write_text("user help", encoding="utf-8")

            with (
                patch("app_builder.main.__file__", str(package_file)),
                patch("app_builder.main.sys.prefix", str(prefix)),
                patch(
                    "app_builder.main.sysconfig.get_path",
                    return_value=str(user_data),
                ),
            ):
                help_url = _help_html_url()

        self.assertEqual(installed_help.resolve().as_uri(), help_url)


if __name__ == "__main__":
    unittest.main()
