from __future__ import annotations

import types
from collections.abc import Callable, Iterable, Mapping
from dataclasses import Field, MISSING, dataclass, field, fields, is_dataclass
from typing import (
    Any,
    TypeGuard,
    TypeVar,
    Union,
    cast,
    get_args,
    get_origin,
    get_type_hints,
)


class _Required:
    def __repr__(self) -> str:
        return "REQUIRED"


REQUIRED = _Required()
_CONFIG_META_KEY = "app_builder_config"
_NONE_TYPE = type(None)
T = TypeVar("T")


class ConfigError(ValueError):
    """Configuration validation error with a stable, path-aware message."""

    def __init__(self, path: str, message: str) -> None:
        self.path = path
        self.message = message
        super().__init__(f"{path}: {message}")


@dataclass(frozen=True, slots=True)
class ConfigMeta:
    description: str | None = None
    aliases: tuple[str, ...] = ()
    example: Any = REQUIRED
    example_factory: Callable[[], Any] | None = None


def config_field(
    *,
    default: Any = REQUIRED,
    default_factory: Callable[[], Any] | _Required = REQUIRED,
    description: str | None = None,
    doc: str | None = None,
    aliases: Iterable[str] = (),
    example: Any = REQUIRED,
    example_factory: Callable[[], Any] | _Required = REQUIRED,
) -> Any:
    """Create a dataclass field carrying config schema metadata."""

    if description is not None and doc is not None:
        raise TypeError("Use either description or doc, not both.")
    if default is not REQUIRED and default_factory is not REQUIRED:
        raise TypeError("Use either default or default_factory, not both.")
    if example is not REQUIRED and example_factory is not REQUIRED:
        raise TypeError("Use either example or example_factory, not both.")
    if default_factory is not REQUIRED and not callable(default_factory):
        raise TypeError("default_factory must be callable.")
    if example_factory is not REQUIRED and not callable(example_factory):
        raise TypeError("example_factory must be callable.")

    aliases_tuple = tuple(aliases)
    resolved_example_factory = (
        None
        if example_factory is REQUIRED
        else cast(Callable[[], Any], example_factory)
    )
    meta = ConfigMeta(
        description=description if description is not None else doc,
        aliases=aliases_tuple,
        example=example,
        example_factory=resolved_example_factory,
    )
    kwargs: dict[str, Any] = {"metadata": {_CONFIG_META_KEY: meta}}
    if default is not REQUIRED:
        kwargs["default"] = default
    elif default_factory is not REQUIRED:
        kwargs["default_factory"] = default_factory
    return field(**kwargs)


def get_config_meta(field_: Field[Any]) -> ConfigMeta:
    value = field_.metadata.get(_CONFIG_META_KEY)
    if isinstance(value, ConfigMeta):
        return value
    return ConfigMeta()


def materialize_config(
    config_type: type[T],
    value: Mapping[str, Any],
    *,
    path: str = "config",
) -> T:
    """Strictly materialize a dataclass config object from a YAML-like mapping."""

    if not _is_dataclass_type(config_type):
        raise ConfigError(path, f"expected dataclass type, got {config_type!r}.")
    if not isinstance(value, Mapping):
        raise ConfigError(path, f"expected mapping, got {_type_name(value)}.")
    return _materialize_dataclass(cast(type[T], config_type), value, path)


def materialize_defaults(config_type: type[T], *, path: str = "config") -> T:
    return materialize_config(config_type, default_mapping(config_type), path=path)


def materialize_example(config_type: type[T], *, path: str = "config") -> T:
    return materialize_config(config_type, example_mapping(config_type), path=path)


def default_mapping(config_type: type[Any]) -> dict[str, Any]:
    """Return defaults as plain mappings, omitting fields that have no default."""

    if not _is_dataclass_type(config_type):
        raise ConfigError("config", f"expected dataclass type, got {config_type!r}.")
    result: dict[str, Any] = {}
    for field_ in _dataclass_fields(config_type):
        if field_.default is not MISSING:
            result[field_.name] = _plain_value(field_.default)
        elif field_.default_factory is not MISSING:
            result[field_.name] = _plain_value(field_.default_factory())
    return result


