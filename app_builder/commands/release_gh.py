import click

from ..create_github_release import create_github_release


@click.command()
def release_gh() -> None:
    """
    Create a release and upload it to GitHub.
    """
    create_github_release()
