import click

from ..util import init as init_


@click.command()
def init() -> None:
    """
    Initialize the current git repository as an app-builder project.
    """
    init_()
