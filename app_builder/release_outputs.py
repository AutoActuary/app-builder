from __future__ import annotations

import hashlib
import os
import re
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Iterable

from .schema import ConfigError, ReleaseOutputSpec

BUILTIN_OUTPUT_NAMES = frozenset({"payload", "installer", "manifest", "checksums"})
_OUTPUT_NAME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_.-]*$")
_GLOB_CHARACTERS = frozenset("*?[")


@dataclass(frozen=True, slots=True)
class ReleaseOutput:
    name: str
    path: Path
    size: int
    sha256: str


def validate_output_declarations(
    specs: Iterable[ReleaseOutputSpec], requested_names: Iterable[str] = ()
) -> None:
    """Validate output declarations without touching the filesystem."""

    known_names = {name.casefold(): name for name in BUILTIN_OUTPUT_NAMES}
    for index, spec in enumerate(specs):
        config_path = f"config.outputs[{index}]"
        _validate_output_name(spec.name, config_path)
        name_key = spec.name.casefold()
        if name_key in known_names:
            raise ConfigError(
                f"{config_path}.name",
                f"duplicate or reserved output name {spec.name!r}.",
            )
        known_names[name_key] = spec.name
        _validate_output_pattern(spec.pattern, config_path)
        _validate_match_bounds(spec, config_path)

    seen_requests: set[str] = set()
    for index, requested_name in enumerate(requested_names):
        key = requested_name.casefold()
        config_path = f"config.publications.github.outputs[{index}]"
        if key in seen_requests:
            raise ConfigError(
                config_path,
                f"duplicate output name {requested_name!r}.",
            )
        seen_requests.add(key)
        if key not in known_names:
            available = ", ".join(sorted(known_names.values()))
            raise ConfigError(
                config_path,
                f"unknown output {requested_name!r}. Available outputs: {available}.",
            )


def resolve_configured_outputs(
    dist_dir: Path,
    specs: Iterable[ReleaseOutputSpec],
    *,
    occupied_paths: Iterable[Path],
) -> tuple[tuple[str, Path], ...]:
    resolved_dist = dist_dir.resolve()
    occupied = {_path_key(path.resolve()): path.resolve() for path in occupied_paths}
    seen_names = set(BUILTIN_OUTPUT_NAMES)
    resolved: list[tuple[str, Path]] = []

    for index, spec in enumerate(specs):
        config_path = f"config.outputs[{index}]"
        _validate_output_name(spec.name, config_path)
        name_key = spec.name.casefold()
        if name_key in {name.casefold() for name in seen_names}:
            raise ConfigError(
                f"{config_path}.name",
                f"duplicate or reserved output name {spec.name!r}.",
            )
        seen_names.add(spec.name)
        pattern = _validate_output_pattern(spec.pattern, config_path)
        _validate_match_bounds(spec, config_path)
        matches = sorted(
            (path.resolve() for path in resolved_dist.glob(pattern) if path.is_file()),
            key=lambda path: os.path.normcase(str(path)),
        )
        for match in matches:
            try:
                match.relative_to(resolved_dist)
            except ValueError as error:
                raise ConfigError(
                    f"{config_path}.pattern",
                    f"matched a file outside installer.dist: {match}",
                ) from error
        if len(matches) < spec.min_matches:
            raise ConfigError(
                f"{config_path}.pattern",
                f"matched {len(matches)} files; expected at least {spec.min_matches}: {pattern!r}.",
            )
        if spec.max_matches is not None and len(matches) > spec.max_matches:
            raise ConfigError(
                f"{config_path}.pattern",
                f"matched {len(matches)} files; expected at most {spec.max_matches}: {pattern!r}.",
            )
        for match in matches:
            key = _path_key(match)
            previous = occupied.get(key)
            if previous is not None:
                raise ConfigError(
                    f"{config_path}.pattern",
                    f"output path collides with another release output: {match}",
                )
            occupied[key] = match
            resolved.append((spec.name, match))
    return tuple(resolved)


