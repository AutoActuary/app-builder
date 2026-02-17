import sys
from pathlib import Path
from typing import Any

import click
from .commands.init import init
from .commands.deps import deps
from .commands.release import release
from .commands.release_gh import release_gh


def caller_version_tuple() -> tuple[int, ...] | None:
    """
    This is a workaround to get the version of the caller cli if app-builder is not called directly (but from the cli).
    Note: the cli also acts as a wrapper and puppeteer for maintaining different versions of this app and dispatching to the correct one.
    """

    py_caller = Path(sys.executable).resolve()
    app_dir = py_caller.parent.parent.parent
    if app_dir.name != "app-builder":
        return None

    version_links = list(app_dir.glob("GitHub commit *.lnk"))
    if len(version_links) != 1:
        return None
    version_link = version_links[0]

    version_str = version_link.name.split("GitHub commit v", 1)[-1].split(".lnk", 1)[0]
    version_str = version_str.split("-")[0]
    version_str_tuple = tuple(version_str.split("."))

    if not len(version_str_tuple) == 3:
        return None

    def int_able(x: Any) -> bool:
        try:
            int(x)
            return True
        except:
            return False

    version = tuple(int(i) for i in version_str_tuple if int_able(i))
    if not len(version) == 3:
        return None

    return version


@click.group(
    invoke_without_command=True,
)
@click.option(
    "-i",
    "--init",
    "bc_i",
    is_flag=True,
    help="Initialize the current git repository as an app-builder project. "
    "Deprecated. Use 'app-builder init' instead.",
)
@click.option(
    "-d",
    "--get-dependencies",
    "bc_d",
    is_flag=True,
    help="Ensure all the dependencies are set up properly. "
    "Deprecated. Use 'app-builder deps' instead.",
)
@click.option(
    "-l",
    "--local-release",
    "bc_l",
    is_flag=True,
    help="Create a release. Deprecated. Use 'app-builder release' instead.",
)
@click.option(
    "-g",
    "--github-release",
    "bc_g",
    is_flag=True,
    help="Create a release and upload it to GitHub. "
    "Deprecated. Use 'app-builder release-gh' instead.",
)
# TODO: Maybe this should be a separate CLI,
#   like `app-builder-install` or `app-builder-setup` or `app-builder-version-manager`?
@click.option(
    "--install-version",
    "bc_install_version",
    type=str,
    help="Install a specific version of app-builder.",
)
def main(
    *,
    bc_i: bool = False,
    bc_d: bool = False,
    bc_l: bool = False,
    bc_g: bool = False,
    bc_install_version: str | None = None
) -> None:
    """
    \b
     █████╗ ██████╗ ██████╗       ██████╗ ██╗   ██╗██╗██╗     ██████╗ ███████╗██████╗
    ██╔══██╗██╔══██╗██╔══██╗      ██╔══██╗██║   ██║██║██║     ██╔══██╗██╔════╝██╔══██╗
    ███████║██████╔╝██████╔╝█████╗██████╔╝██║   ██║██║██║     ██║  ██║█████╗  ██████╔╝
    ██╔══██║██╔═══╝ ██╔═══╝ ╚════╝██╔══██╗██║   ██║██║██║     ██║  ██║██╔══╝  ██╔══██╗
    ██║  ██║██║     ██║           ██████╔╝╚██████╔╝██║███████╗██████╔╝███████╗██║  ██║
    ╚═╝  ╚═╝╚═╝     ╚═╝           ╚═════╝  ╚═════╝ ╚═╝╚══════╝╚═════╝ ╚══════╝╚═╝  ╚═╝
    """
    version = caller_version_tuple()
    if version is not None and version < (0, 1, 0):
        print()
        print(
            "Error: this version requires an installation of App-Builder-v0.1.0.exe or higher"
        )
        print(
            "Please Download and install here: https://github.com/AutoActuary/app-builder/releases"
        )
        sys.exit(-1)

    if bc_i:
        from .util import init

        init()

    elif bc_d:
        from .get_dependencies import get_dependencies

        get_dependencies()

    elif bc_l:
        from .create_release import create_release

        create_release()

    elif bc_g:
        from .create_github_release import create_github_release

        create_github_release()

    elif bc_install_version:
        # This should never happen, since the `--install-version` flag is captured by the CLI wrapper.
        pass


main.add_command(init)
main.add_command(deps)
main.add_command(release)
main.add_command(release_gh)
