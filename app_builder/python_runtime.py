from __future__ import annotations

import ast
import base64
import hashlib
import json
import os
import platform
import re
import shutil
import subprocess
import tempfile
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from zipfile import ZipFile

from .config import load_project_config
from .poetry_dependencies import (
    DEV_GROUP,
    MAIN_GROUP,
    PoetryLock,
    ensure_poetry_lock,
    install_locked_poetry_dependencies,
)
from .schema import PythonBundledOptions, PythonVenvOptions

NUGET_PYTHON_PACKAGE_ID = "python"
NUGET_FLAT_CONTAINER_BASE_URL = "https://api.nuget.org/v3-flatcontainer"
NUGET_PYTHON_INDEX_URL = (
    f"{NUGET_FLAT_CONTAINER_BASE_URL}/{NUGET_PYTHON_PACKAGE_ID}/index.json"
)
NUGET_REGISTRATION_BASE_URL = "https://api.nuget.org/v3/registration5-semver1"
_VERSION_PATTERN_RE = re.compile(r"^\d+(?:\.\d+)*(?:[-+][0-9A-Za-z_.-]+)?$")
_NUGET_SOURCE_MARKER = ".app-builder-python-source.json"
_NUGET_PACKAGE_PAYLOAD_ROOT = "tools"
EXE_WRAP_VERSION = "v2.1.0"
_EXE_WRAP_RELEASE_BASE_URL = (
    f"https://github.com/AutoActuary/ExeWrap/releases/download/{EXE_WRAP_VERSION}"
)
_EXE_WRAP_DIGESTS = {
    "windows-arm64": "sha256:1e813291868052c8b7e65bebf127d62a4896ffbc506bb158b8be9c8c24035bc6",
    "windows-x64": "sha256:42c64c90d6620d4942b88e56b615679a8667eaa64902444aa7b21769998936cb",
    "windows-x86": "sha256:757d3260f648262fb2ab0198d1b57de18382c2e0ada10a60c819b58af8863905",
}
_EXE_WRAP_CONFIG_START_MARKER = b"8c0e8d4c-32af-4fd8-9c68-6a0f97efeb6a"
_EXE_WRAP_CONSOLE_LAUNCHER = "ExeWrap-console.exe"
_EXE_WRAP_WINDOWED_LAUNCHER = "ExeWrap-windowed.exe"
_EXE_WRAP_SOURCE_MARKER = ".app-builder-exewrap-source.json"


class PythonVersionNotFoundError(RuntimeError):
    """Raised when NuGet does not offer a requested Python version."""


def python_executable(venv_root: Path) -> Path:
    scripts_dir = "Scripts" if os.name == "nt" else "bin"
    exe_name = "python.exe" if os.name == "nt" else "python"
    return venv_root / scripts_dir / exe_name


def bundled_python_executable(python_root: Path) -> Path:
    return python_root / "python" / "python.exe"


def _python_executable(venv_root: Path) -> Path:
    return python_executable(venv_root)


def _bundled_python_executable(python_root: Path) -> Path:
    return bundled_python_executable(python_root)


def _self_contained_venv_launcher_executable(venv_root: Path) -> Path:
    return venv_root / "Scripts" / "python.exe"


def _self_contained_venv_windowed_launcher_executable(venv_root: Path) -> Path:
    return venv_root / "Scripts" / "pythonw.exe"


def _ensure_pip(python_executable: Path) -> None:
    subprocess.run(
        [
            str(python_executable),
            "-E",
            "-m",
            "ensurepip",
            "--upgrade",
            "--default-pip",
        ],
        check=True,
    )


def _matches_version_pattern(pattern: str | None, version: str) -> bool:
    cleaned = _normalized_version_pattern(pattern)
    if cleaned is None:
        return True
    return version == cleaned or version.startswith(f"{cleaned}.")


def _normalized_version_pattern(pattern: str | None) -> str | None:
    if pattern is None:
        return None
    cleaned = pattern.strip()
    if cleaned in ("", "*"):
        return None
    if cleaned.endswith(".*"):
        cleaned = cleaned[:-2]
    return cleaned


def _is_prerelease_version(version: str) -> bool:
    return "-" in version


