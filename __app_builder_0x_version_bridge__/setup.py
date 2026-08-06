from __future__ import annotations

import tomllib
from pathlib import Path

from setuptools import find_packages, setup
from setuptools.command.build_py import build_py

BRIDGE_ROOT = Path(__file__).resolve().parent
PROJECT_ROOT = BRIDGE_ROOT.parent
BRIDGE_VERSION = "1.0.0"


def _project_dependencies() -> list[str]:
    with (PROJECT_ROOT / "pyproject.toml").open("rb") as pyproject_file:
        payload = tomllib.load(pyproject_file)
    project = payload.get("project")
    dependencies = project.get("dependencies") if isinstance(project, dict) else None
    if not isinstance(dependencies, list) or not all(
        isinstance(dependency, str) for dependency in dependencies
    ):
        raise RuntimeError(
            "Root pyproject.toml must declare project.dependencies as strings."
        )
    return dependencies


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
