from __future__ import annotations

import os
import glob
from collections.abc import Mapping, Sequence
from pathlib import Path, PurePosixPath

_WINDOWS_RESERVED_NAMES = {
    "aux",
    "con",
    "nul",
    "prn",
    *(f"com{number}" for number in range(1, 10)),
    *(f"lpt{number}" for number in range(1, 10)),
}


def expand_patterns(project_root: Path, patterns: list[str]) -> list[Path]:
    matches: list[Path] = []
    seen: set[Path] = set()
    for pattern in patterns:
        expanded = os.path.expandvars(pattern)
        for path in project_root.glob(expanded):
            resolved = path.resolve()
            if resolved not in seen and path.exists():
                seen.add(resolved)
                matches.append(path)
    return matches


def _expand_required_pattern(project_root: Path, pattern: str) -> list[Path]:
    expanded = os.path.expandvars(pattern)
    candidate = Path(expanded)
    if candidate.is_absolute() or ".." in candidate.parts:
        raise ValueError(
            f"Payload include pattern must stay inside the project: {pattern!r}"
        )
    try:
        matches = [path for path in project_root.glob(expanded) if path.exists()]
    except (NotImplementedError, ValueError) as error:
        raise ValueError(f"Invalid payload include pattern: {pattern!r}") from error
    if not matches:
        raise FileNotFoundError(f"Payload include pattern matched nothing: {pattern!r}")
    root = project_root.resolve()
    for path in matches:
        try:
            path.resolve().relative_to(root)
        except ValueError as error:
            raise ValueError(
                f"Payload include pattern resolves outside the project: {pattern!r}"
            ) from error
    return matches


def collect_files(
    project_root: Path, include: list[str], exclude: list[str]
) -> list[Path]:
    files: dict[Path, None] = {}
    for pattern in include:
        for path in _expand_required_pattern(project_root, pattern):
            if path.is_dir():
                for child in path.rglob("*"):
                    if child.is_file():
                        files[child.resolve()] = None
            elif path.is_file():
                files[path.resolve()] = None
    for path in expand_patterns(project_root, exclude):
        if path.is_dir():
            prefix = path.resolve()
            for file_path in list(files):
                if prefix in file_path.parents or file_path == prefix:
                    files.pop(file_path, None)
        else:
            files.pop(path.resolve(), None)
    resolved_files = [Path(path) for path in sorted(files)]
    if not resolved_files:
        raise ValueError(
            "Payload file set is empty after applying include and exclude rules."
        )
    return resolved_files


def build_remap_table(
    project_root: Path,
    files: list[Path],
    remap: list[tuple[str, str]],
) -> dict[Path, PurePosixPath]:
    mapping: dict[Path, PurePosixPath] = {}
    root = project_root.resolve()
    file_set = {file_path.resolve() for file_path in files}
    for source, _ in remap:
        source_path = Path(source)
        if (
            source_path.is_absolute()
            or ".." in source_path.parts
            or glob.has_magic(source)
        ):
            raise ValueError(
                f"Payload remap source must be a literal project-relative path: {source!r}"
            )
        resolved_source = (root / source_path).resolve()
        try:
            resolved_source.relative_to(root)
        except ValueError as error:
            raise ValueError(
                f"Payload remap source resolves outside the project: {source!r}"
            ) from error
        if not resolved_source.exists():
            raise FileNotFoundError(f"Payload remap source does not exist: {source!r}")
        if resolved_source.is_dir():
            selected = any(resolved_source in path.parents for path in file_set)
        else:
            selected = resolved_source in file_set
        if not selected:
            raise ValueError(
                f"Payload remap source is not present in the resolved file set: {source!r}"
            )
    remap_by_source = {
        Path(project_root / src).resolve(): validate_archive_path(dst)
        for src, dst in remap
    }
    remap_dir_sources = sorted(
        [(src, dst) for src, dst in remap_by_source.items() if src.is_dir()],
        key=lambda item: len(item[0].parts),
        reverse=True,
    )
    for file_path in files:
        direct = remap_by_source.get(file_path.resolve())
        if direct is not None:
            mapping[file_path] = direct
            continue
        remapped = False
        for source_dir, dest_dir in remap_dir_sources:
            if source_dir in file_path.parents:
                relative = file_path.resolve().relative_to(source_dir)
                mapping[file_path] = dest_dir / PurePosixPath(relative.as_posix())
                remapped = True
                break
        if remapped:
            continue
        mapping[file_path] = PurePosixPath(
            file_path.resolve().relative_to(project_root.resolve()).as_posix()
        )
    validate_remap_table(mapping, reserved_paths=("version.txt",))
    return mapping


def validate_archive_path(value: PurePosixPath | str) -> PurePosixPath:
    raw_value = str(value).replace("\\", "/")
    posix_path = PurePosixPath(raw_value)
    if (
        not raw_value
        or raw_value.strip() != raw_value
        or posix_path.is_absolute()
        or any(ord(character) < 32 for character in raw_value)
    ):
        raise ValueError(f"Unsafe archive path: {value!s}")

    raw_parts = raw_value.split("/")
    if any(part in ("", ".", "..") for part in raw_parts):
        raise ValueError(f"Unsafe archive path: {value!s}")

    for part in raw_parts:
        if any(character in part for character in '<>:"|?*'):
            raise ValueError(f"Unsafe archive path: {value!s}")
        if part.endswith((" ", ".")):
            raise ValueError(f"Unsafe archive path: {value!s}")
        device_name = part.split(".", 1)[0].casefold()
        if device_name in _WINDOWS_RESERVED_NAMES:
            raise ValueError(f"Unsafe archive path: {value!s}")
    return posix_path


def validate_remap_table(
    remap_table: Mapping[Path, PurePosixPath],
    *,
    reserved_paths: Sequence[PurePosixPath | str] = (),
) -> None:
    reserved = {
        _archive_collision_key(validate_archive_path(path)) for path in reserved_paths
    }
    destinations: list[tuple[str, Path, PurePosixPath]] = []
    for source, raw_destination in remap_table.items():
        destination = validate_archive_path(raw_destination)
        key = _archive_collision_key(destination)
        if key in reserved:
            raise ValueError(
                f"Archive destination {destination.as_posix()!r} is reserved by app-builder."
            )
        destinations.append((key, source, destination))

    destinations.sort(key=lambda item: item[0])
    seen: dict[str, tuple[Path, PurePosixPath]] = {}
    for key, source, destination in destinations:
        previous = seen.get(key)
        if previous is not None:
            previous_source, previous_destination = previous
            raise ValueError(
                "Archive destination collision: "
                f"{previous_source} and {source} both map to "
                f"{previous_destination.as_posix()!r}."
            )

        parts = key.split("/")
        for parent_length in range(1, len(parts)):
            parent_key = "/".join(parts[:parent_length])
            parent = seen.get(parent_key)
            if parent is not None:
                raise ValueError(
                    "Archive file/directory collision: "
                    f"{parent[0]} maps to {parent[1].as_posix()!r}, which is a parent "
                    f"of {destination.as_posix()!r}."
                )
        seen[key] = (source, destination)


def _archive_collision_key(path: PurePosixPath) -> str:
    return "/".join(part.casefold() for part in path.parts)