def example_mapping(config_type: type[Any]) -> dict[str, Any]:
    """Return example values as plain mappings, using defaults as fallback."""

    if not _is_dataclass_type(config_type):
        raise ConfigError("config", f"expected dataclass type, got {config_type!r}.")
    hints = get_type_hints(config_type, include_extras=True)
    result: dict[str, Any] = {}
    for field_ in _dataclass_fields(config_type):
        meta = get_config_meta(field_)
        annotation = hints[field_.name]
        nested_type = _nested_dataclass_type(annotation)
        if meta.example is not REQUIRED:
            result[field_.name] = _plain_value(meta.example)
        elif meta.example_factory is not None:
            result[field_.name] = _plain_value(meta.example_factory())
        elif nested_type is not None and field_.default is not None:
            result[field_.name] = example_mapping(nested_type)
        elif field_.default is not MISSING:
            result[field_.name] = _plain_value(field_.default)
        elif field_.default_factory is not MISSING:
            result[field_.name] = _plain_value(field_.default_factory())
        else:
            if nested_type is None:
                raise ConfigError(
                    field_.name,
                    f"missing example for required field. Expected {_describe_type(annotation)}.",
                )
            result[field_.name] = example_mapping(nested_type)
    return result


def _materialize_dataclass(
    config_type: type[T],
    value: Mapping[str, Any],
    path: str,
) -> T:
    hints = get_type_hints(config_type, include_extras=True)
    field_names = {field_.name for field_ in _dataclass_fields(config_type)}
    alias_to_field: dict[str, str] = {}
    for field_ in _dataclass_fields(config_type):
        for alias in get_config_meta(field_).aliases:
            if alias in field_names:
                raise ConfigError(
                    _join_path(path, field_.name),
                    f"alias {alias!r} conflicts with a field name.",
                )
            existing_alias = alias_to_field.get(alias)
            if existing_alias is not None:
                raise ConfigError(
                    _join_path(path, field_.name),
                    f"alias {alias!r} is already used by {existing_alias!r}.",
                )
            alias_to_field[alias] = field_.name

    expected_keys = _expected_keys(config_type)
    resolved: dict[str, tuple[str, Any]] = {}
    unknown_keys: list[str] = []
    for key, item in value.items():
        if not isinstance(key, str):
            raise ConfigError(path, f"expected string keys, got {_type_name(key)}.")
        field_name = key if key in field_names else alias_to_field.get(key)
        if field_name is None:
            unknown_keys.append(key)
            continue
        existing_entry = resolved.get(field_name)
        if existing_entry is not None:
            raise ConfigError(
                _join_path(path, field_name),
                f"duplicate keys {existing_entry[0]!r} and {key!r}; use {field_name!r}.",
            )
        resolved[field_name] = (key, item)

    if unknown_keys:
        expected = ", ".join(repr(key) for key in expected_keys)
        unknown = ", ".join(repr(key) for key in unknown_keys)
        raise ConfigError(path, f"unknown key {unknown}. Expected one of: {expected}.")

    kwargs: dict[str, Any] = {}
    for field_ in _dataclass_fields(config_type):
        field_path = _join_path(path, field_.name)
        annotation = hints[field_.name]
        raw_entry = resolved.get(field_.name)
        if raw_entry is not None:
            kwargs[field_.name] = _materialize_value(
                annotation,
                raw_entry[1],
                field_path,
            )
        elif field_.default is not MISSING:
            kwargs[field_.name] = _materialize_value(
                annotation,
                _plain_value(field_.default),
                field_path,
            )
        elif field_.default_factory is not MISSING:
            kwargs[field_.name] = _materialize_value(
                annotation,
                _plain_value(field_.default_factory()),
                field_path,
            )
        else:
            raise ConfigError(
                field_path,
                f"missing required value. Expected {_describe_type(annotation)}.",
            )
    return config_type(**kwargs)


