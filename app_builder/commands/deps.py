import click
from pathlib import Path

from ..build import ensure_python_environments
from ..project import find_project_root


@click.command()
def deps() -> None:
    """
    Ensure configured Python environments are set up.
    """

    result = ensure_python_environments(find_project_root(Path.cwd()))
    click.echo(f"Bundled Python: {result.python_bundled or 'disabled'}")
    click.echo(f"Build venv: {result.python_venv or 'disabled'}")
