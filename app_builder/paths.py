import os
from pathlib import Path
from locate import this_dir
import tempfile
import hashlib

installed_dir = Path(os.environ['LOCALAPPDATA']).joinpath("autoactuary", "app-builder").resolve()
base_dir = this_dir().parent
key = hashlib.md5(str(base_dir).lower().encode('utf-8')).hexdigest()[:10]
temp_dir = Path(tempfile.gettempdir()).joinpath(f"app-builder-{key}")


def set_from_base(dirname):
    if base_dir != installed_dir:
        return temp_dir.joinpath(dirname)
    else:
        return base_dir.joinpath(dirname)


live_repo = set_from_base("live-repo")
versions = set_from_base("versions")