from __future__ import annotations

import shutil
from pathlib import Path

from .project import find_project_root


def initialize_project(start: Path, *, force: bool) -> Path:
    project_root = find_project_root(start)
    config_path = project_root / "app_builder.yaml"
    if config_path.exists() and not force:
        raise FileExistsError(f"{config_path} already exists. Use --force to overwrite it.")

    template_assets_dir = project_root / "application-templates"
    template_assets_dir.mkdir(exist_ok=True)
    package_assets_dir = Path(__file__).resolve().parent / "assets" / "templates"
    for asset in package_assets_dir.iterdir():
        if asset.is_file():
            shutil.copy2(asset, template_assets_dir / asset.name)

    template_path = Path(__file__).resolve().parent / "assets" / "app_builder_template.yaml"
    config_path.write_text(template_path.read_text(encoding="utf-8"), encoding="utf-8")
    return config_path
