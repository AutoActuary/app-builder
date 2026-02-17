import os
import shutil
import subprocess
from pathlib import Path
from contextlib import suppress

import uuid
import tempfile
from itertools import chain

from locate import allow_relative_location_imports
from path import Path as _Path

allow_relative_location_imports(".")
import app_builder__misc
import app_builder__paths

allow_relative_location_imports("../../..")
from app_builder import git_revision
from app_builder.run_and_suppress import run_and_suppress_pip

"""
Download/install python and R and other dependencies
"""
config = app_builder__misc.get_config()


def split_prog_version(s: str):
    if " " in s:
        splt = s.split(" ")
        if len(splt) != 2:
            raise ValueError(f"Invalid version string: {s}")
        return splt[0], splt[1]

    return s, None


def is_prog(s, progname):
    return s.lower() == progname.lower() or s.lower().startswith(f"{progname.lower()} ")


def create_all_dependencies():
    # implicitly run any script named "pre-dependencies.bat" or "pre-dependencies.cmd" in dedicated locations
    for scriptsdir in [".", "bin", "src", "scripts"]:
        for ext in ("bat", "cmd"):
            for script in (
                _Path(app_builder__paths.app_dir)
                .joinpath(scriptsdir)
                .glob(f"pre-dependencies.{ext}")
            ):
                subprocess.call(script)

    os.makedirs(app_builder__paths.app_dir.joinpath("bin"), exist_ok=True)
    shutil.copy(
        app_builder__paths.deployment_and_release_scripts_dir.joinpath(
            "..", "bin", "7z.exe"
        ),
        app_builder__paths.app_dir.joinpath("bin", "7z.exe"),
    )
    shutil.copy(
        app_builder__paths.deployment_and_release_scripts_dir.joinpath(
            "..", "bin", "7z.dll"
        ),
        app_builder__paths.app_dir.joinpath("bin", "7z.dll"),
    )

    def python_post_process():
        # Added some pip logging information
        pipversionfile = app_builder__paths.temp_dir.joinpath("..\\pipfreeze.txt")
        with pipversionfile.open("w") as f:
            try:
                pyversion = app_builder__misc.sh(
                    f'"{app_builder__paths.python_bin}" --version'
                )
                f.write(pyversion + "\n\n")
            except Exception as e:
                print(e)
            try:
                pipfreeze = app_builder__misc.sh(
                    f'"{app_builder__paths.python_bin}" -m pip freeze'
                )
                f.write(pipfreeze + "\n")
            except Exception as e:
                print(e)

        # Delete all __pycache__ from python (+/- 40mb)
        print("Purge __pycache__ files")
        for file in app_builder__paths.py_dir.rglob("*"):
            if file.name == "__pycache__" and file.is_dir():
                app_builder__misc.rmtree(file)

    for key, value in config.get("dependencies", {}).items():

        # https://github.com/AutoActuary/app-builder/issues/38
        if str(key).lower() == "python" and isinstance(value, dict):

            valid_keys = "version", "pip", "requirements", "requirements_files"
            invalid_keys = list(set(value.keys()) - set(valid_keys))
            if invalid_keys:
                raise RuntimeError(
                    f"Valid keys for `dependencies: python: <keys>` are {valid_keys}; got {invalid_keys}"
                )

            version = value.get("version", None)
            if version is not None:
                version = str(version)

            pip = value.get("pip", None)
            if pip is not None:
                pip = str(pip)

            requirements = value.get("requirements", [])
            app_builder__misc.get_python(version)

            # Relative to app_dir
            requirements_files_globable = [
                Path(app_builder__paths.app_dir, i)
                for i in value.get("requirements_files", [])
            ]
            requirements_files = []
            for file_globable in requirements_files_globable:
                lst = list(
                    Path(file_globable.anchor).glob(
                        str(file_globable.relative_to(file_globable.anchor))
                    )
                )
                requirements_files.extend(lst)
                if not lst:
                    raise FileExistsError(
                        f"No requirements_files matching '{file_globable}'"
                    )

            requirements_tmp = Path(
                tempfile.gettempdir(), f"app-builder-requirements-{uuid.uuid4()}.txt"
            ).resolve()
            requirements_tmp.write_text("\n".join(requirements), encoding="utf-8")

            if pip is not None:
                run_and_suppress_pip(
                    [
                        app_builder__paths.python_bin,
                        "-E",
                        "-m",
                        "pip",
                        "install",
                        "--upgrade",
                        f"pip=={pip}",
                        "--no-warn-script-location",
                        "--disable-pip-version-check",
                    ],
                )

            if all_requirements_files := [requirements_tmp, *requirements_files]:
                run_and_suppress_pip(
                    [
                        app_builder__paths.python_bin,
                        "-E",
                        "-m",
                        "pip",
                        "install",
                        *chain(*[["-r", f] for f in all_requirements_files]),
                        "--upgrade",
                        "--no-warn-script-location",
                        "--disable-pip-version-check",
                    ],
                )

            requirements_tmp.unlink()
            python_post_process()

        # Legacy way
        elif is_prog(key, "python"):
            _, version = split_prog_version(key)
            app_builder__misc.get_python(version)

            if app_builder__misc.islistlike(value):
                pip = None
                value_ = []
                for v in value:
                    for x in ["", "~", "=", ">", "<"]:
                        if is_prog(v, f"pip{x}"):
                            pip = v
                    if v != pip:
                        value_.append(v)

                if pip is not None:
                    subprocess.call(
                        [
                            app_builder__paths.python_bin,
                            "-E",
                            "-m",
                            "pip",
                            "install",
                            "--upgrade",
                            pip,
                            "--no-warn-script-location",
                        ]
                    )

                app_builder__misc.pipinstall_requirements(value)
            python_post_process()

        # install R (if used)
        elif is_prog(key, "r"):
            _, version = split_prog_version(key)
            app_builder__misc.get_r(version)
            if app_builder__misc.islistlike(value):
                for dep in value:
                    app_builder__misc.rinstall(dep)

            print("Purge any R docs and i386 files")
            if app_builder__paths.r_dir.joinpath("unins000.dat").is_file():
                os.remove(app_builder__paths.r_dir.joinpath("unins000.dat"))

            if app_builder__paths.r_dir.joinpath("unins000.exe").is_file():
                os.remove(app_builder__paths.r_dir.joinpath("unins000.exe"))

            app_builder__misc.rmtree(
                app_builder__paths.r_dir.joinpath("bin/i386"), ignore_errors=True
            )
            app_builder__misc.rmtree(
                app_builder__paths.r_dir.joinpath("doc"), ignore_errors=True
            )

            for libdir in app_builder__paths.r_dir.joinpath("library").glob("*"):
                app_builder__misc.rmtree(
                    libdir.joinpath("libs/i386"), ignore_errors=True
                )
                app_builder__misc.rmtree(libdir.joinpath("doc"), ignore_errors=True)

        elif key.lower() == "pandoc" and value:
            app_builder__misc.get_pandoc()

            # Delete unnecessary file
            if app_builder__paths.app_dir.joinpath(
                "bin", "pandoc", "pandoc-citeproc.exe"
            ).is_file():
                os.remove(
                    app_builder__paths.app_dir.joinpath(
                        "bin", "pandoc", "pandoc-citeproc.exe"
                    )
                )

        elif key.lower() == "julia" and (value or value == {}):
            app_builder__misc.get_julia()
            if isinstance(value, dict):
                app_builder__misc.juliainstall_dependencies(value)

        elif key.lower() == "mintty" and value:
            icon = None
            if isinstance(value, str):
                icon = _Path(Path(app_builder__paths.app_dir, value))
            app_builder__misc.get_mintty(icon)

        elif key.lower() == "deploy-scripts":
            git_revision.git_download(
                "git@github.com:AutoActuary/deploy-scripts.git",
                app_builder__paths.app_dir.joinpath("tools", "deploy-scripts"),
                str(value),
            )

        else:
            repo = ""
            with suppress(TypeError):
                repo = str(value[0])

            if "github.com" in repo:
                reponame = repo.split("/")[-1].split(".git")[0]
                checkout = value[1]
                repopath = app_builder__paths.tools_dir.joinpath(reponame)

                git_revision.git_download(repo, repopath, checkout)

    # implicitly run any script named "post-dependencies.bat" or "post-dependencies.cmd" in dedicated locations
    for scriptsdir in [".", "bin", "src", "scripts"]:
        for ext in ("bat", "cmd"):
            for script in (
                _Path(app_builder__paths.app_dir)
                .joinpath(scriptsdir)
                .glob(f"post-dependencies.{ext}")
            ):
                subprocess.call(script)


# **********************************************
# If run as a script
# **********************************************
if __name__ == "__main__":
    create_all_dependencies()
