from __future__ import annotations

import subprocess
import sys
import tomllib
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

MAIN_GROUP = "main"
DEV_GROUP = "dev"
_PIP_INSTALL_CHUNK_SIZE = 40


@dataclass(frozen=True, slots=True)
class LockedPackage:
    name: str
    version: str
    groups: frozenset[str]
    optional: bool
    markers: object | None = None
    source: Mapping[str, Any] | None = None


@dataclass(frozen=True, slots=True)
class PoetryLock:
    packages: tuple[LockedPackage, ...]

    def requirements_for_groups(
        self,
        groups: Iterable[str],
        *,
        project_root: Path,
    ) -> list[str]:
        selected_groups = frozenset(groups)
        return [
            _requirement_for_package(package, selected_groups, project_root)
            for package in self._selected_packages(selected_groups)
        ]

    def index_urls_for_groups(self, groups: Iterable[str]) -> list[str]:
        selected_groups = frozenset(groups)
        urls: set[str] = set()
        for package in self._selected_packages(selected_groups):
            if package.source is None:
                continue
            source_type = package.source.get("type")
            source_url = package.source.get("url")
            if source_type == "legacy" and isinstance(source_url, str):
                urls.add(source_url)
        return sorted(urls)

    def _selected_packages(self, groups: frozenset[str]) -> list[LockedPackage]:
        if not groups:
            return []
        return [
            package
            for package in self.packages
            if not package.optional and package.groups.intersection(groups)
        ]


def ensure_poetry_lock(project_root: Path) -> PoetryLock:
    pyproject_path = project_root / "pyproject.toml"
    if not pyproject_path.exists():
        raise FileNotFoundError(
            f"Could not find {pyproject_path}. Poetry dependencies must be declared in pyproject.toml."
        )

    completed = subprocess.run(
        [sys.executable, "-m", "poetry", "lock", "--no-interaction"],
        cwd=project_root,
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        stderr = completed.stderr.strip()
        detail = f" Poetry said: {stderr}" if stderr else ""
        raise RuntimeError(
            "Poetry failed to lock pyproject.toml. Install Poetry in the same "
            f"Python environment as app-builder and make sure pyproject.toml is valid.{detail}"
        )

    lock_path = project_root / "poetry.lock"
    if not lock_path.exists():
        raise FileNotFoundError(f"Poetry did not create {lock_path}.")
    return load_poetry_lock(lock_path)


def load_poetry_lock(lock_path: Path) -> PoetryLock:
    with lock_path.open("rb") as lock_file:
        payload = tomllib.load(lock_file)
    packages = payload.get("package", [])
    if not isinstance(packages, list):
        raise RuntimeError(f"Unexpected Poetry lock layout in {lock_path}.")
    return PoetryLock(
        packages=tuple(_locked_package_from_mapping(package) for package in packages)
    )


def install_locked_poetry_dependencies(
    *,
    project_root: Path,
    python_executable: Path,
    poetry_lock: PoetryLock,
    groups: Iterable[str],
) -> None:
    selected_groups = frozenset(groups)
    requirements = poetry_lock.requirements_for_groups(
        selected_groups, project_root=project_root
    )
    if not requirements:
        return
    index_urls = poetry_lock.index_urls_for_groups(selected_groups)
    for requirement_chunk in _chunks(requirements, _PIP_INSTALL_CHUNK_SIZE):
        command = [
            str(python_executable),
            "-E",
            "-m",
            "pip",
            "install",
            "--upgrade",
            "--no-deps",
            "--no-warn-script-location",
            "--disable-pip-version-check",
        ]
        for index_url in index_urls:
            command.extend(["--extra-index-url", index_url])
        command.extend(requirement_chunk)
        subprocess.run(command, check=True)


def _locked_package_from_mapping(value: object) -> LockedPackage:
    if not isinstance(value, Mapping):
        raise RuntimeError("Unexpected Poetry lock package entry.")
    name = value.get("name")
    version = value.get("version")
    if not isinstance(name, str) or not isinstance(version, str):
        raise RuntimeError("Poetry lock package entries must have name and version.")
    groups = _package_groups(value.get("groups"))
    optional = value.get("optional", False)
    if not isinstance(optional, bool):
        raise RuntimeError(
            f"Poetry lock package {name!r} has a non-boolean optional flag."
        )
    source = value.get("source")
    if source is not None and not isinstance(source, Mapping):
        raise RuntimeError(f"Poetry lock package {name!r} has an invalid source block.")
    return LockedPackage(
        name=name,
        version=version,
        groups=groups,
        optional=optional,
        markers=value.get("markers"),
        source=source,
    )


def _package_groups(value: object) -> frozenset[str]:
    if value is None:
        return frozenset({MAIN_GROUP})
    if isinstance(value, list) and all(isinstance(item, str) for item in value):
        return frozenset(value)
    raise RuntimeError("Poetry lock package groups must be a list of strings.")


def _requirement_for_package(
    package: LockedPackage,
    selected_groups: frozenset[str],
    project_root: Path,
) -> str:
    requirement = _base_requirement_for_package(package, project_root)
    marker = _marker_for_groups(package.markers, selected_groups)
    if marker is None:
        return requirement
    return f"{requirement}; {marker}"


def _base_requirement_for_package(package: LockedPackage, project_root: Path) -> str:
    if package.source is None:
        return f"{package.name}=={package.version}"

    source_type = package.source.get("type")
    if source_type == "legacy":
        return f"{package.name}=={package.version}"
    if source_type == "git":
        url = _source_string(package, "url")
        reference = package.source.get("resolved_reference") or package.source.get(
            "reference"
        )
        reference_suffix = f"@{reference}" if isinstance(reference, str) else ""
        return f"{package.name} @ git+{url}{reference_suffix}"
    if source_type == "url":
        return f"{package.name} @ {_source_string(package, 'url')}"
    if source_type in {"file", "directory"}:
        source_url = _source_string(package, "url")
        source_path = Path(source_url)
        if not source_path.is_absolute():
            source_path = project_root / source_path
        return f"{package.name} @ {source_path.resolve().as_uri()}"

    raise RuntimeError(
        f"Poetry lock package {package.name!r} uses unsupported source type {source_type!r}."
    )


def _source_string(package: LockedPackage, key: str) -> str:
    assert package.source is not None
    value = package.source.get(key)
    if not isinstance(value, str):
        raise RuntimeError(
            f"Poetry lock package {package.name!r} is missing source {key!r}."
        )
    return value


def _marker_for_groups(
    markers: object | None,
    selected_groups: frozenset[str],
) -> str | None:
    if markers is None:
        return None
    if isinstance(markers, str):
        return markers or None
    if isinstance(markers, Mapping):
        selected_markers = [
            marker
            for group, marker in markers.items()
            if group in selected_groups and isinstance(marker, str) and marker
        ]
        if not selected_markers:
            return None
        return " or ".join(f"({marker})" for marker in selected_markers)
    raise RuntimeError("Poetry lock package markers must be a string or mapping.")


def _chunks(values: Sequence[str], size: int) -> Iterable[list[str]]:
    for index in range(0, len(values), size):
        yield list(values[index : index + size])
