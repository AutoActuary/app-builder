from __future__ import annotations

import unittest
from typing import Any

from app_builder import pydantic_models
from app_builder.schema import ConfigError, load_app_builder_config
from app_builder.schema_export import (
    app_builder_json_schema,
    validate_app_builder_mapping,
)

VALID_MAPPING = {
    "installer": {
        "name": "Demo",
        "install_directory": r"%localappdata%\Demo",
        "paths": {"include": ["src"]},
    },
    "build_hooks": {
        "pre_dist": [
            ["scripts/pre-build.cmd"],
            ["python", "-m", "pytest"],
        ]
    },
}


def _validate_pydantic_model(model_type: Any, value: object) -> Any:
    if hasattr(model_type, "model_validate"):
        return model_type.model_validate(value)
    return model_type.parse_obj(value)


class TestSchemaExport(unittest.TestCase):
    def test_json_schema_is_derived_from_config_dataclasses(self) -> None:
        schema = app_builder_json_schema()

        self.assertEqual("AppBuilderConfig", schema["title"])
        self.assertFalse(schema["additionalProperties"])
        self.assertEqual(["installer"], schema["required"])
        self.assertEqual(
            ["name", "install_directory"],
            schema["properties"]["installer"]["required"],
        )
        self.assertFalse(schema["properties"]["installer"]["additionalProperties"])

    def test_json_schema_describes_nullable_sections_and_hook_commands(self) -> None:
        schema = app_builder_json_schema()

        python_bundled_schema = schema["properties"]["python_bundled"]
        self.assertIn({"type": "null"}, python_bundled_schema["anyOf"])

        hook_items = schema["properties"]["build_hooks"]["properties"]["pre_dist"][
            "items"
        ]
        self.assertEqual(
            {"type": "array", "items": {"type": "string"}},
            hook_items,
        )

    def test_validate_mapping_uses_primary_loader_errors(self) -> None:
        with self.assertRaisesRegex(
            ConfigError,
            r"config\.installer: unknown key 'extra'\. Expected one of:",
        ):
            validate_app_builder_mapping(
                {
                    "installer": {
                        "name": "Demo",
                        "install_directory": r"%localappdata%\Demo",
                        "extra": True,
                    }
                }
            )

    def test_pydantic_compatibility_validate_mapping_uses_loader(self) -> None:
        validated = pydantic_models.validate_mapping(VALID_MAPPING)

        self.assertEqual("Demo", validated["installer"]["name"])
        self.assertEqual(
            [["scripts/pre-build.cmd"], ["python", "-m", "pytest"]],
            validated["build_hooks"]["pre_dist"],
        )

    @unittest.skipUnless(
        pydantic_models.PYDANTIC_AVAILABLE,
        "optional pydantic dependency is not installed",
    )
    def test_pydantic_model_is_derived_and_rejects_extra_keys(self) -> None:
        model_type = pydantic_models.AppBuilderPydanticModel
        model = _validate_pydantic_model(model_type, VALID_MAPPING)

        self.assertEqual("Demo", model.installer.name)
        with self.assertRaises(Exception):
            _validate_pydantic_model(model_type, {**VALID_MAPPING, "surprise": True})
        with self.assertRaises(Exception):
            _validate_pydantic_model(
                model_type,
                {
                    "installer": {
                        "name": "Demo",
                        "install_directory": r"%localappdata%\Demo",
                        "extra": True,
                    }
                },
            )

    @unittest.skipUnless(
        pydantic_models.PYDANTIC_AVAILABLE,
        "optional pydantic dependency is not installed",
    )
    def test_to_pydantic_model_wraps_validated_config(self) -> None:
        config = validate_app_builder_mapping(VALID_MAPPING)
        app_config = load_app_builder_config(config)

        model = pydantic_models.to_pydantic_model(app_config)

        self.assertEqual("Demo", model.installer.name)
