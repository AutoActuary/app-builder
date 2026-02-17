import os
import sys
import tempfile
from pathlib import Path

installed_dir = Path(
    os.environ["LOCALAPPDATA"] if sys.platform == "win32" else "/opt",
    "autoactuary",
    "app-builder",
).resolve()
base_dir = Path(__file__).resolve().parent
temp_dir = Path(tempfile.gettempdir(), f"app-builder-7dfd13678769").resolve()


def set_from_base(dirname: str | Path) -> Path:
    if base_dir != installed_dir:
        return temp_dir.joinpath(dirname)
    else:
        return base_dir.joinpath(dirname)


live_repo = set_from_base("live-repo")
versions = set_from_base("versions")
