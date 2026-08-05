from __future__ import annotations

import hashlib
import json
import re
import subprocess
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import IO, Iterable, Mapping
from zipfile import BadZipFile, ZipFile


@dataclass(frozen=True, slots=True)
class PublicationPreflightResult:
    head_commit: str
    origin_url: str


def write_checksums_file(artifacts: Iterable[Path], output_path: Path) -> None:
    artifact_paths = tuple(artifacts)
    lines = [f"{_sha256_file(path)}  {path.name}" for path in artifact_paths]
    output_path.write_text("\n".join(lines) + "\n", encoding="ascii")


def write_release_notes(
    project_root: Path,
    *,
    app_name: str,
    version: str,
    artifacts: Iterable[Path],
    output_path: Path,
) -> None:
    head = _git(project_root, "rev-parse", "HEAD", check=False).stdout.strip()
    previous_tag = _git(
        project_root,
        "describe",
        "--tags",
        "--abbrev=0",
        "HEAD^",
        check=False,
    ).stdout.strip()
    revision_range = f"{previous_tag}..HEAD" if previous_tag else "HEAD"
    log_result = _git(
        project_root,
        "log",
        "--format=%s",
        revision_range,
        check=False,
    )
    subjects = [line.strip() for line in log_result.stdout.splitlines() if line.strip()]

    lines = [f"# {app_name} {version}", ""]
    if head:
        lines.extend([f"Built from commit `{head}`.", ""])
    lines.extend(["## Changes", ""])
    if subjects:
        lines.extend(f"- {subject}" for subject in subjects)
    else:
        lines.append("- Local release build.")
    lines.extend(["", "## Assets", ""])
    lines.extend(
        f"- `{path.name}` (`sha256:{_sha256_file(path)}`)" for path in artifacts
    )
    output_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def run_publication_preflight(
    project_root: Path,
    *,
    version: str,
    app_name: str,
    dist_dir: Path,
    artifacts: Iterable[Path],
    release_outputs: Iterable[Path] | None = None,
    payload_archive: Path,
    installer_archive: Path,
    manifest_path: Path,
    checksums_path: Path,
    release_notes_path: Path,
) -> PublicationPreflightResult:
    root = project_root.resolve()
    resolved_dist = dist_dir.resolve()
    artifact_paths = tuple(path.resolve() for path in artifacts)
    release_output_paths = tuple(
        path.resolve()
        for path in (release_outputs if release_outputs is not None else artifact_paths)
    )

    _validate_git_root(root)
    _validate_version_ref(root, version)
    _validate_clean_worktree(root, resolved_dist)
    head_commit = _git(root, "rev-parse", "HEAD").stdout.strip()
    origin_url = _git(root, "remote", "get-url", "origin").stdout.strip()
    if not origin_url:
        raise RuntimeError("Release preflight failed: git remote 'origin' has no URL.")
    _validate_local_tag(root, version, head_commit)
    _validate_app_builder_package_version(root, version)
    _validate_artifacts(
        root,
        resolved_dist,
        artifact_paths,
        release_outputs=release_output_paths,
        payload_archive=payload_archive.resolve(),
        installer_archive=installer_archive.resolve(),
        manifest_path=manifest_path.resolve(),
        checksums_path=checksums_path.resolve(),
        release_notes_path=release_notes_path.resolve(),
        app_name=app_name,
        version=version,
    )
    return PublicationPreflightResult(head_commit=head_commit, origin_url=origin_url)


def _validate_git_root(project_root: Path) -> None:
    result = _git(project_root, "rev-parse", "--show-toplevel")
    discovered = Path(result.stdout.strip()).resolve()
    if discovered != project_root:
        raise RuntimeError(
            "Release preflight failed: project root does not match the Git worktree "
            f"root ({discovered})."
        )


def _validate_version_ref(project_root: Path, version: str) -> None:
    if (
        not version
        or version.strip() != version
        or any(character.isspace() for character in version)
    ):
        raise RuntimeError(
            f"Release preflight failed: invalid release version {version!r}."
        )
    result = _git(
        project_root,
        "check-ref-format",
        f"refs/tags/{version}",
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"Release preflight failed: {version!r} is not a valid Git tag name."
        )


