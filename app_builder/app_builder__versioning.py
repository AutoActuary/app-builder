import subprocess
from contextlib import suppress

from path import Path as _Path

from .app_builder__paths import app_dir


def get_githuburl() -> str | None:
    with _Path(app_dir):
        commit = None
        with suppress(subprocess.CalledProcessError):
            commit = (
                subprocess.check_output("git rev-parse HEAD", shell=True)
                .decode("utf-8")
                .strip()
            )

        giturl = None
        with suppress(subprocess.CalledProcessError):
            giturl = (
                subprocess.check_output(
                    "git config --get remote.origin.url", shell=True
                )
                .decode("utf-8")
                .strip()
            )

        if giturl is None:
            return None

        giturl = (
            (giturl.split("@")[-1] if "@" in giturl else giturl)
            .replace(".git", "")
            .replace(":", "/")
        )
        if giturl.startswith("github.com"):
            giturl = f"https://{giturl}"

        if commit is None:
            giturl = f"{giturl}/commit"
        else:
            giturl = f"{giturl}/commit/{commit}"

    return giturl


def git_describe() -> str | None:
    """
    Get the output of `git describe --tags` which is normally useful as a version string.
    Returns None if the command fails (e.g. not a git repository, no tags, etc.)
    """
    try:
        return (
            subprocess.check_output(
                ["git", "describe", "--tags"],
                cwd=app_dir,
            )
            .decode("utf-8")
            .strip()
        )
    except subprocess.CalledProcessError:
        return None
