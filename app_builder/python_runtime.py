from __future__ import annotations

import ast
import json
import os
import shutil
import subprocess
import sys
import tempfile
import urllib.parse
import urllib.request
import venv
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from .config import load_project_config
from .schema import PythonBundledOptions

WINPYTHON_RELEASES_API = (
    "https://api.github.com/repos/winpython/winpython/releases?per_page=100&page={page}"
)


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
    if pattern is None:
        return True
    cleaned = pattern.strip()
    if cleaned in ("", "*"):
        return True
    if cleaned.endswith(".*"):
        cleaned = cleaned[:-2]
    return version == cleaned or version.startswith(f"{cleaned}.")


def _select_winpython_download_url(
    releases: list[Mapping[str, Any]],
    python_version: str | None,
) -> str | None:
    for release in releases:
        assets = release.get("assets", [])
        if not isinstance(assets, list):
            continue
        for asset in assets:
            if not isinstance(asset, Mapping):
                continue
            name = asset.get("name")
            url = asset.get("browser_download_url")
            if not isinstance(name, str) or not isinstance(url, str):
                continue
            lowered_name = name.lower()
            if not lowered_name.startswith("winpython64-"):
                continue
            if not lowered_name.endswith("dot.exe"):
                continue
            asset_version = lowered_name.removeprefix("winpython64-").removesuffix(
                "dot.exe"
            )
            if _matches_version_pattern(python_version, asset_version):
                return url
    return None


def _load_winpython_release_page(page: int) -> list[Mapping[str, Any]]:
    request = urllib.request.Request(
        WINPYTHON_RELEASES_API.format(page=page),
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": "app-builder",
        },
    )
    with urllib.request.urlopen(request) as response:
        payload = json.loads(response.read().decode("utf-8"))
    if not isinstance(payload, list):
        raise RuntimeError("Unexpected WinPython release response from GitHub.")
    return [item for item in payload if isinstance(item, Mapping)]


def _get_winpython_download_url(python_version: str | None) -> str:
    page = 1
    while True:
        releases = _load_winpython_release_page(page)
        if not releases:
            break
        url = _select_winpython_download_url(releases, python_version)
        if url is not None:
            return url
        page += 1
    raise RuntimeError(f"Could not find a WinPython download for {python_version!r}.")


def _download_file(url: str, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    request = urllib.request.Request(url, headers={"User-Agent": "app-builder"})
    with urllib.request.urlopen(request) as response:
        with destination.open("wb") as output:
            shutil.copyfileobj(response, output)


def _download_cache_path(url: str) -> Path:
    filename = Path(urllib.parse.urlsplit(url).path).name
    return Path(tempfile.gettempdir(), "app-builder-downloads", filename)


def _sevenzip_executable() -> Path:
    packaged = Path(__file__).resolve().parent / "src-legacy" / "bin" / "7z.exe"
    if packaged.exists():
        return packaged
    found = shutil.which("7z") or shutil.which("7za")
    if found is None:
        raise FileNotFoundError("Could not find 7z or 7za to extract WinPython.")
    return Path(found)


def _find_extracted_python_dir(extract_root: Path) -> Path:
    candidates = [
        *extract_root.glob("*/python-*"),
        *extract_root.glob("*/python"),
        *extract_root.glob("python-*"),
        *extract_root.glob("python"),
    ]
    for candidate in candidates:
        if candidate.is_dir():
            return candidate
    raise RuntimeError("Could not find the extracted WinPython Python directory.")


def _install_python_wrappers(python_root: Path) -> None:
    wrappers_dir = (
        Path(__file__).resolve().parent
        / "src-legacy"
        / "assets"
        / "python-venv-exe-wrapper"
    )
    python_wrapper = wrappers_dir / "python-venv-exe-wrapper.exe"
    pythonw_wrapper = wrappers_dir / "pythonw-venv-exe-wrapper.exe"
    wrapper_targets = [
        (python_wrapper, python_root / "python.exe"),
        (python_wrapper, python_root / "Scripts" / "python.exe"),
        (pythonw_wrapper, python_root / "Scripts" / "pythonw.exe"),
    ]
    for source, target in wrapper_targets:
        if source.exists():
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)


def _extract_winpython(installer_path: Path, python_root: Path) -> None:
    if python_root.exists():
        shutil.rmtree(python_root)
    with tempfile.TemporaryDirectory() as temp_dir_str:
        extract_root = Path(temp_dir_str, "extract")
        extract_root.mkdir()
        subprocess.run(
            [
                str(_sevenzip_executable()),
                "x",
                "-y",
                f"-o{extract_root}",
                str(installer_path),
            ],
            check=True,
        )
        extracted_python = _find_extracted_python_dir(extract_root)
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
        "include-system-site-packages = false\n",
        encoding="utf-8",
    )
    _install_python_wrappers(python_root)


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


def _ensure_bundled_python(
    project_root: Path,
    options: PythonBundledOptions,
) -> Path:
    python_root = project_root / options.path
    python_executable = _bundled_python_executable(python_root)
    if not _python_matches(python_executable, options.python_version):
        download_url = _get_winpython_download_url(options.python_version)
        installer_path = _download_cache_path(download_url)
        if not installer_path.exists():
            _download_file(download_url, installer_path)
        _extract_winpython(installer_path, python_root)

    python_executable = _bundled_python_executable(python_root)
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
