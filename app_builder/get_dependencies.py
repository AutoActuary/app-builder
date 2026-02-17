import os
import shutil
import subprocess
import tempfile
import uuid
from contextlib import suppress
from itertools import chain
from pathlib import Path

from path import Path as _Path

from .app_builder__misc import (
    juliainstall_dependencies,
    get_mintty,
    islistlike,
    pipinstall_requirements,
    get_r,
    sh,
    rmtree,
    get_python,
    get_pandoc,
    get_julia,
    rinstall,
    get_config,
)
from .app_builder__paths import (
    py_dir,
    r_dir,
    temp_dir,
    python_bin,
    tools_dir,
    app_dir,
    sevenz_bin,
    sevenz_dll,
)
from .git_revision import git_download
from .run_and_suppress import run_and_suppress_pip
from .scripts import iter_scripts


def split_prog_version(s: str):
    if " " in s:
        splt = s.split(" ")
        if len(splt) != 2:
            raise ValueError(f"Invalid version string: {s}")
        return splt[0], splt[1]

    return s, None


def is_prog(s, progname):
    return s.lower() == progname.lower() or s.lower().startswith(f"{progname.lower()} ")


def get_dependencies():
    """
    Download/install python and R and other dependencies
    """

    # Find and run scripts named "pre-dependencies.bat" or "pre-dependencies.cmd"
    for script in iter_scripts(
        base_dir=app_dir,
        sub_dirs=[".", "bin", "src", "scripts"],
        extensions=["bat", "cmd"],
        names=["pre-dependencies"],
    ):
        subprocess.run(args=script, check=True)

    os.makedirs(app_dir.joinpath("bin"), exist_ok=True)
    shutil.copy(sevenz_bin, app_dir.joinpath("bin", "7z.exe"))
    shutil.copy(sevenz_dll, app_dir.joinpath("bin", "7z.dll"))

    def python_post_process():
        temp_dir.mkdir(parents=True, exist_ok=True)

        # Added some pip logging information
        pipversionfile = temp_dir.joinpath("..\\pipfreeze.txt")
        with pipversionfile.open("w") as f:
            try:
                pyversion = sh(f'"{python_bin}" --version')
                f.write(pyversion + "\n\n")
            except Exception as e:
                print(e)
            try:
                pipfreeze = sh(f'"{python_bin}" -m pip freeze')
                f.write(pipfreeze + "\n")
            except Exception as e:
                print(e)

        # Delete all __pycache__ from python (+/- 40mb)
        print("Purge __pycache__ files")
        for file in py_dir.rglob("*"):
            if file.name == "__pycache__" and file.is_dir():
                rmtree(file)

    config = get_config()
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
            get_python(version)

            # Relative to app_dir
            requirements_files_globable = [
                Path(app_dir, i) for i in value.get("requirements_files", [])
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
                        python_bin,
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
                        python_bin,
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
            get_python(version)

            if islistlike(value):
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
                            python_bin,
                            "-E",
                            "-m",
                            "pip",
                            "install",
                            "--upgrade",
                            pip,
                            "--no-warn-script-location",
                        ]
                    )

                pipinstall_requirements(value)
            python_post_process()

        # install R (if used)
        elif is_prog(key, "r"):
            _, version = split_prog_version(key)
            get_r(version)
            if islistlike(value):
                for dep in value:
                    rinstall(dep)

            print("Purge any R docs and i386 files")
            if r_dir.joinpath("unins000.dat").is_file():
                os.remove(r_dir.joinpath("unins000.dat"))

            if r_dir.joinpath("unins000.exe").is_file():
                os.remove(r_dir.joinpath("unins000.exe"))

            rmtree(r_dir.joinpath("bin/i386"), ignore_errors=True)
            rmtree(r_dir.joinpath("doc"), ignore_errors=True)

            for libdir in r_dir.joinpath("library").glob("*"):
                rmtree(libdir.joinpath("libs/i386"), ignore_errors=True)
                rmtree(libdir.joinpath("doc"), ignore_errors=True)

        elif key.lower() == "pandoc" and value:
            get_pandoc()

            # Delete unnecessary file
            if app_dir.joinpath("bin", "pandoc", "pandoc-citeproc.exe").is_file():
                os.remove(app_dir.joinpath("bin", "pandoc", "pandoc-citeproc.exe"))

        elif key.lower() == "julia" and (value or value == {}):
            get_julia()
            if isinstance(value, dict):
                juliainstall_dependencies(value)

        elif key.lower() == "mintty" and value:
            icon = None
            if isinstance(value, str):
                icon = _Path(Path(app_dir, value))
            get_mintty(icon)

        elif key.lower() == "deploy-scripts":
            git_download(
                "git@github.com:AutoActuary/deploy-scripts.git",
                app_dir.joinpath("tools", "deploy-scripts"),
                str(value),
            )

        else:
            repo = ""
            with suppress(TypeError):
                repo = str(value[0])

            if "github.com" in repo:
                reponame = repo.split("/")[-1].split(".git")[0]
                checkout = value[1]
                repopath = tools_dir.joinpath(reponame)

                git_download(repo, repopath, checkout)

    # Find and run scripts named "post-dependencies.bat" or "post-dependencies.cmd"
    for script in iter_scripts(
        base_dir=app_dir,
        sub_dirs=[".", "bin", "src", "scripts"],
        extensions=["bat", "cmd"],
        names=["post-dependencies"],
    ):
        subprocess.run(args=script, check=True)
