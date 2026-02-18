import click

from ..create_release import create_release


@click.command()
@click.option(
    "--version",
    type=str,
    help="The version for the release. "
    "If not provided, the version will be detected automatically from `git describe --tags` if possible, "
    "or else fall back to `unknown`.",
    default=None,
)
def release(
    *,
    version: str | None,
) -> None:
    """
    Create a release.
    """
    create_release(version=version)
