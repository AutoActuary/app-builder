from __future__ import annotations

import sys
from pathlib import Path

import click

from app_builder_meta.version_cache import (
    default_cache_root,
    managed_version_manifests,
    remove_managed_version,
)

from . import __version__
from .build import build_release, ensure_python_environments, upload_release_to_github
from .project import find_project_root
from .poetry_dependencies import refresh_poetry_lock
from .python_runtime import ensure_bundled_python
from .template import initialize_project


def _help_html_url() -> str:
    for help_path in _help_html_candidates():
        if help_path.is_file():
            return help_path.resolve().as_uri()
    return (
        "https://github.com/AutoActuary/app-builder/blob/1.x/docs/app-builder-help.html"
    )


def _help_html_candidates() -> tuple[Path, ...]:
    package_parent = Path(__file__).resolve().parents[1]
    return (
        package_parent / "docs" / "app-builder-help.html",
        Path(sys.prefix) / "share" / "app-builder" / "docs" / "app-builder-help.html",
    )


class AppBuilderGroup(click.Group):
    def format_help(self, ctx: click.Context, formatter: click.HelpFormatter) -> None:
        formatter.write(f"Full help: {_help_html_url()}\n\n")
        super().format_help(ctx, formatter)


@click.group(
    cls=AppBuilderGroup,
    context_settings={"help_option_names": ["-h", "--help"]},
)
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


@main.command("lock")
def lock_cmd() -> None:
    """
    Explicitly create or refresh poetry.lock for subsequent reproducible builds.
    """

    project_root = find_project_root(Path.cwd())
    poetry_lock = refresh_poetry_lock(project_root)
    click.echo(f"Refreshed lock: {poetry_lock.path}")
    click.echo(f"SHA-256: {poetry_lock.sha256}")


@main.group("versions")
def versions_cmd() -> None:
    """
    Inspect or remove managed app-builder version caches.
    """


@versions_cmd.command("list")
def versions_list_cmd() -> None:
    """List cached app-builder refs and their resolved commits."""

    click.echo(f"Cache: {default_cache_root()}")
    manifests = managed_version_manifests()
    if not manifests:
        click.echo("No managed versions are cached.")
        return
    for manifest in manifests:
        click.echo(
            f"{manifest.get('requested_ref')}  {manifest.get('resolved_commit')}  "
            f"[{manifest.get('ref_kind')}]"
        )


@versions_cmd.command("remove")
@click.argument("ref")
def versions_remove_cmd(ref: str) -> None:
    """Remove one cached app-builder ref; it will be recreated on next use."""

    if remove_managed_version(ref):
        click.echo(f"Removed managed version cache for {ref}.")
    else:
        raise click.ClickException(f"No managed version cache exists for {ref}.")


@main.command("python")
def python_cmd() -> None:
    """
    Materialize only the configured bundled Python runtime.
    """

    project_root = find_project_root(Path.cwd())
    bundled_python = ensure_bundled_python(project_root)
    click.echo(f"Bundled Python: {bundled_python or 'disabled'}")


@main.command("release")
@click.option(
    "--version",
    type=str,
    default=None,
    help="Override the release version. Defaults to git describe or '0.0.0-dev'.",
)
@click.option("--verbose", is_flag=True, help="Show detailed build diagnostics.")
def release_cmd(*, version: str | None, verbose: bool) -> None:
    """
    Build a local release artifact set.
    """

    project_root = find_project_root(Path.cwd())
    release = build_release(project_root, version=version, verbose=verbose)
    click.echo(f"Created payload: {release.payload_archive}")
    click.echo(f"Created installer bundle: {release.installer_archive}")
    click.echo(f"Created manifest: {release.manifest_path}")
    click.echo(f"Created checksums: {release.checksums_path}")
    click.echo(f"Created release notes: {release.release_notes_path}")
    click.echo(f"Build log: {release.build_log_path}")
    for output in release.outputs:
        if output.name not in {"payload", "installer", "manifest", "checksums"}:
            click.echo(f"Collected output {output.name}: {output.path}")


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
@click.option("--verbose", is_flag=True, help="Show detailed build diagnostics.")
def release_gh_cmd(*, version: str | None, draft: bool, verbose: bool) -> None:
    """
    Build a release and upload it to GitHub.
    """

    project_root = find_project_root(Path.cwd())
    release = build_release(project_root, version=version, verbose=verbose)
    url = upload_release_to_github(project_root, release=release, draft=draft)
    click.echo(url)
