from pathlib import Path

import click

from ..build import build_release
from ..project import find_project_root


@click.command()
@click.option("--version", type=str, default=None)
def release(*, version: str | None) -> None:
    """
    Create a local release.
    """

    release_result = build_release(find_project_root(Path.cwd()), version=version)
    click.echo(str(release_result.installer_archive))