def _version_release_parts(version: str) -> tuple[int, ...] | None:
    release = version.split("+", 1)[0].split("-", 1)[0]
    parts = release.split(".")
    if not parts or not all(part.isdecimal() for part in parts):
        return None
    return tuple(int(part) for part in parts)


def _padded_version_parts(version: str) -> tuple[int, int, int, int]:
    parts = _version_release_parts(version) or ()
    padded = (*parts, 0, 0, 0, 0)
    return (padded[0], padded[1], padded[2], padded[3])


def _version_sort_key(version: str) -> tuple[tuple[int, int, int, int], int, str]:
    stable = 0 if _is_prerelease_version(version) else 1
    return (_padded_version_parts(version), stable, version)


def _latest_versions(versions: Sequence[str]) -> list[str]:
    return sorted(versions, key=_version_sort_key, reverse=True)


def _requested_version_parts(pattern: str | None) -> tuple[int, ...]:
    cleaned = _normalized_version_pattern(pattern)
    if cleaned is None:
        return ()
    release = cleaned.split("+", 1)[0].split("-", 1)[0]
    parts: list[int] = []
    for part in release.split("."):
        if not part.isdecimal():
            break
        parts.append(int(part))
    return tuple(parts)


def _closest_versions(
    versions: Sequence[str],
    requested: tuple[int, ...],
    *,
    index: int,
    limit: int,
) -> list[str]:
    def score(version: str) -> tuple[int, tuple[int, int, int, int], int]:
        parts = _padded_version_parts(version)
        newest_first = (-parts[0], -parts[1], -parts[2], -parts[3])
        return (
            abs(parts[index] - requested[index]),
            newest_first,
            1 if _is_prerelease_version(version) else 0,
        )

    return sorted(versions, key=score)[:limit]


def _suggest_nuget_python_versions(
    versions: Sequence[str],
    python_version: str | None,
    *,
    limit: int = 5,
) -> list[str]:
    stable_versions = [
        version for version in versions if not _is_prerelease_version(version)
    ]
    suggestion_pool = stable_versions or list(versions)
    requested = _requested_version_parts(python_version)

    if len(requested) >= 2:
        same_minor = [
            version
            for version in suggestion_pool
            if (_version_release_parts(version) or ())[:2] == requested[:2]
        ]
        if same_minor:
            if len(requested) >= 3:
                return _closest_versions(
                    same_minor,
                    requested,
                    index=2,
                    limit=limit,
                )
            return _latest_versions(same_minor)[:limit]

    if requested:
        same_major = [
            version
            for version in suggestion_pool
            if (_version_release_parts(version) or ())[:1] == requested[:1]
        ]
        if same_major:
            if len(requested) >= 2:
                return _closest_versions(
                    same_major,
                    requested,
                    index=1,
                    limit=limit,
                )
            return _latest_versions(same_major)[:limit]

    return _latest_versions(suggestion_pool)[:limit]


def _load_nuget_python_versions() -> list[str]:
    request = urllib.request.Request(
        NUGET_PYTHON_INDEX_URL,
        headers={
            "Accept": "application/json",
            "User-Agent": "app-builder",
        },
    )
    try:
        with urllib.request.urlopen(request) as response:
            payload: Any = json.loads(response.read().decode("utf-8"))
    except urllib.error.URLError as error:
        raise RuntimeError(
            f"Could not query NuGet Python versions from {NUGET_PYTHON_INDEX_URL}: {error}."
        ) from error

    if not isinstance(payload, dict):
        raise RuntimeError("Unexpected NuGet Python version response: expected object.")
    versions = payload.get("versions")
    if not isinstance(versions, list) or not all(
        isinstance(version, str) for version in versions
    ):
        raise RuntimeError(
            "Unexpected NuGet Python version response: expected a string version list."
        )
    return versions


def _select_nuget_python_version(
    versions: Sequence[str],
    python_version: str | None,
) -> str:
    valid_versions = [
        version for version in versions if _VERSION_PATTERN_RE.match(version)
    ]
    matches = [
        version
        for version in valid_versions
        if _matches_version_pattern(python_version, version)
    ]
    stable_matches = [
        version for version in matches if not _is_prerelease_version(version)
    ]
    if stable_matches:
        matches = stable_matches
    if matches:
        return _latest_versions(matches)[0]

    suggestions = _suggest_nuget_python_versions(valid_versions, python_version)
    suggestion_text = ""
    if suggestions:
        suggestion_text = f" Closest available versions: {', '.join(suggestions)}."
    requested = (
        "the latest available version"
        if _normalized_version_pattern(python_version) is None
        else f"a version matching {python_version!r}"
    )
    raise PythonVersionNotFoundError(
        f"NuGet package '{NUGET_PYTHON_PACKAGE_ID}' does not provide {requested}."
        f"{suggestion_text}"
    )


