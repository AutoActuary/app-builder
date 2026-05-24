from __future__ import annotations

import ast
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.error
import urllib.parse
import urllib.request
import venv
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from zipfile import ZipFile

from .config import load_project_config
from .schema import PythonBundledOptions

NUGET_PYTHON_PACKAGE_ID = "python"
NUGET_FLAT_CONTAINER_BASE_URL = "https://api.nuget.org/v3-flatcontainer"
NUGET_PYTHON_INDEX_URL = (
    f"{NUGET_FLAT_CONTAINER_BASE_URL}/{NUGET_PYTHON_PACKAGE_ID}/index.json"
)
_VERSION_PATTERN_RE = re.compile(r"^\d+(?:\.\d+)*(?:[-+][0-9A-Za-z_.-]+)?$")
_NUGET_SOURCE_MARKER = ".app-builder-python-source.json"
_NUGET_PACKAGE_PAYLOAD_ROOT = "tools"


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


def _install_requirements(
    python_executable: Path,
    requirements: list[str],
    requirement_files: list[Path],
) -> None:
    if not requirements and not requirement_files:
        return
    command = [
        str(python_executable),
        "-E",
        "-m",
        "pip",
        "install",
        "--upgrade",
        "--no-warn-script-location",
        "--disable-pip-version-check",
    ]
    command.extend(requirements)
    for requirement_file in requirement_files:
        command.extend(["-r", str(requirement_file)])
    subprocess.run(command, check=True)


def _install_pip_version(python_executable: Path, pip_version: str) -> None:
    subprocess.run(
        [
            str(python_executable),
            "-E",
            "-m",
            "pip",
            "install",
            "--upgrade",
            f"pip=={pip_version}",
            "--no-warn-script-location",
            "--disable-pip-version-check",
        ],
        check=True,
    )


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


def _expand_requirement_files(project_root: Path, patterns: list[str]) -> list[Path]:
    files: list[Path] = []
    for pattern in patterns:
        matched = list(project_root.glob(os.path.expandvars(pattern)))
        if not matched:
            raise FileNotFoundError(
                f"No requirements file matched pattern '{pattern}'."
            )
        files.extend(path for path in matched if path.is_file())
    return files


def _create_venv(target: Path, *, python_executable: Path | None = None) -> Path:
    target_python = _python_executable(target)
    if target_python.exists():
        return target_python
    if target.exists():
        shutil.rmtree(target)
    if python_executable is None:
        builder = venv.EnvBuilder(
            with_pip=True,
            clear=False,
            symlinks=False,
            upgrade=False,
        )
        builder.create(str(target))
        return target_python

    subprocess.run(
        [str(python_executable), "-m", "venv", str(target), "--copies"],
        check=True,
    )
    return target_python


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


def _resolve_nuget_python_package(python_version: str | None) -> NuGetPythonPackage:
    versions = _load_nuget_python_versions()
    selected_version = _select_nuget_python_version(versions, python_version)
    return NuGetPythonPackage(
        version=selected_version,
        download_url=_nuget_python_download_url(selected_version),
    )


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


def _download_package_to_temp(
    package: NuGetPythonPackage,
    temp_root: Path,
) -> Path:
    url = package.download_url
    filename = Path(urllib.parse.urlsplit(url).path).name
    if not filename:
        filename = f"{NUGET_PYTHON_PACKAGE_ID}.{package.version}.nupkg"
    package_path = temp_root / filename
    _download_file(url, package_path)
    return package_path


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
    return (
        package_id == NUGET_PYTHON_PACKAGE_ID
        and isinstance(version, str)
        and _matches_version_pattern(python_version, version)
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
        with tempfile.TemporaryDirectory() as temp_dir_str:
            package_path = _download_package_to_temp(package, Path(temp_dir_str))
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
) -> Path:
    python_executable = establish_bundled_python(project_root, options)
    _ensure_pip(python_executable)
    _install_pip_version(python_executable, options.pip_version)
    _install_requirements(
        python_executable,
        options.requirements,
        _expand_requirement_files(project_root, options.requirements_files),
    )
    return python_executable


def _read_pyvenv_executable(venv_root: Path) -> Path | None:
    pyvenv_cfg = venv_root / "pyvenv.cfg"
    if not pyvenv_cfg.exists():
        return None
    for line in pyvenv_cfg.read_text(encoding="utf-8").splitlines():
        if line.lower().startswith("executable ="):
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


@dataclass(slots=True)
class PythonEnvironmentResult:
    python_bundled: Path | None
    python_venv: Path | None


def ensure_bundled_python(project_root: Path) -> Path | None:
    _, config = load_project_config(project_root)
    if config.python_bundled is None:
        return None
    return establish_bundled_python(project_root, config.python_bundled)


def ensure_python_environments(project_root: Path) -> PythonEnvironmentResult:
    _, config = load_project_config(project_root)
    bundled_python: Path | None = None
    bundled_root: Path | None = None
    venv_python: Path | None = None

    if config.python_bundled is not None:
        bundled_python = _ensure_bundled_python(project_root, config.python_bundled)
        bundled_root = project_root / config.python_bundled.path

    if config.python_venv is not None:
        venv_root = project_root / config.python_venv.path
        if bundled_root is not None:
            venv_python = _create_venv_from_bundled_python(venv_root, bundled_root)
        else:
            venv_python = _create_venv(
                venv_root, python_executable=Path(sys.executable)
            )
        _install_requirements(
            venv_python,
            config.python_venv.requirements,
            _expand_requirement_files(
                project_root, config.python_venv.requirements_files
            ),
        )

    return PythonEnvironmentResult(
        python_bundled=bundled_python,
        python_venv=venv_python,
    )
