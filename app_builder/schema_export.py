from __future__ import annotations

import types
from collections.abc import Mapping
from dataclasses import Field, MISSING, fields, is_dataclass
from typing import Any, TypeGuard, Union, cast, get_args, get_origin, get_type_hints

from .schema_core import ConfigError, REQUIRED, get_config_meta

_NONE_TYPE = type(None)


def json_schema_for_config(
    config_type: type[Any],
    *,
    title: str | None = None,
) -> dict[str, Any]:
    """Derive a JSON Schema object from dataclass config metadata."""

    if not _is_dataclass_type(config_type):
        raise ConfigError("config", f"expected dataclass type, got {config_type!r}.")
    schema = _schema_for_dataclass(config_type)
    schema["$schema"] = "https://json-schema.org/draft/2020-12/schema"
    schema["title"] = title or config_type.__name__
    return schema


def app_builder_json_schema() -> dict[str, Any]:
    from .schema import AppBuilderConfig

    return json_schema_for_config(AppBuilderConfig, title="AppBuilderConfig")


def validate_app_builder_mapping(value: Mapping[str, Any]) -> dict[str, Any]:
    """Validate through the primary loader and return a plain representation."""

    from .schema import load_app_builder_config

    return load_app_builder_config(value).to_dict()


def _schema_for_dataclass(config_type: type[Any]) -> dict[str, Any]:
    hints = get_type_hints(config_type, include_extras=True)
    properties: dict[str, Any] = {}
    required: list[str] = []
    for field_ in _dataclass_fields(config_type):
        field_schema = _schema_for_annotation(hints[field_.name])
        _apply_field_metadata(field_schema, field_)
        properties[field_.name] = field_schema
        if field_.default is MISSING and field_.default_factory is MISSING:
            required.append(field_.name)

    schema: dict[str, Any] = {
        "type": "object",
        "additionalProperties": False,
        "properties": properties,
    }
    if required:
        schema["required"] = required
    return schema


def _schema_for_annotation(annotation: Any) -> dict[str, Any]:
    origin = get_origin(annotation)
    args = get_args(annotation)

    if annotation is Any:
        return {}
    if annotation is str:
        return {"type": "string"}
    if annotation is bool:
        return {"type": "boolean"}
    if annotation is int:
        return {"type": "integer"}
    if annotation is float:
        return {"type": "number"}
    if annotation is _NONE_TYPE:
        return {"type": "null"}
    if _is_dataclass_type(annotation):
        return _schema_for_dataclass(annotation)
    if origin is list and len(args) == 1:
        return {"type": "array", "items": _schema_for_annotation(args[0])}
    if origin is tuple:
        return _tuple_schema(args)
    if _is_union(origin):
        return {"anyOf": [_schema_for_annotation(arg) for arg in args]}
    raise ConfigError(
        "config",
        f"unsupported annotation {_format_annotation(annotation)}. "
        "Expected dataclass, scalar, list, tuple, or union.",
    )


def _tuple_schema(args: tuple[Any, ...]) -> dict[str, Any]:
    if len(args) == 2 and args[1] is Ellipsis:
        return {"type": "array", "items": _schema_for_annotation(args[0])}
    return {
        "type": "array",
        "prefixItems": [_schema_for_annotation(arg) for arg in args],
        "minItems": len(args),
        "maxItems": len(args),
    }


def _apply_field_metadata(schema: dict[str, Any], field_: Field[Any]) -> None:
    meta = get_config_meta(field_)
    if meta.description:
        schema["description"] = meta.description
    if meta.aliases:
        schema["x-aliases"] = list(meta.aliases)
    if meta.example is not REQUIRED:
        schema["examples"] = [_plain_value(meta.example)]
    elif meta.example_factory is not None:
        schema["examples"] = [_plain_value(meta.example_factory())]

    default_factory = field_.default_factory
    if field_.default is not MISSING:
        schema["default"] = _plain_value(field_.default)
    elif default_factory is not MISSING:
        schema["default"] = _plain_value(default_factory())


def _plain_value(value: Any) -> Any:
    if is_dataclass(value):
        return {
            field_.name: _plain_value(getattr(value, field_.name))
            for field_ in fields(value)
        }
    if isinstance(value, list):
        return [_plain_value(item) for item in value]
    if isinstance(value, tuple):
        return [_plain_value(item) for item in value]
    if isinstance(value, dict):
        return {_plain_value(key): _plain_value(item) for key, item in value.items()}
    return value


def _format_annotation(annotation: Any) -> str:
    return str(annotation).replace("typing.", "")


def _is_union(origin: Any) -> bool:
    return origin is Union or origin is types.UnionType


def _is_dataclass_type(value: Any) -> TypeGuard[type[Any]]:
    return isinstance(value, type) and is_dataclass(value)


def _dataclass_fields(config_type: type[Any]) -> tuple[Field[Any], ...]:
    return fields(cast(Any, config_type))
