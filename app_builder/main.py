from __future__ import annotations

from pathlib import Path

import click

from . import __version__
from .build import build_release, ensure_python_environments, upload_release_to_github
from .project import find_project_root
from .template import initialize_project


@click.group(context_settings={"help_option_names": ["-h", "--help"]})
@click.version_option(version=__version__, prog_name="app-builder")
def main() -> None:
    """
    Build and package Windows-first Python applications.
    """


@main.command()
@click.option(
    "--force",
    is_flag=True,
    help="Overwrite an existing template config if one already exists.",
)
def init(*, force: bool) -> None:
    """
    Create a commented app_builder.yaml template in the current git repository.
    """

    initialize_project(Path.cwd(), force=force)


@main.command()
def deps() -> None:
    """
    Materialize configured Python environments without creating a release.
    """

    project_root = find_project_root(Path.cwd())
    result = ensure_python_environments(project_root)
    click.echo(f"Bundled Python: {result.python_bundled or 'disabled'}")
    click.echo(f"Build venv: {result.python_venv or 'disabled'}")


@main.command("release")
@click.option(
    "--version",
    type=str,
    default=None,
    help="Override the release version. Defaults to git describe or '0.0.0-dev'.",
)
def release_cmd(*, version: str | None) -> None:
    """
    Build a local release artifact set.
    """

    project_root = find_project_root(Path.cwd())
    release = build_release(project_root, version=version)
    click.echo(f"Created payload: {release.payload_archive}")
    click.echo(f"Created installer bundle: {release.installer_archive}")
    click.echo(f"Created manifest: {release.manifest_path}")


@main.command("release-gh")
@click.option(
    "--version",
    type=str,
    default=None,
    help="Override the release version. Defaults to git describe or '0.0.0-dev'.",
)
@click.option(
    "--draft/--no-draft",
    default=False,
    help="Create a draft GitHub release.",
)
def release_gh_cmd(*, version: str | None, draft: bool) -> None:
    """
    Build a release and upload it to GitHub.
    """

    project_root = find_project_root(Path.cwd())
    release = build_release(project_root, version=version)
    url = upload_release_to_github(project_root, release=release, draft=draft)
    click.echo(url)
