from __future__ import annotations

import tomllib
from pathlib import Path

from setuptools import find_packages, setup
from setuptools.command.build_py import build_py

BRIDGE_ROOT = Path(__file__).resolve().parent
PROJECT_ROOT = BRIDGE_ROOT.parent
BRIDGE_VERSION = "1.0.0"


def _project_dependencies() -> list[str]:
    with (PROJECT_ROOT / "poetry.lock").open("rb") as lock_file:
        payload = tomllib.load(lock_file)
    packages = payload.get("package")
    if not isinstance(packages, list):
        raise RuntimeError("Root poetry.lock has no package inventory.")
    dependencies: list[str] = []
    for package in packages:
        if not isinstance(package, dict):
            raise RuntimeError("Root poetry.lock has an invalid package entry.")
        groups = package.get("groups", ["main"])
        if not isinstance(groups, list) or not all(
            isinstance(group, str) for group in groups
        ):
            raise RuntimeError("Root poetry.lock package has invalid groups.")
        if "main" not in groups or package.get("optional", False):
            continue
        name = package.get("name")
        version = package.get("version")
        source = package.get("source")
        if not isinstance(name, str) or not isinstance(version, str):
            raise RuntimeError("Root poetry.lock package has no name or version.")
        if source is not None and (
            not isinstance(source, dict) or source.get("type") != "legacy"
        ):
            raise RuntimeError(
                f"Bridge dependency {name!r} must come from a package index."
            )
        requirement = f"{name}=={version}"
        marker = package.get("markers")
        if isinstance(marker, dict):
            marker = marker.get("main")
        if isinstance(marker, str) and marker:
            requirement += f"; {marker}"
        dependencies.append(requirement)
    return sorted(dependencies, key=str.lower)


class BuildPyWithActivator(build_py):
    def run(self) -> None:
        super().run()
        build_root = Path(self.build_lib)
        build_root.mkdir(parents=True, exist_ok=True)
        (build_root / "app_builder_0x_version_bridge.pth").write_text(
            "import __app_builder_0x_version_bridge__.activate\n",
            encoding="ascii",
        )


setup(
    name="app-builder-0x-version-bridge",
    version=BRIDGE_VERSION,
    description="Compatibility bridge from app-builder 0.x version caches to 1.x.",
    packages=find_packages(where="src"),
    package_dir={"": "src"},
    package_data={"__app_builder_0x_version_bridge__": ["py.typed"]},
    python_requires=">=3.11,<4.0",
    install_requires=_project_dependencies(),
    cmdclass={"build_py": BuildPyWithActivator},
)
