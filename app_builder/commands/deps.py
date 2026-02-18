import click

from ..get_dependencies import get_dependencies


@click.command()
def deps() -> None:
    """
    Ensure all the dependencies are set up properly.
    """
    get_dependencies()
