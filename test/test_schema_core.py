from __future__ import annotations

import unittest
from dataclasses import dataclass, fields

from app_builder.schema_core import (
    ConfigError,
    ConfigMeta,
    config_field,
    default_mapping,
    example_mapping,
    get_config_meta,
    materialize_config,
    materialize_defaults,
    materialize_example,
)


@dataclass(slots=True)
class ChildConfig:
    path: str = config_field(example="src")
    enabled: bool = config_field(default=True, example=False)
    tags: list[str] = config_field(default_factory=list, example_factory=lambda: ["ci"])
    remap: tuple[str, str] = config_field(default=("README.md", "docs/README.md"))


@dataclass(slots=True)
class ExampleConfig:
    name: str = config_field(
        aliases=("title",),
        description="Display name.",
        example="Demo",
    )
    optional_label: str | None = None
    child: ChildConfig = config_field(default_factory=lambda: ChildConfig(path="src"))
    commands: list[str | list[str]] = config_field(default_factory=list)


class TestSchemaCoreMaterialization(unittest.TestCase):
    def test_materializes_supported_shapes_strictly(self) -> None:
        config = materialize_config(
            ExampleConfig,
            {
                "title": "Demo",
                "optional_label": None,
                "child": {
                    "path": "app",
                    "enabled": False,
                    "tags": ["build", "test"],
                    "remap": ["README.md", "docs/README.md"],
                },
                "commands": ["scripts/pre.py", ["python", "scripts/post.py"]],
            },
        )

        self.assertEqual("Demo", config.name)
        self.assertIsNone(config.optional_label)
        self.assertEqual(("README.md", "docs/README.md"), config.child.remap)
        self.assertEqual(
            ["scripts/pre.py", ["python", "scripts/post.py"]],
            config.commands,
        )

    def test_unknown_keys_include_path_and_expected_keys(self) -> None:
        with self.assertRaisesRegex(
            ConfigError,
            r"config\.child: unknown key 'extra'\. Expected one of: "
            r"'path', 'enabled', 'tags', 'remap'\.",
        ):
            materialize_config(
                ExampleConfig,
                {
                    "name": "Demo",
                    "child": {"path": "app", "extra": True},
                },
            )

    def test_wrong_nested_type_includes_precise_path(self) -> None:
        with self.assertRaisesRegex(
            ConfigError,
            r"config\.child\.tags\[1\]: expected string, got int\.",
        ):
            materialize_config(
                ExampleConfig,
                {
                    "name": "Demo",
                    "child": {"path": "app", "tags": ["ok", 3]},
                },
            )

    def test_null_is_only_allowed_for_nullable_annotations(self) -> None:
        config = materialize_config(
            ExampleConfig,
            {"name": "Demo", "optional_label": None},
        )
        self.assertIsNone(config.optional_label)

        with self.assertRaisesRegex(
            ConfigError,
            r"config\.name: null is not allowed\. Expected string\.",
        ):
            materialize_config(ExampleConfig, {"name": None})

    def test_missing_required_fields_fail_even_when_nullable(self) -> None:
        @dataclass(slots=True)
        class NullableRequired:
            value: str | None

        with self.assertRaisesRegex(
            ConfigError,
            r"config\.value: missing required value\. Expected string or null\.",
        ):
            materialize_config(NullableRequired, {})

        self.assertIsNone(materialize_config(NullableRequired, {"value": None}).value)

    def test_duplicate_alias_and_field_is_rejected(self) -> None:
        with self.assertRaisesRegex(
            ConfigError,
            r"config\.name: duplicate keys 'name' and 'title'; use 'name'\.",
        ):
            materialize_config(ExampleConfig, {"name": "Demo", "title": "Other"})

    def test_unsupported_annotations_are_path_aware(self) -> None:
        @dataclass(slots=True)
        class UnsupportedConfig:
            values: dict[str, str]

        with self.assertRaisesRegex(
            ConfigError,
            r"config\.values: unsupported annotation dict\[str, str\]\. "
            r"Expected dataclass, scalar, list, tuple, or union\.",
        ):
            materialize_config(UnsupportedConfig, {"values": {"a": "b"}})


class TestSchemaCoreDefaultsAndExamples(unittest.TestCase):
    def test_default_mapping_omits_required_fields(self) -> None:
        defaults = default_mapping(ExampleConfig)

        self.assertNotIn("name", defaults)
        self.assertEqual(
            {
                "path": "src",
                "enabled": True,
                "tags": [],
                "remap": ["README.md", "docs/README.md"],
            },
            defaults["child"],
        )

    def test_materialize_defaults_fails_when_required_defaults_are_missing(
        self,
    ) -> None:
        with self.assertRaisesRegex(
            ConfigError,
            r"config\.name: missing required value\. Expected string\.",
        ):
            materialize_defaults(ExampleConfig)

    def test_example_mapping_and_materialization_use_examples(self) -> None:
        example = example_mapping(ExampleConfig)
        example["child"]["tags"].append("mutated")

        fresh_example = example_mapping(ExampleConfig)
        self.assertEqual(["ci"], fresh_example["child"]["tags"])
        self.assertEqual("Demo", materialize_example(ExampleConfig).name)
        self.assertEqual("src", materialize_example(ExampleConfig).child.path)

    def test_required_field_without_example_fails_example_mapping(self) -> None:
        @dataclass(slots=True)
        class MissingExample:
            value: str

        with self.assertRaisesRegex(
            ConfigError,
            r"value: missing example for required field\. Expected string\.",
        ):
            example_mapping(MissingExample)

    def test_field_metadata_is_exposed(self) -> None:
        meta = get_config_meta(fields(ExampleConfig)[0])

        self.assertIsInstance(meta, ConfigMeta)
        self.assertEqual(("title",), meta.aliases)
        self.assertEqual("Display name.", meta.description)


if __name__ == "__main__":
    unittest.main()
