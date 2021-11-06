import os
import shutil
import subprocess
from pathlib import Path
from contextlib import suppress

import app_builder
from app_builder import git_revision

from locate import allow_relative_location_imports
from path import Path as _Path

allow_relative_location_imports('.')
import misc
import collections.abc
import paths

"""
Download/install python and R and other dependencies
"""

config = misc.get_config()


def create_all_dependencies():
    # implicitly run any script named "pre-dependencies.bat" or "pre-dependencies.cmd" in dedicated locations
    for scriptsdir in [".", "bin", "src", "scripts"]:
        for ext in ("bat", "cmd"):
            for script in _Path(paths.app_dir).joinpath(scriptsdir).glob(f"pre-dependencies.{ext}"):
                subprocess.call(script)

    os.makedirs(paths.app_dir.joinpath("bin"), exist_ok=True)
    shutil.copy(paths.deployment_and_release_scripts_dir.joinpath("..", "bin", "7z.exe"),
                paths.app_dir.joinpath("bin", "7z.exe"))
    shutil.copy(paths.deployment_and_release_scripts_dir.joinpath("..", "bin", "7z.dll"),
                paths.app_dir.joinpath("bin", "7z.dll"))

    # legacy support for spelling mistake "Dependancies"
    spellfix = "Dependencies" if "Dependencies" in config else "Dependancies"
    for key, value in config.get(spellfix, {}).items():

        # install python (if used)
        # add pip stuff, add logging information
        if key.lower().startswith("python"):

            misc.get_python()
            if misc.islistlike(value):
                misc.pipinstall_requirements(value)

            # Added some pip logging information
            pipversionfile = paths.temp_dir.joinpath("..\\pipfreeze.txt")
            with pipversionfile.open('w') as f:
                try:
                    pyversion = misc.sh(f'"{paths.python_bin}" --version')
                    f.write(pyversion + "\n\n")
                except Exception as e:
                    print(e)
                try:
                    pipfreeze = misc.sh(f'"{paths.python_bin}" -m pip freeze')
                    f.write(pipfreeze + "\n")
                except Exception as e:
                    print(e)

            # Delete all __pycache__ from python (+/- 40mb)
            print("Purge __pycache__ files")
            for file in paths.py_dir.rglob("*"):
                if file.name == "__pycache__" and file.is_dir():
                    shutil.rmtree(file)

        # install R (if used)
        elif key.lower() == "r":
            misc.get_r()
            if misc.islistlike(value):
                for dep in value:
                    misc.rinstall(dep)

            print("Purge any R docs and i386 files")
            if paths.rpath.joinpath('unins000.dat').is_file():
                paths.rpath.joinpath('unins000.dat').remove()

            if paths.rpath.joinpath('unins000.exe').is_file():
                paths.rpath.joinpath('unins000.exe').remove()

            shutil.rmtree(paths.rpath.joinpath('bin/i386'), ignore_errors=True)
            shutil.rmtree(paths.rpath.joinpath('doc'), ignore_errors=True)

            for libdir in paths.rpath.joinpath('library').glob("*"):
                shutil.rmtree(libdir.joinpath('libs/i386'), ignore_errors=True)
                shutil.rmtree(libdir.joinpath('doc'), ignore_errors=True)

        elif key.lower() == "pandoc" and value:
            misc.get_pandoc()

            # Delete unnecessary file
            if paths.app_dir.joinpath("bin", "pandoc", "pandoc-citeproc.exe").is_file():
                paths.app_dir.joinpath("bin", "pandoc", "pandoc-citeproc.exe").remove()

        elif key.lower() == "minipython" and value:
            misc.get_minipython()

        elif key.lower() == "julia" and (value or value == {}):
            misc.get_julia()
            if isinstance(value, dict):
                misc.juliainstall_dependencies(value)

        elif key.lower() == "mintty" and value:
            icon = None
            if isinstance(value, str):
                icon = _Path(Path(paths.app_dir, value))
            misc.get_mintty(icon)

        elif key.lower() == "deploy-scripts":
            git_revision.git_download('git@github.com:AutoActuary/deploy-scripts.git',
                                      paths.app_dir.joinpath("tools", "deploy-scripts"), str(value))

        else:
            repo = ''
            with suppress(TypeError):
                repo = str(value[0])

            if 'github.com' in repo:
                reponame = repo.split('/')[-1].split('.git')[0]
                checkout = value[1]
                repopath = paths.tools_dir.joinpath(reponame)

                git_revision.git_download(repo, repopath, checkout)

    # implicitly run any script named "post-dependencies.bat" or "post-dependencies.cmd" in dedicated locations
    for scriptsdir in [".", "bin", "src", "scripts"]:
        for ext in ("bat", "cmd"):
            for script in _Path(paths.app_dir).joinpath(scriptsdir).glob(f"post-dependencies.{ext}"):
                subprocess.call(script)


# **********************************************
# If run as a script
# **********************************************
if __name__ == "__main__":
    create_all_dependencies()
