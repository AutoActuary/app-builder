import click

from ..create_release import create_release


@click.command()
def release() -> None:
    """
    Create a release.
    """
    create_release()
