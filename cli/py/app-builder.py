import os
import shutil
from subprocess import run, call
import tempfile
from pathlib import Path
import fnmatch
import re
import time
import sys

from locate import allow_relative_location_imports

allow_relative_location_imports("../..")

from app_builder import git_revision
from app_builder import paths
from app_builder.shell import copy
from app_builder.util import help, init, rmtree
from app_builder.run_and_suppress import run_and_suppress_pip


class ApplicationYamlError(Exception):
    pass


def iglob(p, pattern):
    rule = re.compile(fnmatch.translate(pattern), re.IGNORECASE)
    return [f for f in Path(p).glob("*") if rule.match(f.name)]


def get_app_base_directory(start_dir) -> Path:
    """
    Travel up from the starting directory to find the application's base directory, pattern contains 'Application.yaml'.
    """
    d = start_dir.resolve()
    err = ApplicationYamlError(
        "Expected git repository with 'application.yaml' at base. To initiate app-builder within"
        " the current repo, use `app-builder --init`"
    )
    for i in range(1000):
        if len(iglob(d, "application.yaml") + iglob(d, ".git")) == 2:
            return d.resolve()

        if d.parent == d:  # like "c:" == "c:"
            raise err

        d = d.parent

    raise err


def get_app_version():
    base = get_app_base_directory(Path(".").resolve())
    version = None
    with open(base.joinpath("application.yaml"), "r") as f:
        for line in f.readlines():
            line = line.split("#")[0].strip()
            if line == "":
                continue

            # Allow both app-builder and app_builder for legacy reasons
            if ":" not in line or line.split(":")[0].strip().lower() not in (
                "app-builder",
                "app_builder",
            ):
                raise ApplicationYamlError(
                    "app-builder expects 'application.yaml' files to start with `app_builder: <version>`"
                )
            else:
                version = line.split(":", 1)[1].strip()
                if (version[0] + version[-1]) in ('""', "''"):
                    version = version[1:-1]
                assert version != ""
                break

    return version


def create_app_builder_based_venv(
    venv_path: Path,
) -> Path:

    base_python_exe = (
        Path(__file__).resolve().parent.parent.parent
        / "bin"
        / "python"
        / "python"
        / "python.exe"
    )

    run(
        [
            str(base_python_exe),
            "-m",
            "venv",
            str(venv_path),
            "--without-pip",
        ],
        check=True,
    )

    # Define the source directory to copy files from
    src_base = base_python_exe.parent.parent

    # Ignore files in original that will cause overwrites
    exclude_relpath_lower_strings = {
        "scripts",
        "python",
        "python.exe",
        "pyvenv.cfg",
        "lib",
    }

    def copy_included_files(src: Path = src_base):
        relpath = src.resolve().relative_to(src_base.resolve())
        if relpath.as_posix().lower() not in exclude_relpath_lower_strings:
            if src.is_dir():
                for f in src.glob("*"):
                    copy_included_files(f)
            else:
                dest = venv_path / relpath
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, dest)

    copy_included_files()

    # Load original autory's site packages in order for the venv to have access to them
    (venv_path / "Lib" / "site-packages" / "base_site_packages.pth").write_text(
        f"import site; site.addsitedir({repr((src_base / 'Lib/site-packages').as_posix())})"
    )

    return venv_path / "Scripts" / "python.exe"


def ensure_app_version(version):
    path_rev = paths.versions.joinpath(version)

    # Maybe no work needed
    if not path_rev.joinpath("app-builder.cmd").is_file():

        print(f"Requires app-builder version '{version}'")
        print(f"Git-clone and pip-install additional requirements")
        git_revision.git_download(
            "https://github.com/AutoActuary/app-builder.git", paths.live_repo, version
        )

        # Use temp directory so that we can't accidently end up half way
        with tempfile.TemporaryDirectory() as tdir_str:
            tdir = Path(tdir_str)

            tdir.joinpath("app-builder.cmd").write_text(
                r'@call "%~dp0\venv\Scripts\python.exe" "%~dp0repo\app_builder\main.py" %*'
            )

            tdir.joinpath("run.log").write_text("")

            tmp_rev_repo = tdir.joinpath("repo")
            os.makedirs(tmp_rev_repo, exist_ok=True)

            for i in paths.live_repo.glob("*"):
                if i.name == ".git":
                    continue
                copy(i, tmp_rev_repo.joinpath(i.name))

            create_app_builder_based_venv(tdir / "venv")

            run_and_suppress_pip(
                [
                    tdir / "venv" / "Scripts" / "python.exe",
                    "-m",
                    "pip",
                    "install",
                    "-r",
                    tmp_rev_repo.joinpath("requirements.txt"),
                    "--no-warn-script-location",
                    "--disable-pip-version-check",
                ]
            )

            rmtree(path_rev, ignore_errors=True)
            os.makedirs(path_rev.parent, exist_ok=True)
            shutil.copytree(tdir, path_rev)

        print(f"App-builder version '{version}' packaged at '{str(path_rev)}'")
        print()


def version_cleanup():
    """
    Use arbitrary filter choices to not let the version directory blow up in size
    """
    vdict = {}
    for i in paths.versions.glob("*"):
        run_log = i.joinpath("run.log")

        if run_log.is_file():
            vdict[os.path.getmtime(run_log)] = i

    # Keep the last used 50 versions
    discard = sorted(list(vdict.keys()))[:-50]

    for i in discard:
        rmtree(vdict[i])


def main_arg_in(options):
    return len(sys.argv) >= 2 and sys.argv[1].lower() in options


def run_versioned_main():
    try:
        if main_arg_in(["--install-version"]):
            if len(sys.argv) < 3:
                help()
                sys.exit(255)

            version = sys.argv[2]
            print(f"Install version '{version}'")
            ensure_app_version(version)
            sys.exit(0)

        else:
            version = get_app_version()
            ensure_app_version(version)

    # If something is wrong with application.yaml rather print help menu
    except ApplicationYamlError:
        if len(sys.argv) < 2 or main_arg_in(["-h", "--help"]):
            help()
            sys.exit(255)

        elif main_arg_in(["-i", "--init"]):
            init()
            sys.exit(0)

        else:
            raise

    # Leave trail
    rev_path = paths.versions.joinpath(version)

    rev_path.joinpath("run.log").write_text("")

    # Run directly
    exit_code = call(
        [
            rev_path / "venv" / "Scripts" / "python.exe",
            rev_path / "repo" / "app_builder" / "main.py",
            *sys.argv[1:],
        ],
    )

    version_cleanup()

    sys.exit(exit_code)


if __name__ == "__main__":
    run_versioned_main()
