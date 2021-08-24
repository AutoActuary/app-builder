import os
import shutil
import subprocess
from pathlib import Path
import fnmatch
import re
from textwrap import dedent
import time

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

            if ":" not in line or line.split(":")[0].strip().lower() != "app-builder":
                raise RuntimeError(
                    "app-builder expect all `application.yaml` files to start with `app-builder: <version>`"
                )
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

    git_revision.git_download("https://github.com/AutoActuary/app-builder.git", paths.live_repo, rev)

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
            os.environ['PATH'] = f"{Path(sys.executable).parent};{os.environ['PATH']}"
            os.environ['PYTHONPATH'] = str(site_dir) + ';' + os.environ.get('PYTHONPATH', '') 
            
            sys.exit(
                subprocess.call([sys.executable, str(this_dir.joinpath("repo", "app_builder", "main.py"))]+sys.argv[1:])
            )
            """))

    return rev


def version_cleanup():
    """
    Use arbitrary choices to not let the version directory blow up in size
    """
    vdict = {}
    for i in paths.versions.glob("*"):
        run_log = i.joinpath("run.log")

        if run_log.is_file():
            vdict[os.path.getmtime(run_log)] = i

    # sort from oldest to newest
    maybes = sorted(list(vdict.keys()))[:-10]

    # throw away items over 50 count
    throwaways = set(maybes).difference(maybes[-40:])

    # throw away leftovers OR older than a month
    for key in maybes:
        if key in throwaways or time.time() - key > 60*60*24*30:
            shutil.rmtree(vdict[key])


def run_versioned_main():
    rev = get_app_version()
    rev_path = paths.versions.joinpath(rev)

    installed = True
    if not rev_path.is_dir():
        installed = False
        print(f"Checkout app-builder version `{rev}`")
        print(f"Bottle app-builder version `{rev}` dependencies")

    ensure_app_version()

    if not installed and rev_path.is_dir():
        print(f"App-builder updated to version `{rev}`")
        print()

    # run
    exec_py(rev_path.joinpath("run.py"))

    # clean up
    with open(rev_path.joinpath("run.log"), "w") as fw:
        pass
    version_cleanup()


if __name__ == "__main__":
    run_versioned_main()
