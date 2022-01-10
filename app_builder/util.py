import subprocess
from pathlib import Path
from textwrap import dedent
import os
from contextlib import contextmanager
from typing import List
import tempfile


def help():
    print(dedent("""
        Usage: app-builder [Options]
        Options:
          -h, --help             Print these options
          -d, --get-dependencies Ensure all the dependencies are set up properly
          -l, --local-release    Create a local release
          -g, --github-release   Create a release and upload it to GitHub 
        """))


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


def expand_path(path: Path):
    """
    Expand directories to it's individual files.
    """

    path = Path(path)
    if path.is_dir():
        for i in path.glob("*"):
            yield from expand_path(i)
    else:
        yield path


def force_file_path(path):
    os.makedirs(Path(path).parent, exist_ok=True)
    if not Path(path).exists():
        with Path(path).open("w") as f:
            f.write("")


def globlist(basedir, *include_exclude_include_exclude_etc: List[str]) -> List[str]:
    r"""
    Build a list of files from a sequence of include and exclude glob lists. These glob lists work in sequential order
    (i.e. where the next list of glob filters takes preference over the previous ones).

    >>> with tempfile.TemporaryDirectory() as d:
    ...     with working_directory(d):
    ...         for i in ["1/i/a.txt", "1/i/b.txt", "1/ii.txt", "1/iii/c.txt", "2/i/d.txt", "2/ii/e.txt"]:
    ...             force_file_path(i)
    ...     [str(i) for i in globlist(d, ["*"], ["1/i", "2/*/e.txt"], ["1/i/b.txt"])]
    ['1\\ii.txt', '1\\iii\\c.txt', '2\\i\\d.txt', '1\\i\\b.txt']
    """

    with working_directory(basedir):
        fileset = {}

        include = True
        for globlist in include_exclude_include_exclude_etc:
            for glob in globlist:
                for path in Path().glob(glob):
                    for file in expand_path(path):
                        if include:
                            fileset.setdefault(file, None)
                        else:
                            fileset.pop(file, None)

            include = not include

    return list(fileset)


def create_7zip_from_filelist(
        outpath,
        basedir,
        filelist,
        copymode=False,
        append=False,
        sevenzip_bin="7z"
):
    """
    Use 7zip to create an archive from a list of files
    """

    # Lastly, zip everything from 1:1 mapping, then from the copied non-1:1 mapping
    # https://stackoverflow.com/a/28474846
    mode = ["-mx0"] if copymode else ["-t7z", "-m0=lzma2:d1024m", "-mx=9", "-aoa", "-mfb=64", "-md=32m", "-ms=on"]

    if not append:
        try:
            os.remove(outpath)
        except FileNotFoundError:
            pass

    with working_directory(basedir):
        with tempfile.TemporaryDirectory() as tmpdir:
            filelist_txt = Path(tmpdir).joinpath("ziplist.txt")
            with open(filelist_txt, "w") as f:
                f.write("\n".join([str(i) for i in filelist]))

            subprocess.call([sevenzip_bin, 'a', '-y'] + mode + [str(outpath), f"@{filelist_txt}"])