def _nuget_python_download_url(version: str) -> str:
    return (
        f"{NUGET_FLAT_CONTAINER_BASE_URL}/{NUGET_PYTHON_PACKAGE_ID}/{version}/"
        f"{NUGET_PYTHON_PACKAGE_ID}.{version}.nupkg"
    )


@dataclass(frozen=True, slots=True)
class NuGetPythonPackage:
    version: str
    download_url: str
    digest: str | None = None


@dataclass(frozen=True, slots=True)
class ExeWrapPackage:
    asset_name: str
    download_url: str
    digest: str | None


def _resolve_nuget_python_package(python_version: str | None) -> NuGetPythonPackage:
    versions = _load_nuget_python_versions()
    selected_version = _select_nuget_python_version(versions, python_version)
    return NuGetPythonPackage(
        version=selected_version,
        download_url=_nuget_python_download_url(selected_version),
        digest=_load_nuget_python_digest(selected_version),
    )


def _load_nuget_python_digest(version: str) -> str:
    registration_url = (
        f"{NUGET_REGISTRATION_BASE_URL}/{NUGET_PYTHON_PACKAGE_ID}/{version}.json"
    )
    registration = _load_nuget_json(registration_url)
    catalog_url = registration.get("catalogEntry")
    if not isinstance(catalog_url, str) or not catalog_url.startswith("https://"):
        raise RuntimeError(
            f"NuGet registration metadata did not provide a catalog entry for Python {version}."
        )
    catalog = _load_nuget_json(catalog_url)
    algorithm = catalog.get("packageHashAlgorithm")
    encoded = catalog.get("packageHash")
    if algorithm != "SHA512" or not isinstance(encoded, str):
        raise RuntimeError(
            f"NuGet catalog metadata did not provide a SHA-512 package hash for Python {version}."
        )
    try:
        digest = base64.b64decode(encoded, validate=True)
    except ValueError as error:
        raise RuntimeError(
            f"NuGet returned an invalid SHA-512 package hash for Python {version}."
        ) from error
    if len(digest) != hashlib.sha512().digest_size:
        raise RuntimeError(
            f"NuGet returned an invalid SHA-512 package hash for Python {version}."
        )
    return "sha512:" + digest.hex()


def _load_nuget_json(url: str) -> dict[str, Any]:
    request = urllib.request.Request(
        url,
        headers={"Accept": "application/json", "User-Agent": "app-builder"},
    )
    try:
        with urllib.request.urlopen(request) as response:
            payload: Any = json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise RuntimeError(
            f"Could not read NuGet metadata from {url}: {error}."
        ) from error
    if not isinstance(payload, dict):
        raise RuntimeError(f"Unexpected NuGet metadata response from {url}.")
    return payload