def prepare_configured_output_locations(
    dist_dir: Path,
    specs: Iterable[ReleaseOutputSpec],
    *,
    protected_paths: Iterable[Path],
) -> tuple[Path, ...]:
    """Remove files that could satisfy named outputs before post_dist runs."""
    resolved_dist = dist_dir.resolve()
    protected = {_path_key(path.resolve()) for path in protected_paths}
    seen_names = set(BUILTIN_OUTPUT_NAMES)
    removed: list[Path] = []

    for index, spec in enumerate(specs):
        config_path = f"config.outputs[{index}]"
        _validate_output_name(spec.name, config_path)
        name_key = spec.name.casefold()
        if name_key in {name.casefold() for name in seen_names}:
            raise ConfigError(
                f"{config_path}.name",
                f"duplicate or reserved output name {spec.name!r}.",
            )
        seen_names.add(spec.name)
        pattern = _validate_output_pattern(spec.pattern, config_path)
        _validate_match_bounds(spec, config_path)
        for path in sorted(
            (candidate.resolve() for candidate in resolved_dist.glob(pattern)),
            key=lambda candidate: os.path.normcase(str(candidate)),
        ):
            try:
                path.relative_to(resolved_dist)
            except ValueError as error:
                raise ConfigError(
                    f"{config_path}.pattern",
                    f"matched a path outside installer.dist: {path}",
                ) from error
            if not path.is_file():
                continue
            if _path_key(path) in protected:
                raise ConfigError(
                    f"{config_path}.pattern",
                    f"matches protected built-in release output: {path.name!r}.",
                )
            path.unlink()
            removed.append(path)
    return tuple(removed)


def select_publication_outputs(
    outputs: Iterable[ReleaseOutput],
    requested_names: Iterable[str],
    *,
    declared_names: Iterable[str] = (),
) -> tuple[ReleaseOutput, ...]:
    grouped: dict[str, list[ReleaseOutput]] = {}
    canonical_names: dict[str, str] = {}
    for output in outputs:
        key = output.name.casefold()
        grouped.setdefault(key, []).append(output)
        canonical_names[key] = output.name
    for declared_name in declared_names:
        key = declared_name.casefold()
        canonical_names.setdefault(key, declared_name)
        grouped.setdefault(key, [])

    selected: list[ReleaseOutput] = []
    seen_requests: set[str] = set()
    for index, requested_name in enumerate(requested_names):
        key = requested_name.casefold()
        if key in seen_requests:
            raise ConfigError(
                f"config.publications.github.outputs[{index}]",
                f"duplicate output name {requested_name!r}.",
            )
        seen_requests.add(key)
        matches = grouped.get(key)
        if matches is None:
            available = ", ".join(sorted(canonical_names.values()))
            raise ConfigError(
                f"config.publications.github.outputs[{index}]",
                f"unknown output {requested_name!r}. Available outputs: {available}.",
            )
        selected.extend(matches)

    filenames: dict[str, Path] = {}
    for output in selected:
        filename_key = output.path.name.casefold()
        previous = filenames.get(filename_key)
        if previous is not None:
            raise ConfigError(
                "config.publications.github.outputs",
                f"GitHub asset filename collision: {previous.name!r} from {previous} and {output.path}.",
            )
        filenames[filename_key] = output.path
    return tuple(selected)


def describe_output(name: str, path: Path) -> ReleaseOutput:
    return ReleaseOutput(
        name=name,
        path=path,
        size=path.stat().st_size,
        sha256=_sha256_file(path),
    )


def _validate_output_name(name: str, config_path: str) -> None:
    if not _OUTPUT_NAME_RE.fullmatch(name):
        raise ConfigError(
            f"{config_path}.name",
            "expected a name beginning with a letter and containing only letters, digits, '.', '_', or '-'.",
        )


def _validate_output_pattern(pattern: str, config_path: str) -> str:
    normalized = pattern.replace("\\", "/")
    path = PurePosixPath(normalized)
    if (
        not normalized
        or normalized.strip() != normalized
        or path.is_absolute()
        or ":" in normalized
        or "**" in normalized
        or any(part in {"", ".", ".."} for part in normalized.split("/"))
        or any(ord(character) < 32 for character in normalized)
    ):
        raise ConfigError(
            f"{config_path}.pattern",
            "must be a safe path or non-recursive glob relative to installer.dist.",
        )
    if any(
        character in part
        for part in normalized.split("/")[:-1]
        for character in _GLOB_CHARACTERS
    ):
        raise ConfigError(
            f"{config_path}.pattern",
            "wildcards are allowed only in the final filename segment.",
        )
    return normalized


def _validate_match_bounds(spec: ReleaseOutputSpec, config_path: str) -> None:
    if spec.min_matches < 0:
        raise ConfigError(f"{config_path}.min_matches", "must be zero or greater.")
    if spec.max_matches is not None and spec.max_matches < spec.min_matches:
        raise ConfigError(
            f"{config_path}.max_matches",
            "must be greater than or equal to min_matches.",
        )


def _path_key(path: Path) -> str:
    return os.path.normcase(str(path)).casefold()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as input_file:
        for chunk in iter(lambda: input_file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
