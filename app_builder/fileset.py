from __future__ import annotations

import os
from pathlib import Path, PurePosixPath


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


def collect_files(project_root: Path, include: list[str], exclude: list[str]) -> list[Path]:
    files: dict[Path, None] = {}
    for path in expand_patterns(project_root, include):
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
    return [Path(path) for path in sorted(files)]


def build_remap_table(
    project_root: Path,
    files: list[Path],
    remap: list[tuple[str, str]],
) -> dict[Path, PurePosixPath]:
    mapping: dict[Path, PurePosixPath] = {}
    remap_by_source = {Path(project_root / src).resolve(): PurePosixPath(dst) for src, dst in remap}
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
        mapping[file_path] = PurePosixPath(file_path.resolve().relative_to(project_root.resolve()).as_posix())
    return mapping
