from __future__ import annotations

from typing import Any

from .schema import AppBuilderConfig

try:
    from pydantic import BaseModel, ConfigDict

    class _PythonBundledModel(BaseModel):
        model_config = ConfigDict(extra="forbid")
        path: str = "bin/python"
        python_version: str = "3.11.1"
        pip_version: str = "23.2.1"
        requirements: list[str] = []
        requirements_files: list[str] = []

    class _PythonVenvModel(BaseModel):
        model_config = ConfigDict(extra="forbid")
        path: str = "venv"
        requirements: list[str] = []
        requirements_files: list[str] = []

    class _InstallHooksModel(BaseModel):
        model_config = ConfigDict(extra="forbid")
        pre_install: list[str] = []
        post_install: list[str] = []
        pre_uninstall: list[str] = []
        post_uninstall: list[str] = []

    class _PathsMappingModel(BaseModel):
        model_config = ConfigDict(extra="forbid")
        include: list[str] = []
        exclude: list[str] = []
        remap: list[tuple[str, str]] = []

    class _StartMenuShortcutModel(BaseModel):
        model_config = ConfigDict(extra="forbid")
        target: str
        display_name: str | None = None
        icon: str | None = None

    class _InstallerOptionsModel(BaseModel):
        model_config = ConfigDict(extra="forbid")
        name: str
        install_directory: str
        ascii_banner: str = "application-templates/asciibanner.txt"
        icon: str = "application-templates/icon.ico"
        pause_on_exit: bool = True
        add_uninstaller: bool = True
        start_menu: list[_StartMenuShortcutModel] = []
        install_hooks: _InstallHooksModel = _InstallHooksModel()
        dist: str = "dist"
        paths: _PathsMappingModel = _PathsMappingModel()

    class _BuildHooksModel(BaseModel):
        model_config = ConfigDict(extra="forbid")
        pre_process: list[str] = []
        pre_python_bundled: list[str] = []
        post_python_bundled: list[str] = []
        pre_python_venv: list[str] = []
        post_python_venv: list[str] = []
        pre_dist: list[str] = []
        post_dist: list[str] = []
        pre_github_release: list[str] = []
        post_github_release: list[str] = []
        post_process: list[str] = []

    class AppBuilderPydanticModel(BaseModel):
        model_config = ConfigDict(extra="forbid")
        app_builder_version: str | None = "v1.0.0"
        python_bundled: _PythonBundledModel | None = _PythonBundledModel()
        python_venv: _PythonVenvModel | None = _PythonVenvModel()
        installer: _InstallerOptionsModel
        build_hooks: _BuildHooksModel = _BuildHooksModel()

    PYDANTIC_AVAILABLE = True

except ImportError:  # pragma: no cover
    AppBuilderPydanticModel = None  # type: ignore[assignment]
    PYDANTIC_AVAILABLE = False


def to_pydantic_model(config: AppBuilderConfig) -> Any:
    if not PYDANTIC_AVAILABLE:
        return None
    return AppBuilderPydanticModel.model_validate(config.to_dict())
