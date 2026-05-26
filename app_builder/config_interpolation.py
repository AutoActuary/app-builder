from __future__ import annotations

import os
import re
import subprocess
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .project import detect_version
from .schema import ConfigError

_INTERPOLATION_RE = re.compile(r"\$\{([^{}]+)\}")


@dataclass(slots=True)
class InterpolationContext:
    project_root: Path
    raw_root: Mapping[str, Any]
    app_version: str | None = None
    git_values: dict[str, str] = field(default_factory=dict)
    resolved_paths: dict[tuple[str, ...], Any] = field(default_factory=dict)


def interpolate_config(
    value: Mapping[str, Any],
    *,
    project_root: Path,
    app_version: str | None = None,
) -> dict[str, Any]:
    context = InterpolationContext(
        project_root=project_root,
        raw_root=value,
        app_version=app_version,
    )
    resolved = _resolve_node(value, (), (), context)
    if not isinstance(resolved, dict):
        raise ConfigError("config", "expected mapping after interpolation.")
    return resolved


def _resolve_node(
    value: Any,
    path: tuple[str, ...],
    stack: tuple[tuple[str, ...], ...],
    context: InterpolationContext,
) -> Any:
    if isinstance(value, str):
        return _resolve_string(value, path, stack, context)
    if isinstance(value, list):
        return [
            _resolve_node(item, (*path, str(index)), stack, context)
            for index, item in enumerate(value)
        ]
    if isinstance(value, dict):
        return {
            key: _resolve_node(item, (*path, str(key)), stack, context)
            for key, item in value.items()
        }
    return value


def _resolve_string(
    value: str,
    path: tuple[str, ...],
    stack: tuple[tuple[str, ...], ...],
    context: InterpolationContext,
) -> str:
    if path in stack:
        raise ConfigError(
            _format_path(path),
            "circular interpolation reference detected.",
        )

    def replace(match: re.Match[str]) -> str:
        expression = match.group(1).strip()
        return _resolve_expression(expression, path, (*stack, path), context)

    return _INTERPOLATION_RE.sub(replace, value)


def _resolve_expression(
    expression: str,
    current_path: tuple[str, ...],
    stack: tuple[tuple[str, ...], ...],
    context: InterpolationContext,
) -> str:
    if expression.startswith("ENV."):
        return _resolve_env(expression.removeprefix("ENV."), current_path)
    if expression.startswith("GIT."):
        return _resolve_git(expression.removeprefix("GIT."), current_path, context)
    if expression == "APP.VERSION":
        return _resolve_app_version(context)
    if expression.startswith("CONFIG."):
        return _resolve_config_reference(
            expression.removeprefix("CONFIG."),
            current_path,
            stack,
            context,
        )
    raise ConfigError(
        _format_path(current_path),
        f"unknown interpolation variable '{expression}'.",
    )


def _resolve_env(name: str, current_path: tuple[str, ...]) -> str:
    if not name:
        raise ConfigError(_format_path(current_path), "ENV interpolation needs a name.")
    value = os.environ.get(name)
    if value is None:
        lower_name = name.lower()
        for env_name, env_value in os.environ.items():
            if env_name.lower() == lower_name:
                return env_value
        raise ConfigError(
            _format_path(current_path),
            f"environment variable '{name}' is not set.",
        )
    return value


def _resolve_git(
    name: str,
    current_path: tuple[str, ...],
    context: InterpolationContext,
) -> str:
    normalized = name.strip().upper()
    if normalized in context.git_values:
        return context.git_values[normalized]

    if normalized == "DESCRIBE":
        value = detect_version(context.project_root)
    elif normalized == "COMMIT":
        value = _git_output(context.project_root, ["rev-parse", "HEAD"], current_path)
    elif normalized == "SHORT_COMMIT":
        value = _git_output(
            context.project_root, ["rev-parse", "--short", "HEAD"], current_path
        )
    elif normalized == "BRANCH":
        value = _git_output_optional(
            context.project_root, ["symbolic-ref", "--short", "HEAD"]
        )
    elif normalized == "TAG":
        value = _git_output_optional(
            context.project_root, ["describe", "--tags", "--exact-match"]
        )
    elif normalized == "IS_DIRTY":
        output = _git_output(context.project_root, ["status", "--porcelain"], current_path)
        value = "true" if output else "false"
    else:
        raise ConfigError(
            _format_path(current_path),
            f"unknown GIT interpolation variable '{name}'.",
        )

    context.git_values[normalized] = value
    return value


def _resolve_app_version(context: InterpolationContext) -> str:
    if context.app_version is None:
        context.app_version = detect_version(context.project_root)
    return context.app_version


def _resolve_config_reference(
    expression: str,
    current_path: tuple[str, ...],
    stack: tuple[tuple[str, ...], ...],
    context: InterpolationContext,
) -> str:
    target_path = _parse_config_path(expression)
    if not target_path:
        raise ConfigError(
            _format_path(current_path),
            "CONFIG interpolation needs a path.",
        )
    if target_path in context.resolved_paths:
        value = context.resolved_paths[target_path]
    else:
        target_value = _get_config_value(target_path, context)
        value = _resolve_node(target_value, target_path, stack, context)
        context.resolved_paths[target_path] = value
    if not isinstance(value, str):
        raise ConfigError(
            _format_path(current_path),
            f"CONFIG.{expression} resolved to {type(value).__name__}; only string values can be interpolated.",
        )
    return value


def _parse_config_path(expression: str) -> tuple[str, ...]:
    cleaned = expression.strip()
    if cleaned.lower().startswith("config."):
        cleaned = cleaned.split(".", 1)[1]
    return tuple(part for part in cleaned.split(".") if part)


def _get_config_value(
    target_path: tuple[str, ...],
    context: InterpolationContext,
) -> Any:
    value: Any = context.raw_root
    path_so_far: list[str] = []
    for part in target_path:
        path_so_far.append(part)
        if isinstance(value, dict):
            if part not in value:
                raise ConfigError(
                    _format_path(tuple(path_so_far)),
                    "CONFIG interpolation target does not exist.",
                )
            value = value[part]
            continue
        if isinstance(value, list) and part.isdecimal():
            index = int(part)
            if index >= len(value):
                raise ConfigError(
                    _format_path(tuple(path_so_far)),
                    "CONFIG interpolation list index is out of range.",
                )
            value = value[index]
            continue
        raise ConfigError(
            _format_path(tuple(path_so_far)),
            "CONFIG interpolation cannot descend into this value.",
        )
    return value

def _git_output(
    project_root: Path,
    args: list[str],
    current_path: tuple[str, ...],
) -> str:
    completed = subprocess.run(
        ["git", *args],
        cwd=project_root,
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        detail = completed.stderr.strip() or completed.stdout.strip()
        raise ConfigError(
            _format_path(current_path),
            f"git {' '.join(args)} failed while resolving interpolation variable: {detail}",
        )
    return completed.stdout.strip()


def _git_output_optional(project_root: Path, args: list[str]) -> str:
    completed = subprocess.run(
        ["git", *args],
        cwd=project_root,
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        return ""
    return completed.stdout.strip()


def _format_path(path: tuple[str, ...]) -> str:
    if not path:
        return "config"
    return "config." + ".".join(path)
