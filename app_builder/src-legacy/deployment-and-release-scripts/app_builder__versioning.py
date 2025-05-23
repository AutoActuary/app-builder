import subprocess
from contextlib import suppress

from path import Path as _Path
from locate import allow_relative_location_imports

allow_relative_location_imports(".")
import app_builder__paths


def sh(cmd):
    return subprocess.check_output(cmd, shell=True).decode("utf-8").strip()


def get_githuburl():
    with _Path(app_builder__paths.app_dir):
        commit = None
        with suppress(subprocess.CalledProcessError):
            commit = sh("git rev-parse HEAD")

        giturl = None
        with suppress(subprocess.CalledProcessError):
            giturl = sh("git config --get remote.origin.url")

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


def get_gitversion():
    with _Path(app_builder__paths.app_dir):
        try:
            return sh("git describe --tags")
        except subprocess.CalledProcessError:
            return ""
