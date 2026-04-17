from pathlib import Path

import click

from ..build import build_release, upload_release_to_github
from ..project import find_project_root


@click.command()
@click.option("--version", type=str, default=None)
@click.option("--draft/--no-draft", default=False)
def release_gh(*, version: str | None, draft: bool) -> None:
    """
    Create a release and upload it to GitHub.
    """

    project_root = find_project_root(Path.cwd())
    release_result = build_release(project_root, version=version)
    click.echo(upload_release_to_github(project_root, release=release_result, draft=draft))
