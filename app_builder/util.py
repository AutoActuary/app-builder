import glob
import shutil
import subprocess
from pathlib import Path
from textwrap import dedent
import os
import stat
from contextlib import contextmanager
from typing import List, Union, Callable
import tempfile
import sys


def help():
    print(
        dedent(
            """
        Usage: app-builder [Options]
        Options:
          -h, --help                   Print these options
          -d, --get-dependencies       Ensure all the dependencies are set up properly
          -l, --local-release          Create a local release
          -g, --github-release         Create a release and upload it to GitHub
          -i, --init                   Initiate current git repo as an app-builder project             
          --install-version <version>  Add and install app-builder version to the preinstall cache
        """
        )
    )


def init():
    gitbase = None
    parts = Path(".").resolve().parts

    for i in range(len(parts) + 1, 0, -1):
        d = Path("/".join(parts[0:i]))
        if len(list(d.glob(".git"))):
            gitbase = d

    if gitbase is None:
        raise RuntimeError("Run `app-builder --init` within a git repository.")

    appyaml = gitbase.joinpath("application.yaml")

    if appyaml.exists():
        raise RuntimeError(
            f"Git repository already has an 'application.yaml' file in '{d}'"
        )

    os.makedirs(dst := gitbase.joinpath("application-templates"), exist_ok=True)
    for i in Path(__file__).resolve().parent.joinpath("assets", "templates").glob("*"):
        shutil.copy2(i, dst.joinpath(i.name))

    with appyaml.open("w") as f:
        f.write(
            dedent(
                r"""
                app-builder: v0.2.1
                
                application:
                
                # Basic information for your app 
                name: TempApp
                asciibanner: application-templates/asciibanner.txt
                icon: application-templates/icon.ico
                installdir: '%localappdata%\TempApp'
                
                # Pause at the end of the installation sequence  
                pause: true
                
                # Add shortcuts from `installdir` to start-menu
                startmenu:
                    - application-templates/program.cmd
                
                # Choose which files to include, exclude, and rename
                data:
                    include:
                    - "*"
                    exclude:
                    - .git*
                    - tools
                    - application.yaml
                    # You can use also use `rename: [[a/src, b/dst], [src2, dst2]]` as a way to remap your file system
                
                # Bundle Python/R/Julia and packages into bin/*
                dependencies:
                python:
                    # You can list the packages via pip versioning (i.e. `pyyaml~=5.3`)  
                    - pyyaml
                  
            """
            ).strip()
        )


@contextmanager
def working_directory(path):
    """
    A context manager which changes the working directory to the given
    path, and then changes it back to its previous value on exit.
    Usage:
    > # Do something in original directory
    > with working_directory('/my/new/path'):
    >     # Do something in new directory
    > # Back to old directory
    """

    prev_cwd = os.getcwd()
    os.chdir(path)
    try:
        yield
    finally:
        os.chdir(prev_cwd)


def force_file_path(path):
    os.makedirs(Path(path).parent, exist_ok=True)
    if not Path(path).exists():
        with Path(path).open("w") as f:
            f.write("")


def rmtree(
    path: Union[str, Path], ignore_errors: bool = False, onerror: Callable = None
) -> None:
    """
    Mimicks shutil.rmtree, but add support for deleting read-only files

    >>> import tempfile
    >>> import stat
    >>> with tempfile.TemporaryDirectory() as tdir:
    ...     os.makedirs(Path(tdir, "tmp"))
    ...     with Path(tdir, "tmp", "f1").open("w") as f:
    ...         _ = f.write("tmp")
    ...     os.chmod(Path(tdir, "tmp", "f1"), stat.S_IREAD|stat.S_IRGRP|stat.S_IROTH)
    ...     try:
    ...         shutil.rmtree(Path(tdir, "tmp"))
    ...     except Exception as e:
    ...         print(e) # doctest: +ELLIPSIS
    ...     rmtree(Path(tdir, "tmp"))
    [WinError 5] Access is denied: '...f1'

    """

    def _onerror(_func: Callable, _path: Union[str, Path], _exc_info) -> None:
        # Is the error an access error ?
        try:
            os.chmod(_path, stat.S_IWUSR)
            _func(_path)
        except Exception as e:
            if ignore_errors:
                pass
            elif onerror is not None:
                onerror(_func, _path, sys.exc_info())
            else:
                raise

    return shutil.rmtree(path, False, _onerror)


def split_dos(command_line: str) -> List[str]:
    """
    Parse a command line string into individual arguments, handling whitespace, quotes,
    and escaped characters according to Windows command line parsing rules.

    This function interprets the command line string based on a subset of Windows' parsing conventions
    for executable arguments, managing cases with whitespace, escape sequences, and double quotes.

    Args:
        command_line (str): The full command line string to parse.

    Returns:
        list: A list of parsed arguments as individual strings.

    Adapted from:
        - https://web.archive.org/web/20220626225925/http://www.windowsinspired.com/how-a-windows-programs-splits-its-command-line-into-individual-arguments/
        - https://chatgpt.com/share/6731f38b-8e00-8006-8610-d9019d2e59a1
    """

    args = []
    length = len(command_line)
    i = 0

    while i < length:
        # Skip any leading whitespace
        while i < length and command_line[i] in (" ", "\t"):
            i += 1
        if i >= length:
            break

        arg = ""
        treat_special_chars = True

        while i < length:
            num_backslashes = 0

            # Count consecutive backslashes
            while i < length and command_line[i] == "\\":
                num_backslashes += 1
                i += 1

            if i < length and command_line[i] == '"':
                # Handle double quotes
                if num_backslashes % 2 == 0:
                    # Even number of backslashes before double quote
                    arg += "\\" * (num_backslashes // 2)
                    i += 1  # Skip the double quote

                    # Check for consecutive double quotes in IgnoreSpecialChars state
                    if (
                        not treat_special_chars
                        and i < length
                        and command_line[i] == '"'
                    ):
                        arg += '"'
                        i += 1  # Skip the second double quote
                    else:
                        # Toggle parser state
                        treat_special_chars = not treat_special_chars
                else:
                    # Odd number of backslashes before double quote
                    arg += "\\" * (num_backslashes // 2)
                    arg += '"'  # Escaped double quote
                    i += 1
            else:
                # Handle characters other than double quotes
                arg += "\\" * num_backslashes
                if i >= length:
                    break
                if command_line[i] in (" ", "\t") and treat_special_chars:
                    # Whitespace ends the argument in InterpretSpecialChars state
                    i += 1
                    break
                else:
                    arg += command_line[i]
                    i += 1

        args.append(arg)

    return args