def _validate_clean_worktree(project_root: Path, dist_dir: Path) -> None:
    try:
        dist_relative = dist_dir.relative_to(project_root).as_posix().rstrip("/")
    except ValueError as error:
        raise RuntimeError(
            f"Release preflight failed: dist directory is outside the project: {dist_dir}"
        ) from error
    result = _git(
        project_root,
        "status",
        "--porcelain=v1",
        "-z",
        "--untracked-files=all",
    )
    dirty: list[str] = []
    records = [record for record in result.stdout.split("\0") if record]
    for record in records:
        status = record[:2]
        path = record[3:].replace("\\", "/")
        if status == "??" and (
            path == dist_relative or path.startswith(dist_relative + "/")
        ):
            continue
        dirty.append(f"{status} {path}")
    if dirty:
        preview = ", ".join(dirty[:8])
        suffix = " ..." if len(dirty) > 8 else ""
        raise RuntimeError(
            "Release preflight failed: Git worktree is not clean outside the dist "
            f"directory: {preview}{suffix}"
        )


def _validate_local_tag(project_root: Path, version: str, head_commit: str) -> None:
    exists = _git(
        project_root,
        "show-ref",
        "--verify",
        "--quiet",
        f"refs/tags/{version}",
        check=False,
    )
    if exists.returncode != 0:
        return
    tag_commit = _git(project_root, "rev-list", "-n", "1", version).stdout.strip()
    if tag_commit != head_commit:
        raise RuntimeError(
            f"Release preflight failed: local tag {version!r} points to {tag_commit}, "
            f"not HEAD {head_commit}."
        )


def _validate_app_builder_package_version(project_root: Path, version: str) -> None:
    pyproject_path = project_root / "pyproject.toml"
    if not pyproject_path.is_file():
        return
    with pyproject_path.open("rb") as pyproject_file:
        payload = tomllib.load(pyproject_file)
    project = payload.get("project")
    if not isinstance(project, Mapping):
        return
    name = project.get("name")
    package_version = project.get("version")
    if _identity_key(name) != "appbuilder":
        return
    if package_version != version:
        raise RuntimeError(
            "Release preflight failed: app-builder package version "
            f"{package_version!r} does not match release version {version!r}."
        )


