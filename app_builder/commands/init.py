import click
from pathlib import Path

from ..template import initialize_project


@click.command()
@click.option("--force", is_flag=True, help="Overwrite an existing template config if one already exists.")
def init(*, force: bool) -> None:
    """
    Initialize the current git repository as an app-builder project.
    """

    initialize_project(Path.cwd(), force=force)
