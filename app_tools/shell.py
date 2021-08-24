import os
import shutil
import subprocess
from contextlib import contextmanager
from pathlib import Path


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


def sh_lines(command, **kwargs)
    shell = isinstance(command, str)
    lst = subprocess.check_output(command,
                                  shell=isinstance(command, str),
                                  **kwargs).decode("utf-8").strip().split("\n")
    return [] if lst == [''] else [i.strip() for i in lst]


def sh_quiet(command):
    return subprocess.call(command,
                           shell=isinstance(command, str),
                           stderr=subprocess.DEVNULL,
                           stdout=subprocess.DEVNULL)

def copy(src, dst):
    if Path(src).is_file():
        return shutil.copy2(src, dst)
    else:
        return shutil.copytree(src, dst, dirs_exist_ok=True)