def _download_file(url: str, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    request = urllib.request.Request(url, headers={"User-Agent": "app-builder"})
    try:
        with urllib.request.urlopen(request) as response:
            with destination.open("wb") as output:
                shutil.copyfileobj(response, output)
    except urllib.error.HTTPError as error:
        raise RuntimeError(
            f"Could not download {url}: NuGet returned HTTP {error.code}."
        ) from error
    except urllib.error.URLError as error:
        raise RuntimeError(f"Could not download {url}: {error}.") from error


def _download_cache_path(url: str) -> Path:
    filename = Path(urllib.parse.urlsplit(url).path).name
    if not filename:
        filename = f"{NUGET_PYTHON_PACKAGE_ID}.nupkg"
    return Path(tempfile.gettempdir(), "app-builder-downloads", filename)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as input_file:
        for chunk in iter(lambda: input_file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _expected_digest(digest: str | None) -> tuple[str, str] | None:
    if digest is None:
        return None
    algorithm, separator, expected = digest.partition(":")
    if separator != ":" or algorithm not in {"sha256", "sha512"}:
        raise RuntimeError(f"Unsupported download digest {digest!r}.")
    expected_length = hashlib.new(algorithm).digest_size * 2
    if len(expected) != expected_length or any(
        character not in "0123456789abcdefABCDEF" for character in expected
    ):
        raise RuntimeError(f"Invalid {algorithm} download digest {digest!r}.")
    return algorithm, expected.lower()


def _file_digest(path: Path, algorithm: str) -> str:
    digest = hashlib.new(algorithm)
    with path.open("rb") as input_file:
        for chunk in iter(lambda: input_file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _ensure_downloaded_file(url: str, digest: str | None = None) -> Path:
    path = _download_cache_path(url)
    expected = _expected_digest(digest)
    if (
        path.exists()
        and expected is not None
        and _file_digest(path, expected[0]) != expected[1]
    ):
        path.unlink()
    if not path.exists():
        _download_file(url, path)
    if expected is not None and _file_digest(path, expected[0]) != expected[1]:
        raise RuntimeError(
            f"Downloaded file {path} did not match expected {expected[0]} digest."
        )
    return path


def _exe_wrap_platform_tag() -> str:
    machine = platform.machine().lower()
    if machine in {"amd64", "x86_64"}:
        return "windows-x64"
    if machine in {"arm64", "aarch64"}:
        return "windows-arm64"
    if machine in {"x86", "i386", "i686"}:
        return "windows-x86"
    raise RuntimeError(
        f"ExeWrap does not publish a Windows launcher for architecture {machine!r}."
    )


def _resolve_exe_wrap_package() -> ExeWrapPackage:
    platform_tag = _exe_wrap_platform_tag()
    asset_name = f"ExeWrap-{EXE_WRAP_VERSION}-{platform_tag}.zip"
    return ExeWrapPackage(
        asset_name=asset_name,
        download_url=f"{_EXE_WRAP_RELEASE_BASE_URL}/{asset_name}",
        digest=_EXE_WRAP_DIGESTS[platform_tag],
    )


def _exe_wrap_package_path() -> Path:
    package = _resolve_exe_wrap_package()
    return _ensure_downloaded_file(package.download_url, package.digest)


def _extract_exe_wrap_launcher(
    package_path: Path,
    launcher_name: str,
    destination: Path,
) -> None:
    with ZipFile(package_path) as zip_file:
        for member in zip_file.infolist():
            if Path(member.filename).name != launcher_name or member.is_dir():
                continue
            destination.parent.mkdir(parents=True, exist_ok=True)
            with zip_file.open(member) as source, destination.open("wb") as output:
                shutil.copyfileobj(source, output)
            return
    raise RuntimeError(
        f"ExeWrap package {package_path} did not contain {launcher_name}."
    )


def _exe_wrap_python_config(target_exe_name: str) -> bytes:
    return (
        "{\n"
        '  "command": [\n'
        f'    "@{{exe_dir:parent:join("python"):join("{target_exe_name}")}}",\n'
        "    @{args}\n"
        "  ]\n"
        "}\n"
    ).encode("utf-8")


def _stamp_exe_wrap_launcher(
    base_launcher: Path,
    output_path: Path,
    config: bytes,
) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_bytes(
        base_launcher.read_bytes() + _EXE_WRAP_CONFIG_START_MARKER + config
    )


def _exe_wrap_launcher_matches(output_path: Path, config: bytes) -> bool:
    if not output_path.exists():
        return False
    payload = output_path.read_bytes()
    marker_index = payload.rfind(_EXE_WRAP_CONFIG_START_MARKER)
    if marker_index < 0:
        return False
    embedded_config = payload[marker_index + len(_EXE_WRAP_CONFIG_START_MARKER) :]
    return embedded_config == config


def _install_exe_wrap_python_launchers(
    venv_root: Path,
    *,
    package_path: Path | None = None,
) -> None:
    package: ExeWrapPackage | None = None
    if package_path is None:
        package = _resolve_exe_wrap_package()
        package_path = _ensure_downloaded_file(package.download_url, package.digest)
    with tempfile.TemporaryDirectory() as temp_dir_str:
        temp_dir = Path(temp_dir_str)
        console_launcher = temp_dir / _EXE_WRAP_CONSOLE_LAUNCHER
        windowed_launcher = temp_dir / _EXE_WRAP_WINDOWED_LAUNCHER
        _extract_exe_wrap_launcher(
            package_path, _EXE_WRAP_CONSOLE_LAUNCHER, console_launcher
        )
        _extract_exe_wrap_launcher(
            package_path, _EXE_WRAP_WINDOWED_LAUNCHER, windowed_launcher
        )
        _stamp_exe_wrap_launcher(
            console_launcher,
            _self_contained_venv_launcher_executable(venv_root),
            _exe_wrap_python_config("python.exe"),
        )
        _stamp_exe_wrap_launcher(
            windowed_launcher,
            _self_contained_venv_windowed_launcher_executable(venv_root),
            _exe_wrap_python_config("pythonw.exe"),
        )
    if package is not None:
        (venv_root / _EXE_WRAP_SOURCE_MARKER).write_text(
            json.dumps(
                {
                    "version": EXE_WRAP_VERSION,
                    "asset_name": package.asset_name,
                    "download_url": package.download_url,
                    "digest": package.digest,
                },
                indent=2,
            ),
            encoding="utf-8",
        )


def _source_marker_path(python_root: Path) -> Path:
    return python_root / _NUGET_SOURCE_MARKER


def _write_nuget_source_marker(
    python_root: Path,
    package: NuGetPythonPackage,
) -> None:
    _source_marker_path(python_root).write_text(
        json.dumps(
            {
                "package_id": NUGET_PYTHON_PACKAGE_ID,
                "version": package.version,
                "download_url": package.download_url,
                "digest": package.digest,
            },
            indent=2,
        ),
        encoding="utf-8",
    )


def _nuget_source_marker_matches(
    python_root: Path,
    python_version: str | None,
) -> bool:
    marker_path = _source_marker_path(python_root)
    if not marker_path.exists():
        return False
    try:
        payload: Any = json.loads(marker_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return False
    if not isinstance(payload, dict):
        return False
    package_id = payload.get("package_id")
    version = payload.get("version")
    digest = payload.get("digest")
    return (
        package_id == NUGET_PYTHON_PACKAGE_ID
        and isinstance(version, str)
        and _matches_version_pattern(python_version, version)
        and isinstance(digest, str)
        and _expected_digest(digest) is not None
    )


def _safe_archive_target(root: Path, relative_parts: tuple[str, ...]) -> Path:
    destination = root.joinpath(*relative_parts)
    root_resolved = root.resolve()
    destination_resolved = destination.resolve()
    try:
        destination_resolved.relative_to(root_resolved)
    except ValueError as error:
        raise RuntimeError(
            f"NuGet Python package contains an unsafe archive path: {'/'.join(relative_parts)}."
        ) from error
    return destination


def _extract_nuget_python_payload(package_path: Path, payload_root: Path) -> None:
    extracted_any = False
    with ZipFile(package_path) as zip_file:
        for member in zip_file.infolist():
            parts = Path(member.filename).parts
            if not parts or parts[0].lower() != _NUGET_PACKAGE_PAYLOAD_ROOT:
                continue
            relative_parts = tuple(parts[1:])
            if not relative_parts:
                continue
            extracted_any = True
            target = _safe_archive_target(payload_root, relative_parts)
            if member.is_dir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            with zip_file.open(member) as source, target.open("wb") as destination:
                shutil.copyfileobj(source, destination)

    if not extracted_any:
        raise RuntimeError("NuGet Python package did not contain a Python payload.")


def _extract_nuget_python_package(package_path: Path, python_root: Path) -> None:
    if python_root.exists():
        shutil.rmtree(python_root)
    with tempfile.TemporaryDirectory() as temp_dir_str:
        extracted_python = Path(temp_dir_str, "python-payload")
        _extract_nuget_python_payload(package_path, extracted_python)
        if not (extracted_python / "python.exe").exists():
            raise RuntimeError("NuGet Python package did not contain python.exe.")
        site_packages = extracted_python / "Lib" / "site-packages"
        scripts = extracted_python / "Scripts"

        (python_root / "Lib").mkdir(parents=True, exist_ok=True)
        if site_packages.exists():
            shutil.move(str(site_packages), str(python_root / "Lib" / "site-packages"))
        else:
            (python_root / "Lib" / "site-packages").mkdir(parents=True)

        if scripts.exists():
            shutil.move(str(scripts), str(python_root / "Scripts"))
        else:
            (python_root / "Scripts").mkdir(parents=True)

        shutil.move(str(extracted_python), str(python_root / "python"))

    (python_root / "pyvenv.cfg").write_text(
        f"home = {(python_root / 'python').resolve().as_posix()}\n"
        "include-system-site-packages = false\n",
        encoding="utf-8",
    )


def _python_matches(python_executable: Path, version_pattern: str | None) -> bool:
    if not python_executable.exists():
        return False
    completed = subprocess.run(
        [str(python_executable), "-V"],
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        return False
    version = (completed.stdout or completed.stderr).strip().split()[-1]
    return _matches_version_pattern(version_pattern, version)


def establish_bundled_python(
    project_root: Path,
    options: PythonBundledOptions,
) -> Path:
    python_root = project_root / options.path
    python_executable = _bundled_python_executable(python_root)
    if not (
        _python_matches(python_executable, options.python_version)
        and _nuget_source_marker_matches(python_root, options.python_version)
    ):
        package = _resolve_nuget_python_package(options.python_version)
        package_path = _ensure_downloaded_file(package.download_url, package.digest)
        _extract_nuget_python_package(package_path, python_root)
        _write_nuget_source_marker(python_root, package)

    python_executable = _bundled_python_executable(python_root)
    if not _python_matches(python_executable, options.python_version):
        raise RuntimeError(
            f"Materialized Python at {python_executable} did not match "
            f"configured version {options.python_version!r}."
        )
    return python_executable


def _ensure_bundled_python(
    project_root: Path,
    options: PythonBundledOptions,
    poetry_lock: PoetryLock,
) -> Path:
    python_executable = establish_bundled_python(project_root, options)
    _ensure_pip(python_executable)
    install_locked_poetry_dependencies(
        project_root=project_root,
        python_executable=python_executable,
        poetry_lock=poetry_lock,
        groups={MAIN_GROUP},
    )
    return python_executable


def _read_pyvenv_executable(venv_root: Path) -> Path | None:
    return _read_pyvenv_path(venv_root, "executable")


def _read_pyvenv_home(venv_root: Path) -> Path | None:
    return _read_pyvenv_path(venv_root, "home")


def _read_pyvenv_path(venv_root: Path, key: str) -> Path | None:
    pyvenv_cfg = venv_root / "pyvenv.cfg"
    if not pyvenv_cfg.exists():
        return None
    for line in pyvenv_cfg.read_text(encoding="utf-8").splitlines():
        if line.lower().startswith(f"{key.lower()} ="):
            return Path(line.split("=", 1)[1].strip())
    return None


def _base_site_packages_pth(venv_root: Path) -> Path:
    return venv_root / "Lib" / "site-packages" / "base_site_packages.pth"


def _read_base_site_packages(venv_root: Path) -> Path | None:
    site_packages_pth = _base_site_packages_pth(venv_root)
    if not site_packages_pth.exists():
        return None
    text = site_packages_pth.read_text(encoding="utf-8").strip()
    prefix = "import site; site.addsitedir("
    if not text.startswith(prefix) or not text.endswith(")"):
        return None
    value = text[len(prefix) : -1]
    try:
        parsed = ast.literal_eval(value)
    except (SyntaxError, ValueError):
        return None
    if not isinstance(parsed, str):
        return None
    return Path(parsed)


def _write_base_site_packages(venv_root: Path, base_site_packages: Path) -> None:
    site_packages_pth = _base_site_packages_pth(venv_root)
    site_packages_pth.parent.mkdir(parents=True, exist_ok=True)
    site_packages_pth.write_text(
        f"import site; site.addsitedir({base_site_packages.as_posix()!r})\n",
        encoding="utf-8",
    )


def _venv_matches_bundled_python(venv_root: Path, bundled_root: Path) -> bool:
    base_python = _bundled_python_executable(bundled_root)
    pyvenv_executable = _read_pyvenv_executable(venv_root)
    base_site_packages = _read_base_site_packages(venv_root)
    expected_site_packages = bundled_root / "Lib" / "site-packages"
    return (
        pyvenv_executable is not None
        and pyvenv_executable.resolve() == base_python.resolve()
        and base_site_packages is not None
        and base_site_packages.resolve() == expected_site_packages.resolve()
    )


def _copy_bundled_runtime_support(bundled_root: Path, venv_root: Path) -> None:
    exclude_relpath_lower_strings = {
        "scripts/activate",
        "scripts/activate.bat",
        "scripts/activate.ps1",
        "scripts/deactivate.bat",
        "scripts/python.exe",
        "scripts/pythonw.exe",
        "python",
        "python.exe",
        "pyvenv.cfg",
        "lib",
        _NUGET_SOURCE_MARKER,
        _NUGET_PACKAGE_PAYLOAD_ROOT,
    }

    def copy_included_files(source: Path = bundled_root) -> None:
        relpath = source.resolve().relative_to(bundled_root.resolve())
        if relpath.as_posix().lower() in exclude_relpath_lower_strings:
            return
        if source.is_dir():
            for child in source.iterdir():
                copy_included_files(child)
            return
        destination = venv_root / relpath
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)

    copy_included_files()


def _create_venv_from_bundled_python(venv_root: Path, bundled_root: Path) -> Path:
    if _venv_matches_bundled_python(venv_root, bundled_root):
        return _python_executable(venv_root)
    if venv_root.exists():
        shutil.rmtree(venv_root)

    base_python = _bundled_python_executable(bundled_root)
    subprocess.run(
        [str(base_python), "-m", "venv", str(venv_root), "--without-pip"],
        check=True,
    )
    _copy_bundled_runtime_support(bundled_root, venv_root)
    _write_base_site_packages(venv_root, bundled_root / "Lib" / "site-packages")
    return _python_executable(venv_root)


def _self_contained_venv_python_executable(venv_root: Path) -> Path:
    return venv_root / "python" / "python.exe"


def _self_contained_venv_matches(
    venv_root: Path,
    python_version: str | None,
) -> bool:
    home = _read_pyvenv_home(venv_root)
    expected_home = venv_root / "python"
    return (
        home is not None
        and home.resolve() == expected_home.resolve()
        and _python_matches(
            _self_contained_venv_python_executable(venv_root),
            python_version,
        )
        and _nuget_source_marker_matches(venv_root, python_version)
        and _exe_wrap_source_marker_matches(venv_root)
        and _exe_wrap_launcher_matches(
            _self_contained_venv_launcher_executable(venv_root),
            _exe_wrap_python_config("python.exe"),
        )
        and _exe_wrap_launcher_matches(
            _self_contained_venv_windowed_launcher_executable(venv_root),
            _exe_wrap_python_config("pythonw.exe"),
        )
    )


def _exe_wrap_source_marker_matches(venv_root: Path) -> bool:
    marker_path = venv_root / _EXE_WRAP_SOURCE_MARKER
    try:
        payload: Any = json.loads(marker_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    if not isinstance(payload, Mapping):
        return False
    platform_tag = _exe_wrap_platform_tag()
    return (
        payload.get("version") == EXE_WRAP_VERSION
        and payload.get("asset_name")
        == f"ExeWrap-{EXE_WRAP_VERSION}-{platform_tag}.zip"
        and payload.get("digest") == _EXE_WRAP_DIGESTS[platform_tag]
    )


def _create_self_contained_venv(
    venv_root: Path,
    options: PythonVenvOptions,
) -> Path:
    if _self_contained_venv_matches(venv_root, options.python_version):
        return _self_contained_venv_launcher_executable(venv_root)
    if venv_root.exists():
        shutil.rmtree(venv_root)

    package = _resolve_nuget_python_package(options.python_version)
    package_path = _ensure_downloaded_file(package.download_url, package.digest)
    _extract_nuget_python_package(package_path, venv_root)
    _write_nuget_source_marker(venv_root, package)
    _ensure_pip(_self_contained_venv_python_executable(venv_root))
    _install_exe_wrap_python_launchers(venv_root)
    return _self_contained_venv_launcher_executable(venv_root)


@dataclass(slots=True)
class PythonEnvironmentResult:
    python_bundled: Path | None
    python_venv: Path | None
    build_inputs: tuple[dict[str, str], ...] = ()


class PythonEnvironmentMaterializer:
    """Materialize project Python runtimes in lifecycle-visible stages."""

    def __init__(
        self,
        project_root: Path,
        *,
        app_version: str | None = None,
    ) -> None:
        self.project_root = project_root
        _, self.config = load_project_config(
            project_root,
            app_version=app_version,
        )
        self.poetry_lock: PoetryLock | None = None
        if (
            self.config.python_bundled is not None
            or self.config.python_venv is not None
        ):
            self.poetry_lock = ensure_poetry_lock(project_root)
        self.python_bundled: Path | None = None
        self.python_venv: Path | None = None
        self._bundled_materialized = False
        self._venv_materialized = False

    def materialize_bundled(self) -> Path | None:
        if self._bundled_materialized:
            return self.python_bundled
        if self.config.python_bundled is not None:
            assert self.poetry_lock is not None
            self.python_bundled = _ensure_bundled_python(
                self.project_root,
                self.config.python_bundled,
                self.poetry_lock,
            )
        self._bundled_materialized = True
        return self.python_bundled

    def materialize_venv(self) -> Path | None:
        if self._venv_materialized:
            return self.python_venv
        if not self._bundled_materialized:
            raise RuntimeError(
                "Bundled Python stage must complete before the venv stage."
            )
        if self.config.python_venv is not None:
            assert self.poetry_lock is not None
            venv_root = self.project_root / self.config.python_venv.path
            if self.config.python_bundled is not None:
                bundled_root = self.project_root / self.config.python_bundled.path
                self.python_venv = _create_venv_from_bundled_python(
                    venv_root,
                    bundled_root,
                )
                venv_groups = {DEV_GROUP}
            else:
                self.python_venv = _create_self_contained_venv(
                    venv_root,
                    self.config.python_venv,
                )
                venv_groups = {MAIN_GROUP, DEV_GROUP}
            install_locked_poetry_dependencies(
                project_root=self.project_root,
                python_executable=self.python_venv,
                poetry_lock=self.poetry_lock,
                groups=venv_groups,
            )
        self._venv_materialized = True
        return self.python_venv

    def result(self) -> PythonEnvironmentResult:
        marker_roots = [
            root
            for root in (
                (
                    self.project_root / self.config.python_bundled.path
                    if self._bundled_materialized
                    and self.config.python_bundled is not None
                    else None
                ),
                (
                    self.project_root / self.config.python_venv.path
                    if self._venv_materialized and self.config.python_venv is not None
                    else None
                ),
            )
            if root is not None
        ]
        return PythonEnvironmentResult(
            python_bundled=self.python_bundled,
            python_venv=self.python_venv,
            build_inputs=_python_environment_build_inputs(
                self.project_root,
                self.poetry_lock,
                marker_roots,
            ),
        )


def ensure_bundled_python(project_root: Path) -> Path | None:
    _, config = load_project_config(project_root)
    if config.python_bundled is None:
        return None
    return establish_bundled_python(project_root, config.python_bundled)


def _python_environment_build_inputs(
    project_root: Path,
    poetry_lock: PoetryLock | None,
    marker_roots: Sequence[Path],
) -> tuple[dict[str, str], ...]:
    build_inputs: list[dict[str, str]] = []
    if poetry_lock is not None:
        if poetry_lock.path is not None and poetry_lock.sha256 is not None:
            build_inputs.append(
                {
                    "kind": "poetry_lock",
                    "path": poetry_lock.path.relative_to(
                        project_root.resolve()
                    ).as_posix(),
                    "sha256": poetry_lock.sha256,
                    "content_hash": poetry_lock.content_hash or "",
                }
            )
        for marker_root in marker_roots:
            for marker_name, kind in (
                (_NUGET_SOURCE_MARKER, "nuget_python"),
                (_EXE_WRAP_SOURCE_MARKER, "exewrap"),
            ):
                marker_path = marker_root / marker_name
                if not marker_path.is_file():
                    continue
                marker = json.loads(marker_path.read_text(encoding="utf-8"))
                if not isinstance(marker, Mapping):
                    continue
                record = {"kind": kind}
                record.update(
                    {
                        str(key): str(value)
                        for key, value in marker.items()
                        if value is not None
                    }
                )
                if record not in build_inputs:
                    build_inputs.append(record)
    return tuple(build_inputs)


def ensure_python_environments(project_root: Path) -> PythonEnvironmentResult:
    materializer = PythonEnvironmentMaterializer(project_root)
    materializer.materialize_bundled()
    materializer.materialize_venv()
    return materializer.result()
