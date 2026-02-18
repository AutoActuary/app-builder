import fnmatch
import os
import re
import sys
import tempfile
from pathlib import Path
from typing import List

from .errors import ApplicationYamlError

installed_dir = Path(
    os.environ["LOCALAPPDATA"] if sys.platform == "win32" else "/opt",
    "autoactuary",
    "app-builder",
).resolve()

base_dir = Path(__file__).resolve().parent

repo_dir = base_dir.parent

temp_dir = Path(tempfile.gettempdir(), f"app-builder-7dfd13678769").resolve()

version_txt_path = repo_dir / "version.txt"


def set_from_base(dirname: str | Path) -> Path:
    if base_dir != installed_dir:
        return temp_dir.joinpath(dirname)
    else:
        return base_dir.joinpath(dirname)


live_repo = set_from_base("live-repo")
versions = set_from_base("versions")


def iglob(p: str | Path, pattern: str) -> List[Path]:
    rule = re.compile(fnmatch.translate(pattern), re.IGNORECASE)
    return [f for f in Path(p).glob("*") if rule.match(f.name)]


def get_app_base_directory(start_dir: Path) -> Path:
    """
    Travel up from the starting directory to find the application's base directory which contains 'application.yaml'.
    """
    d = start_dir.resolve()
    err = ApplicationYamlError(
        "Expected git repository with 'application.yaml' at base. "
        "To initiate app-builder within the current repo, use `app-builder init`."
    )
    for i in range(1000):
        if len(iglob(d, "application.yaml") + iglob(d, ".git")) == 2:
            return d.resolve()

        if d.parent == d:  # like "c:" == "c:"
            raise err

        d = d.parent

    raise err
