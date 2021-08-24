import os
import shutil
import subprocess
from pathlib import Path
import fnmatch
import re
from textwrap import dedent

import sys

from locate import allow_relative_location_imports
allow_relative_location_imports(".")

import git_revision
import paths
from exec_py import exec_py
from shell import sh_lines, copy


def iglob(p, pattern):
    rule = re.compile(fnmatch.translate(pattern), re.IGNORECASE)
    return [f for f in Path(p).glob("*") if rule.match(f.name)]


def get_app_base_directory(start_dir) -> Path:
    """
    Travel up from the starting directory to find the application's base directory, pattern contains 'Application.yaml'.
    """
    d = start_dir.resolve()
    for i in range(1000):
        if len(iglob(d, "application.yaml") + iglob(d, ".git")) == 2:
            return d.resolve()

        parent = d.parent
        if parent == d:  # like "c:" == "c:"
            raise FileNotFoundError("Expected git repository with `Application.yaml` at base!")
        d = parent

    raise FileNotFoundError("Expected git repository with `Application.yaml` at base!")


def get_app_version():
    base = get_app_base_directory(Path(".").resolve())
    version = None
    with open(base.joinpath("application.yaml"), "r") as f:
        for line in f.readlines():
            line = line.split("#")[0].strip()
            if line == "":
                continue

            if ":" not in line or line.split(":")[0].strip() != "version":
                raise RuntimeError("App-tools expect all `application.yaml` files to start with `version: <version>`")
            else:
                version = line.split(':', 1)[1].strip()
                if (version[0]+version[-1]) in ('""', "''"):
                    version = version[1:-1]
                assert version != ""
                break

    return version


def ensure_app_version():
    rev = get_app_version()
    path_rev = paths.versions.joinpath(rev)

    # Maybe no work needed
    if path_rev.joinpath("run.py").is_file():
        return rev

    git_revision.git_download("https://github.com/AutoActuary/app-tools.git", paths.live_repo, rev)

    path_rev_repo = path_rev.joinpath("repo")
    path_rev_site = path_rev.joinpath("site-packages")

    shutil.rmtree(path_rev_repo, ignore_errors=True)
    os.makedirs(path_rev_repo, exist_ok=True)
    for i in paths.live_repo.glob("*"):
        if i.name == ".git":
            continue
        copy(i, path_rev_repo.joinpath(i.name))

    os.makedirs(path_rev_site, exist_ok=True)
    assert 0 == subprocess.call([sys.executable, "-m", "pip",
                                 "install",
                                 "-r", path_rev_repo.joinpath("requirements.txt"),
                                 f"--target={path_rev_site}"])

    # Inject launcher
    with open(path_rev.joinpath("run.py"), "w") as fw:
        fw.write(dedent(r"""
            from pathlib import Path
            import subprocess
            import sys
            import os
            
            this_dir = Path(__file__).resolve().parent
            site_dir = this_dir.joinpath('site-packages')
            
            sys.path.insert(0, str(site_dir))
            os.environ['PATH'] = f"{Path(sys.executable).parent};os.environ['PATH']"
            os.environ['PYTHONPATH'] = str(site_dir) + ';' + os.environ.get('PYTHONPATH', '') 
            
            sys.exit(
                subprocess.call([sys.executable, str(this_dir.joinpath("repo", "app_tools", "main.py"))]+sys.argv[1:])
            )
            """))

    return rev


def run_versioned_main():
    rev = ensure_app_version()
    exec_py(paths.versions.joinpath(rev, "run.py"))


if __name__ == "__main__":
    run_versioned_main()
