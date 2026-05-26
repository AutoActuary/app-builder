from __future__ import annotations

import importlib
import types
from collections.abc import Callable, Mapping
from dataclasses import Field as DataclassField
from dataclasses import MISSING, fields, is_dataclass
from typing import Any
from typing import Union as TypingUnion
from typing import get_args, get_origin, get_type_hints

from .schema import AppBuilderConfig, load_app_builder_config
from .schema_core import REQUIRED, get_config_meta
from .schema_export import app_builder_json_schema

_NONE_TYPE = type(None)


AppBuilderPydanticModel: Any = None
PYDANTIC_AVAILABLE = False


def validate_mapping(value: Mapping[str, Any]) -> dict[str, Any]:
    """Validate through the strict dataclass loader and return plain data."""

    return load_app_builder_config(value).to_dict()


def to_pydantic_model(config: AppBuilderConfig) -> Any:
    """Return an optional Pydantic model derived from dataclass metadata."""

    if not PYDANTIC_AVAILABLE:
        return None
    model_type = AppBuilderPydanticModel
    if hasattr(model_type, "model_validate"):
        return model_type.model_validate(config.to_dict())
    return model_type.parse_obj(config.to_dict())


def _derive_pydantic_model(config_type: type[Any]) -> Any | None:
    try:
        pydantic = importlib.import_module("pydantic")
    except ImportError:
        return None
    state = _PydanticDerivationState(pydantic)
    return state.model_for_dataclass(config_type)


class _PydanticDerivationState:
    def __init__(self, pydantic: Any) -> None:
        self._pydantic = pydantic
        self._models: dict[type[Any], Any] = {}

    def model_for_dataclass(self, config_type: type[Any]) -> Any:
        cached = self._models.get(config_type)
        if cached is not None:
            return cached

        model_name = (
            "AppBuilderPydanticModel"
            if config_type is AppBuilderConfig
            else f"{config_type.__name__}PydanticModel"
        )
        hints = get_type_hints(config_type, include_extras=True)
        field_definitions: dict[str, tuple[Any, Any]] = {}
        for field_ in fields(config_type):
            annotation = self._convert_annotation(hints[field_.name])
            field_definitions[field_.name] = (
                annotation,
                self._pydantic_field(field_),
            )

        create_model = self._pydantic.create_model
        model_config = self._model_config()
        if config_type is AppBuilderConfig and isinstance(model_config, dict):
            model_config["json_schema_extra"] = app_builder_json_schema()
        model_type = create_model(
            model_name,
            __config__=model_config,
            **field_definitions,
        )
        self._models[config_type] = model_type
        return model_type

    def _convert_annotation(self, annotation: Any) -> Any:
        origin = get_origin(annotation)
        args = get_args(annotation)

        if _is_dataclass_type(annotation):
            return self.model_for_dataclass(annotation)
        if origin is list and len(args) == 1:
            list_type: Any = list
            return list_type[self._convert_annotation(args[0])]
        if origin is tuple:
            tuple_type: Any = tuple
            return tuple_type[
                tuple(
                    Ellipsis if arg is Ellipsis else self._convert_annotation(arg)
                    for arg in args
                )
            ]
        if _is_union(origin):
            union_type: Any = TypingUnion
            return union_type[
                tuple(
                    arg if arg is _NONE_TYPE else self._convert_annotation(arg)
                    for arg in args
                )
            ]
        return annotation

    def _pydantic_field(self, field_: DataclassField[Any]) -> Any:
        kwargs: dict[str, Any] = {}
        meta = get_config_meta(field_)
        if meta.description:
            kwargs["description"] = meta.description
        if meta.example is not REQUIRED:
            kwargs["json_schema_extra"] = {"examples": [_plain_value(meta.example)]}
        elif meta.example_factory is not None:
            kwargs["json_schema_extra"] = {
                "examples": [_plain_value(meta.example_factory())]
            }

        field_factory = self._pydantic.Field
        if field_.default is not MISSING:
            return field_factory(default=_plain_value(field_.default), **kwargs)
        if field_.default_factory is not MISSING:
            return field_factory(
                default_factory=_plain_default_factory(field_.default_factory),
                **kwargs,
            )
        return field_factory(..., **kwargs)

    def _model_config(self) -> Any:
        config_dict = getattr(self._pydantic, "ConfigDict", None)
        if config_dict is not None:
            return config_dict(extra="forbid")
        return type("Config", (), {"extra": "forbid"})


def _plain_default_factory(factory: Callable[[], Any]) -> Callable[[], Any]:
    def build_default() -> Any:
        return _plain_value(factory())

    return build_default


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


def _is_dataclass_type(value: Any) -> bool:
    return isinstance(value, type) and is_dataclass(value)


def _is_union(origin: Any) -> bool:
    return origin is TypingUnion or origin is types.UnionType


AppBuilderPydanticModel = _derive_pydantic_model(AppBuilderConfig)
PYDANTIC_AVAILABLE = AppBuilderPydanticModel is not None