def _validate_artifacts(
    project_root: Path,
    dist_dir: Path,
    artifacts: tuple[Path, ...],
    *,
    release_outputs: tuple[Path, ...],
    payload_archive: Path,
    installer_archive: Path,
    manifest_path: Path,
    checksums_path: Path,
    release_notes_path: Path,
    app_name: str,
    version: str,
) -> None:
    if len(set(artifacts)) != len(artifacts):
        raise RuntimeError("Release preflight failed: artifact paths are not unique.")
    if len(set(release_outputs)) != len(release_outputs):
        raise RuntimeError(
            "Release preflight failed: release output paths are not unique."
        )
    if not set(artifacts).issubset(release_outputs):
        raise RuntimeError(
            "Release preflight failed: publication artifacts are not a subset of "
            "the resolved release outputs."
        )
    for artifact in (*release_outputs, release_notes_path):
        try:
            artifact.relative_to(dist_dir)
        except ValueError as error:
            raise RuntimeError(
                f"Release preflight failed: artifact is outside dist: {artifact}"
            ) from error
        if not artifact.is_file() or artifact.stat().st_size == 0:
            raise RuntimeError(
                f"Release preflight failed: artifact is missing or empty: {artifact}"
            )

    required_outputs = {
        payload_archive,
        installer_archive,
        manifest_path,
        checksums_path,
    }
    if not required_outputs.issubset(release_outputs):
        raise RuntimeError(
            "Release preflight failed: release outputs are missing the payload, "
            "installer, manifest, or checksums contract."
        )

    manifest = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
    if manifest.get("name") != app_name or manifest.get("version") != version:
        raise RuntimeError(
            "Release preflight failed: installer manifest identity does not match "
            f"{app_name!r} {version!r}."
        )
    if manifest.get("payload_archive") != payload_archive.name:
        raise RuntimeError(
            "Release preflight failed: installer manifest names a different payload."
        )

    try:
        with ZipFile(installer_archive) as installer_zip:
            names = set(installer_zip.namelist())
            embedded_payload_sha256 = (
                _sha256_stream(installer_zip.open(payload_archive.name))
                if payload_archive.name in names
                else None
            )
            embedded_manifest = (
                _read_embedded_manifest(
                    installer_zip.read("bin/install.ps1").decode("utf-8")
                )
                if "bin/install.ps1" in names
                else None
            )
    except BadZipFile as error:
        raise RuntimeError(
            f"Release preflight failed: installer outer ZIP is unreadable: {installer_archive}"
        ) from error
    required_outer_files = {
        payload_archive.name,
        "install.cmd",
        "bin/install.ps1",
    }
    missing = sorted(required_outer_files - names)
    if missing:
        raise RuntimeError(
            "Release preflight failed: installer is missing required outer files: "
            + ", ".join(missing)
        )
    if embedded_payload_sha256 != _sha256_file(payload_archive):
        raise RuntimeError(
            "Release preflight failed: installer embedded payload differs from "
            f"standalone payload {payload_archive.name}."
        )
    if embedded_manifest != manifest:
        raise RuntimeError(
            "Release preflight failed: installer embedded manifest differs from "
            f"published manifest {manifest_path.name}."
        )

    recorded = _read_checksums(checksums_path)
    expected_checksum_names = {
        artifact.name for artifact in release_outputs if artifact != checksums_path
    }
    if set(recorded) != expected_checksum_names:
        raise RuntimeError(
            "Release preflight failed: checksum inventory differs from the "
            "payload, installer, and manifest contract."
        )
    for artifact in release_outputs:
        if artifact == checksums_path:
            continue
        actual = _sha256_file(artifact)
        if recorded.get(artifact.name) != actual:
            raise RuntimeError(
                f"Release preflight failed: checksum mismatch for {artifact.name}."
            )

    expected_names = {path.name for path in (*release_outputs, release_notes_path)}
    identity_prefix = installer_archive.name.removesuffix("-installer.exe")
    generated_names = {
        f"{identity_prefix}.zip",
        f"{identity_prefix}.7z",
        f"{identity_prefix}-installer.exe",
        f"{identity_prefix}-manifest.json",
        f"{identity_prefix}-SHA256SUMS.txt",
        f"{identity_prefix}-release-notes.md",
    }
    unexpected = sorted(
        path.name
        for path in dist_dir.iterdir()
        if path.is_file()
        and path.name in generated_names
        and path.name not in expected_names
    )
    if unexpected:
        raise RuntimeError(
            "Release preflight failed: unexpected same-version files in dist: "
            + ", ".join(unexpected)
        )


def _read_checksums(path: Path) -> dict[str, str]:
    checksums: dict[str, str] = {}
    for line in path.read_text(encoding="ascii").splitlines():
        if not line.strip():
            continue
        parts = line.split("  ", 1)
        if (
            len(parts) != 2
            or len(parts[0]) != 64
            or any(character not in "0123456789abcdefABCDEF" for character in parts[0])
            or not parts[1]
            or parts[1] in checksums
        ):
            raise RuntimeError(
                f"Release preflight failed: malformed checksum line in {path}: {line!r}"
            )
        checksums[parts[1]] = parts[0].lower()
    return checksums


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as input_file:
        for chunk in iter(lambda: input_file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _sha256_stream(stream: IO[bytes]) -> str:
    digest = hashlib.sha256()
    with stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _read_embedded_manifest(script: str) -> object:
    match = re.search(
        r"\$EmbeddedManifestJson = @'\r?\n(.*?)\r?\n'@",
        script,
        flags=re.DOTALL,
    )
    if match is None:
        raise RuntimeError(
            "Release preflight failed: installer script has no readable embedded manifest."
        )
    try:
        return json.loads(match.group(1))
    except json.JSONDecodeError as error:
        raise RuntimeError(
            "Release preflight failed: installer script embedded manifest is invalid JSON."
        ) from error


def _identity_key(value: object) -> str:
    if not isinstance(value, str):
        return ""
    return "".join(character for character in value.casefold() if character.isalnum())


def _git(
    project_root: Path,
    *args: str,
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        ["git", *args],
        cwd=project_root,
        capture_output=True,
        text=True,
        check=False,
    )
    if check and result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip() or "unknown git error"
        raise RuntimeError(
            f"Release preflight failed while running git {' '.join(args)}: {detail}"
        )
    return result
