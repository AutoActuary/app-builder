from __future__ import annotations

import hashlib
import re
import subprocess
import sys
import tempfile
import tomllib
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app_builder_meta.environment import get_environment

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
    files: tuple[tuple[str, str], ...] = ()


@dataclass(frozen=True, slots=True)
class PoetryLock:
    packages: tuple[LockedPackage, ...]
    path: Path | None = None
    sha256: str | None = None
    content_hash: str | None = None

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

    lock_path = project_root / "poetry.lock"
    if not lock_path.exists():
        raise FileNotFoundError(
            f"Could not find {lock_path}. Normal builds never create or update the lock; run 'app-builder lock' explicitly."
        )

    _run_poetry_lock_command(project_root, ["check", "--lock"], action="verify")
    return load_poetry_lock(lock_path)


def refresh_poetry_lock(project_root: Path) -> PoetryLock:
    pyproject_path = project_root / "pyproject.toml"
    if not pyproject_path.exists():
        raise FileNotFoundError(
            f"Could not find {pyproject_path}. Poetry dependencies must be declared in pyproject.toml."
        )
    _run_poetry_lock_command(
        project_root, ["lock", "--no-interaction"], action="refresh"
    )
    lock_path = project_root / "poetry.lock"
    if not lock_path.exists():
        raise FileNotFoundError(f"Poetry did not create {lock_path}.")
    return load_poetry_lock(lock_path)


def _run_poetry_lock_command(
    project_root: Path, args: list[str], *, action: str
) -> None:
    env = get_environment().subprocess_environment()
    env["POETRY_VIRTUALENVS_CREATE"] = "false"
    env["POETRY_NO_INTERACTION"] = "1"
    completed = subprocess.run(
        [sys.executable, "-m", "poetry", *args],
        cwd=project_root,
        env=env,
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        stderr = completed.stderr.strip()
        detail = f" Poetry said: {stderr}" if stderr else ""
        raise RuntimeError(
            f"Poetry failed to {action} poetry.lock. Install Poetry in the same "
            f"Python environment as app-builder and make sure pyproject.toml is valid.{detail}"
        )


def load_poetry_lock(lock_path: Path) -> PoetryLock:
    with lock_path.open("rb") as lock_file:
        payload = tomllib.load(lock_file)
    packages = payload.get("package", [])
    if not isinstance(packages, list):
        raise RuntimeError(f"Unexpected Poetry lock layout in {lock_path}.")
    metadata = payload.get("metadata", {})
    content_hash = (
        metadata.get("content-hash") if isinstance(metadata, Mapping) else None
    )
    return PoetryLock(
        packages=tuple(_locked_package_from_mapping(package) for package in packages),
        path=lock_path.resolve(),
        sha256=_sha256_file(lock_path),
        content_hash=content_hash if isinstance(content_hash, str) else None,
    )


def install_locked_poetry_dependencies(
    *,
    project_root: Path,
    python_executable: Path,
    poetry_lock: PoetryLock,
    groups: Iterable[str],
) -> None:
    selected_groups = frozenset(groups)
    selected_packages = poetry_lock._selected_packages(selected_groups)
    if not selected_packages:
        return
    _reject_mutable_path_dependencies(selected_packages)
    index_urls = poetry_lock.index_urls_for_groups(selected_groups)
    hashed_lines: list[str] = []
    direct_requirements: list[str] = []
    for package in selected_packages:
        requirement = _requirement_for_package(package, selected_groups, project_root)
        if package.source is None or package.source.get("type") in {"legacy", "url"}:
            hashes = sorted(
                digest for _, digest in package.files if digest.startswith("sha256:")
            )
            if not hashes:
                raise RuntimeError(
                    f"Poetry lock package {package.name!r} has no SHA-256 artifact hashes. "
                    "Run 'app-builder lock' with a current Poetry version."
                )
            hashed_lines.append(
                requirement
                + " \\\n    "
                + " \\\n    ".join(f"--hash={digest}" for digest in hashes)
            )
        else:
            direct_requirements.append(requirement)

    if hashed_lines:
        subprocess_env = get_environment().subprocess_environment()
        with tempfile.TemporaryDirectory() as temp_dir_str:
            requirements_path = Path(temp_dir_str) / "locked-requirements.txt"
            requirements_path.write_text(
                "\n".join(hashed_lines) + "\n", encoding="utf-8"
            )
            command = _pip_install_command(python_executable, index_urls)
            command.extend(
                ["--require-hashes", "--requirement", str(requirements_path)]
            )
            subprocess.run(command, env=subprocess_env, check=True)

    subprocess_env = get_environment().subprocess_environment()
    for requirement_chunk in _chunks(direct_requirements, _PIP_INSTALL_CHUNK_SIZE):
        command = _pip_install_command(python_executable, index_urls)
        command.extend(requirement_chunk)
        subprocess.run(command, env=subprocess_env, check=True)


def _pip_install_command(
    python_executable: Path, index_urls: Iterable[str]
) -> list[str]:
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
        "--quiet",
        "--progress-bar",
        "off",
    ]
    for index_url in index_urls:
        command.extend(["--extra-index-url", index_url])
    return command


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
    files_value = value.get("files", [])
    if not isinstance(files_value, list):
        raise RuntimeError(f"Poetry lock package {name!r} has an invalid files list.")
    locked_files: list[tuple[str, str]] = []
    for file_value in files_value:
        if not isinstance(file_value, Mapping):
            raise RuntimeError(
                f"Poetry lock package {name!r} has an invalid file entry."
            )
        filename = file_value.get("file")
        digest = file_value.get("hash")
        if not isinstance(filename, str) or not isinstance(digest, str):
            raise RuntimeError(
                f"Poetry lock package {name!r} has an invalid file digest."
            )
        locked_files.append((filename, digest))
    return LockedPackage(
        name=name,
        version=version,
        groups=groups,
        optional=optional,
        markers=value.get("markers"),
        source=source,
        files=tuple(locked_files),
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
        reference = package.source.get("resolved_reference")
        if not isinstance(reference, str) or not re.fullmatch(
            r"[0-9a-fA-F]{40}", reference
        ):
            raise RuntimeError(
                f"Poetry lock git package {package.name!r} is not pinned to a full resolved commit."
            )
        return f"{package.name} @ git+{url}@{reference}"
    if source_type == "url":
        return f"{package.name} @ {_source_string(package, 'url')}"
    if source_type in {"file", "directory"}:
        raise RuntimeError(
            f"Poetry dependency {package.name!r} uses mutable {source_type!r} "
            "source. Release dependency inputs must be reproducible; publish the "
            "dependency to an index with hashes or use a Git dependency whose "
            "poetry.lock entry contains a full resolved commit."
        )

    raise RuntimeError(
        f"Poetry lock package {package.name!r} uses unsupported source type {source_type!r}."
    )


def _reject_mutable_path_dependencies(packages: Iterable[LockedPackage]) -> None:
    for package in packages:
        source_type = package.source.get("type") if package.source is not None else None
        if source_type in {"file", "directory"}:
            raise RuntimeError(
                f"Poetry dependency {package.name!r} uses mutable {source_type!r} "
                "source. Release dependency inputs must be reproducible; publish "
                "the dependency to an index with hashes or use a Git dependency "
                "whose poetry.lock entry contains a full resolved commit."
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


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as input_file:
        for chunk in iter(lambda: input_file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