def _materialize_value(annotation: Any, value: Any, path: str) -> Any:
    origin = get_origin(annotation)
    args = get_args(annotation)

    if annotation is Any:
        return value
    if _is_union(origin):
        if value is None:
            if _NONE_TYPE in args:
                return None
            raise ConfigError(
                path,
                f"null is not allowed. Expected {_describe_type(annotation)}.",
            )
        errors: list[ConfigError] = []
        for option in args:
            if option is _NONE_TYPE:
                continue
            try:
                return _materialize_value(option, value, path)
            except ConfigError as error:
                errors.append(error)
        raise ConfigError(
            path,
            f"expected {_describe_type(annotation)}, got {_type_name(value)}.",
        ) from (errors[0] if errors else None)
    if value is None:
        raise ConfigError(
            path, f"null is not allowed. Expected {_describe_type(annotation)}."
        )
    if _is_dataclass_type(annotation):
        if not isinstance(value, Mapping):
            raise ConfigError(path, f"expected mapping, got {_type_name(value)}.")
        return _materialize_dataclass(annotation, value, path)
    if origin is list:
        if len(args) != 1:
            raise ConfigError(
                path, f"unsupported annotation {_format_annotation(annotation)}."
            )
        if not isinstance(value, list):
            raise ConfigError(path, f"expected list, got {_type_name(value)}.")
        return [
            _materialize_value(args[0], item, _index_path(path, index))
            for index, item in enumerate(value)
        ]
    if origin is tuple:
        return _materialize_tuple(annotation, value, path)
    if annotation is str:
        if not isinstance(value, str):
            raise ConfigError(path, f"expected string, got {_type_name(value)}.")
        return value
    if annotation is bool:
        if not isinstance(value, bool):
            raise ConfigError(path, f"expected boolean, got {_type_name(value)}.")
        return value
    if annotation is int:
        if isinstance(value, bool) or not isinstance(value, int):
            raise ConfigError(path, f"expected integer, got {_type_name(value)}.")
        return value
    if annotation is float:
        if isinstance(value, bool) or not isinstance(value, (float, int)):
            raise ConfigError(path, f"expected number, got {_type_name(value)}.")
        return float(value)
    raise ConfigError(
        path,
        f"unsupported annotation {_format_annotation(annotation)}. "
        "Expected dataclass, scalar, list, tuple, or union.",
    )


def _materialize_tuple(annotation: Any, value: Any, path: str) -> tuple[Any, ...]:
    args = get_args(annotation)
    if not isinstance(value, list):
        raise ConfigError(path, f"expected tuple-shaped list, got {_type_name(value)}.")
    if len(args) == 2 and args[1] is Ellipsis:
        return tuple(
            _materialize_value(args[0], item, _index_path(path, index))
            for index, item in enumerate(value)
        )
    if len(value) != len(args):
        raise ConfigError(
            path,
            f"expected {len(args)} tuple items, got {len(value)}.",
        )
    return tuple(
        _materialize_value(item_type, item, _index_path(path, index))
        for index, (item_type, item) in enumerate(zip(args, value))
    )


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


def _nested_dataclass_type(annotation: Any) -> type[Any] | None:
    if _is_dataclass_type(annotation):
        return annotation
    origin = get_origin(annotation)
    args = get_args(annotation)
    if _is_union(origin):
        non_none = [arg for arg in args if arg is not _NONE_TYPE]
        if len(non_none) == 1 and _is_dataclass_type(non_none[0]):
            return non_none[0]
    return None


def _expected_keys(config_type: type[Any]) -> list[str]:
    result: list[str] = []
    for field_ in _dataclass_fields(config_type):
        result.append(field_.name)
        result.extend(get_config_meta(field_).aliases)
    return result


def _describe_type(annotation: Any) -> str:
    origin = get_origin(annotation)
    args = get_args(annotation)
    if annotation is Any:
        return "any value"
    if annotation is str:
        return "string"
    if annotation is bool:
        return "boolean"
    if annotation is int:
        return "integer"
    if annotation is float:
        return "number"
    if _is_dataclass_type(annotation):
        return "mapping"
    if origin is list and len(args) == 1:
        return f"list[{_describe_type(args[0])}]"
    if origin is tuple:
        if len(args) == 2 and args[1] is Ellipsis:
            return f"tuple[{_describe_type(args[0])}, ...]"
        return "tuple[" + ", ".join(_describe_type(arg) for arg in args) + "]"
    if _is_union(origin):
        return " or ".join(
            "null" if arg is _NONE_TYPE else _describe_type(arg) for arg in args
        )
    return _format_annotation(annotation)


def _format_annotation(annotation: Any) -> str:
    return str(annotation).replace("typing.", "")


def _is_union(origin: Any) -> bool:
    return origin is Union or origin is types.UnionType


def _is_dataclass_type(value: Any) -> TypeGuard[type[Any]]:
    return isinstance(value, type) and is_dataclass(value)


def _dataclass_fields(config_type: type[Any]) -> tuple[Field[Any], ...]:
    return fields(cast(Any, config_type))


def _join_path(path: str, field_name: str) -> str:
    return f"{path}.{field_name}" if path else field_name


def _index_path(path: str, index: int) -> str:
    return f"{path}[{index}]"


def _type_name(value: Any) -> str:
    return type(value).__name__
