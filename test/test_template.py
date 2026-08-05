from __future__ import annotations

import subprocess
import unittest
from dataclasses import fields
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any, get_type_hints

from app_builder.config import load_config
from app_builder.schema import AppBuilderConfig, BuildHooks
from app_builder.template import (
    TEMPLATE_SNAPSHOT_PATH,
    initialize_project,
    render_config_reference_markdown,
    render_help_config_reference_html,
    render_config_template_yaml,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
CONFIG_REFERENCE_PATH = REPO_ROOT / "docs" / "configuration.md"
HELP_HTML_PATH = REPO_ROOT / "docs" / "app-builder-help.html"


class TestTemplateInitialization(unittest.TestCase):
    def test_init_creates_template_and_assets(self) -> None:
        with TemporaryDirectory() as temp_dir_str:
            temp_dir = Path(temp_dir_str)
            subprocess.run(
                ["git", "init"], cwd=temp_dir, check=True, capture_output=True
            )

            config_path = initialize_project(temp_dir, force=False)

            self.assertTrue(config_path.exists())
            self.assertTrue((temp_dir / "application-templates" / "icon.ico").exists())
            self.assertEqual(
                render_config_template_yaml(),
                config_path.read_text(encoding="utf-8"),
            )
            self.assertEqual("MyApp", load_config(config_path).installer.name)

    def test_generated_template_validates(self) -> None:
        with TemporaryDirectory() as temp_dir_str:
            config_path = Path(temp_dir_str) / "app_builder.yaml"
            config_path.write_text(render_config_template_yaml(), encoding="utf-8")

            config = load_config(config_path)

        self.assertEqual("MyApp", config.installer.name)
        self.assertIsNotNone(config.python_bundled)
        assert config.python_bundled is not None
        self.assertEqual("bin/python", config.python_bundled.path)
        self.assertEqual(
            "application-templates/program.cmd",
            config.installer.start_menu[0].target,
        )
        self.assertEqual([], config.outputs)
        self.assertEqual(
            ["payload", "installer", "manifest", "checksums"],
            config.publications.github.outputs,
        )

    def test_template_asset_snapshot_matches_schema_metadata(self) -> None:
        self.assertEqual(
            render_config_template_yaml(),
            TEMPLATE_SNAPSHOT_PATH.read_text(encoding="utf-8"),
        )

    def test_configuration_docs_snapshot_matches_schema_metadata(self) -> None:
        self.assertEqual(
            render_config_reference_markdown(),
            CONFIG_REFERENCE_PATH.read_text(encoding="utf-8"),
        )

    def test_configuration_docs_cover_required_and_command_contracts(self) -> None:
        docs = render_config_reference_markdown()

        self.assertIn("## `config.installer`", docs)
        self.assertIn(
            "| `name` | `string` | yes | required | `MyApp` | Human-facing application name and Windows install identity. It must be a trimmed, filename-safe, non-reserved Windows name. |",
            docs,
        )
        self.assertIn("## Complete app_builder.yaml Template", docs)
        self.assertIn("Hook fields are `list[list[string]]`.", docs)

    def test_complete_template_lists_every_build_hook_and_structured_list_item(
        self,
    ) -> None:
        template = render_config_template_yaml()

        for field_ in fields(BuildHooks):
            self.assertIn(f"  {field_.name}: []", template)
        self.assertIn(
            "# Item fields: name, pattern, min_matches, max_matches.", template
        )

    def test_generated_references_cover_every_schema_field(self) -> None:
        from app_builder.template import _config_anchor

        markdown = render_config_reference_markdown()
        html = render_help_config_reference_html()

        for path, config_type in _walk_config_types("config", AppBuilderConfig):
            markdown_title = "Top-Level Config" if path == "config" else f"`{path}`"
            html_title = "Top-Level Config" if path == "config" else path
            markdown_marker = f"## {markdown_title}\n"
            html_marker = f'<h4 id="{_config_anchor(path)}">{html_title}</h4>'
            self.assertIn(markdown_marker, markdown)
            self.assertIn(html_marker, html)
            markdown_section = markdown.split(markdown_marker, 1)[1].split("\n## ", 1)[
                0
            ]
            html_section = html.split(html_marker, 1)[1].split("<h4 id=", 1)[0]
            for field_ in fields(config_type):
                self.assertIn(f"| `{field_.name}` |", markdown_section)
                self.assertIn(f"<td><code>{field_.name}</code></td>", html_section)

    def test_help_html_config_reference_matches_schema_metadata(self) -> None:
        help_html = HELP_HTML_PATH.read_text(encoding="utf-8")
        fragment = render_help_config_reference_html()

        self.assertIn("<!-- BEGIN GENERATED CONFIG REFERENCE -->", help_html)
        self.assertIn("<!-- END GENERATED CONFIG REFERENCE -->", help_html)
        self.assertIn(fragment, help_html)
        self.assertIn("Complete app_builder.yaml Template", fragment)
        self.assertIn("config.installer.install_hooks", fragment)


def _walk_config_types(
    path: str, config_type: type[Any]
) -> list[tuple[str, type[Any]]]:
    from app_builder.template import (
        _list_dataclass_item_type,
        _nested_dataclass_type,
    )

    result = [(path, config_type)]
    hints = get_type_hints(config_type, include_extras=True)
    for field_ in fields(config_type):
        annotation = hints[field_.name]
        nested_type = _nested_dataclass_type(annotation)
        list_item_type = _list_dataclass_item_type(annotation)
        if nested_type is not None:
            result.extend(_walk_config_types(f"{path}.{field_.name}", nested_type))
        elif list_item_type is not None:
            result.extend(_walk_config_types(f"{path}.{field_.name}[]", list_item_type))
    return result
