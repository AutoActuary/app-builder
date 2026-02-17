import fnmatch
import os
import re
import shutil
import sys
import tempfile
from pathlib import Path
from subprocess import run, call
from typing import Collection, List

from locate import append_sys_path
from packaging.version import Version

with append_sys_path("../.."):
    from app_builder import git_revision
    from app_builder import paths
    from app_builder.shell import copy
    from app_builder.util import rmtree
    from app_builder.run_and_suppress import run_and_suppress_pip


class ApplicationYamlError(Exception):
    pass


def iglob(p: str | Path, pattern: str) -> List[Path]:
    rule = re.compile(fnmatch.translate(pattern), re.IGNORECASE)
    return [f for f in Path(p).glob("*") if rule.match(f.name)]


def get_app_base_directory(start_dir: Path) -> Path:
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


def get_current_version() -> str:
    """
    Get the current version of `app-builder` from the `version.txt` file that is injected during the build process.
    If `version.txt` does not exist, return "dev" to indicate that this is a development version of app-builder.
    """
    try:
        return paths.version_txt_path.read_text().strip()
    except FileNotFoundError:
        return "dev"


def get_desired_version() -> str:
    """
    Get the desired version of `app-builder` from `application.yaml`.
    """
    base = get_app_base_directory(Path(".").resolve())
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
                    "`application.yaml` must start with `app_builder: <version>`"
                )
            version = line.split(":", 1)[1].strip()
            if (version[0] + version[-1]) in ('""', "''"):
                version = version[1:-1]
            if version:
                return version

            raise ApplicationYamlError(
                "`application.yaml` starts with `app_builder: <version>` but the version is empty"
            )

        raise FileNotFoundError("`application.yaml` not found")


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

    def copy_included_files(src: Path = src_base) -> None:
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


def ensure_app_version(version: str) -> None:
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


def version_cleanup() -> None:
    """
    Use arbitrary filter choices to not let the version directory blow up in size
    """
    vdict = {}
    for p in paths.versions.glob("*"):
        run_log = p.joinpath("run.log")

        if run_log.is_file():
            vdict[os.path.getmtime(run_log)] = p

    # Keep the last used 50 versions
    discard = sorted(list(vdict.keys()))[:-50]

    for d in discard:
        rmtree(vdict[d])


def main_arg_in(options: Collection[str]) -> bool:
    return len(sys.argv) >= 2 and sys.argv[1].lower() in options


def run_versioned_main() -> int:
    desired_version: str | None

    # Allow the user to request a specific version of `app-builder` on the command line.
    if main_arg_in(["--install-version"]):
        try:
            desired_version = sys.argv[2]
        except IndexError:
            print("Usage: app-builder --install-version <version>")
            return 255

        print(f"Install version '{desired_version}'")
        ensure_app_version(desired_version)
        return 0

    if main_arg_in(["-h", "--help", "help", "-i", "--init", "init"]):
        # It looks like the user is trying to get help or initialize a new project,
        # so just run the current version.
        # Do not install anything, and do not rely on `application.yaml`.
        desired_version = None
    elif main_arg_in(["--use-version"]):
        try:
            desired_version = sys.argv[2]
        except IndexError:
            print("Usage: app-builder --use-version <version>")
            return 255

        if desired_version == "current":
            desired_version = None
        else:
            ensure_app_version(desired_version)
    else:
        # Ensure that we have the version of `app-builder` that is specified in `application.yaml` before continuing.
        try:
            desired_version = get_desired_version()
        except FileNotFoundError:
            # `application.yaml` was not found, which means the user has not yet run `init`.
            # Continue with the current version of `app-builder`.
            desired_version = None
        except ApplicationYamlError as e:
            # `application.yaml` was found, but we could not discern the version number.
            print(e)
            return 1
        else:
            ensure_app_version(desired_version)

    if desired_version is None:
        # Use the current version.
        print(f"Using `app-builder` version: {get_current_version()}")
        interpreter = Path(sys.executable)
        log_path = paths.base_dir / "run.log"
        interpreter_args = ["-m", "app_builder"]
    else:
        # Use the specified version.
        print(f"Using `app-builder` version: {desired_version}")
        version_path = paths.versions / desired_version
        interpreter = version_path / "venv" / "Scripts" / "python.exe"
        log_path = version_path / "run.log"

        if Version(desired_version) <= Version("0.19.0"):
            # These versions need to be invoked using main.py as a script.
            interpreter_args = [version_path / "repo" / "app_builder" / "main.py"]
        else:
            # Versions newer than 0.19.0 need to be run as a module.
            interpreter_args = ["-m", "app_builder"]

    log_path.write_text("")

    exit_code = call(
        args=[
            interpreter,
            "-X",
            "utf8",
            *interpreter_args,
            *sys.argv[1:],
        ],
    )

    version_cleanup()

    return exit_code


if __name__ == "__main__":
    sys.exit(run_versioned_main())
