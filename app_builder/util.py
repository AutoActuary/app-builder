import glob
import shutil
import subprocess
from pathlib import Path
from textwrap import dedent
import os
from contextlib import contextmanager
from typing import List
import tempfile
import sys


def help():
    print(dedent("""
        Usage: app-builder [Options]
        Options:
          -h, --help             Print these options
          -d, --get-dependencies Ensure all the dependencies are set up properly
          -l, --local-release    Create a local release
          -g, --github-release   Create a release and upload it to GitHub
          -i, --init             Initiate current git repo as an app-builder project             
        """))


def init():
    gitbase = None
    parts = Path(".").resolve().parts

    for i in range(len(parts)+1, 0, -1):
        d = Path("/".join(parts[0:i]))
        if len(list(d.glob(".git"))):
            gitbase = d

    if gitbase is None:
        raise RuntimeError("Run `app-builder --init` within a git repository.")

    appyaml = gitbase.joinpath("application.yaml")

    if appyaml.exists():
        raise RuntimeError(f"Run git repository already has an 'application.yaml' file in '{d}'")

    os.makedirs(dst := gitbase.joinpath("tools", "templates"), exist_ok=True)
    for i in Path(__file__).resolve().parent.joinpath("assets", "templates").glob("*"):
        shutil.copy2(i, dst.joinpath(i.name))

    with appyaml.open("w") as f:
        f.write(
            dedent(r"""
            app-builder: c372872
            
            application:
            
              # Basic information for your app 
              name: TempApp
              asciibanner: tools/templates/asciibanner.txt
              icon: tools/templates/icon.ico
              installdir: '%localappdata%\TempApp'
            
              # Pause at the end of the installation sequence  
              pause: true
            
              # Add shortcuts from `installdir` to start-menu
              startmenu:
                - tools/templates/program.cmd
              
              # Choose which files to include and exclude 
              data:
                include:
                  - '*'
                exclude:
                  - .git*
                  - tools
                  - application.yaml
                # You can use also use `rename: [[a/src, b/dst], [src2, dst2]]` to remap your file
                
            # Bundle Python/R/Julia and packages into bin/*
            dependencies:
                python:
                    # You can list the packages via pip versioning (i.e. `pyyaml~=5.3`)  
                    - pyyaml
                  
            """).strip()
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

    >>> globlist(".", [sys.executable]) #doctest: +ELLIPSIS
    [...python.exe...]
    """

    with working_directory(basedir):
        fileset = {}

        include = True
        for globlist in include_exclude_include_exclude_etc:
            for g in globlist:

                for path in glob.glob(g):
                    for file in expand_path(path):
                        if include:
                            fileset.setdefault(file, None)
                        else:
                            fileset.pop(file, None)

            include = not include

    return list(fileset)


def comparable_filename(fname):
    return os.path.abspath(fname).lower().replace("\\", "/").rstrip("/")


def create_7zip_from_include_exclude_and_rename_list(
        outpath,
        basedir,
        include_list,
        exclude_list,
        rename_list = None,
        copymode=False,
        append=False,
        sevenzip_bin="7z"
):
    r"""
    >>> with tempfile.TemporaryDirectory() as d:
    ...     with working_directory(d):
    ...         for i in ["1/i/a.txt", "1/i/b.txt", "1/ii.txt", "1/iii/c.txt", "2/i/d.txt", "2/ii/eEe.txt"]:
    ...             force_file_path(i)
    ...         create_7zip_from_include_exclude_and_rename_list(
    ...             "temp.7z",
    ...             ".",
    ...             ["*", sys.executable],
    ...             ["2/ii/e.txt"],
    ...             [[sys.executable, "blap"], ["2", "3"]],
    ...             False,
    ...             False,
    ...             Path(__file__).resolve().parent.joinpath("src-legacy", "bin", "7z.exe")
    ...         )
    """
    outpath = os.path.abspath(outpath)

    if rename_list is None:
        rename_list = []

    # Lastly, zip everything from 1:1 mapping, then from the copied non-1:1 mapping
    # https://stackoverflow.com/a/28474846
    mode = ["-mx0"] if copymode else ["-t7z", "-m0=lzma2:d1024m", "-mx=9", "-aoa", "-mfb=64", "-md=32m", "-ms=on"]

    if not append:
        try:
            os.remove(outpath)
        except FileNotFoundError:
            pass

    with working_directory(basedir):
        with tempfile.TemporaryDirectory() as stage_dir:
            filelist = globlist(".", include_list, exclude_list)
            filedict = {comparable_filename(i): i for i in filelist}

            for i, j in rename_list:
                if os.path.isabs(j):
                    raise RuntimeError(f"Can only rename to a relative path (relative to the base of the zip). Got {j}")

            for _, j in filedict.items():
                if os.path.isabs(j):
                    jtmp = comparable_filename(j) + "/"
                    matched = False
                    dst = None
                    for src, dst in rename_list:
                        if jtmp.startswith(comparable_filename(src) + "/"):
                            matched = True
                            break

                    if not matched:
                        raise RuntimeError("Although absolute filepaths may be given in the 'include' list, it needs to"
                                           f" be renamed to relative locations using a 'rename' entry. Got {j}")

            for src, dst in rename_list:
                dst_stage = Path(stage_dir).joinpath(dst)
                renerr = RuntimeError(f"Cannot rename non-included or excluded paths. Got '{src}'")

                if os.path.isfile(src):
                    os.makedirs(dst_stage.parent, exist_ok=True)
                    shutil.copy2(src, dst_stage)
                    try:
                        filedict.pop(comparable_filename(src))
                    except KeyError:
                        raise renerr

                elif os.path.isdir(src):
                    src_slash = comparable_filename(src) + "/"

                    for key, srcfile in list(filedict.items()):

                        if key.startswith(src_slash):

                            file_dst_branch = os.path.abspath(srcfile)[len(src_slash):]
                            file_dst_path = dst_stage.joinpath(file_dst_branch)

                            os.makedirs(file_dst_path.parent, exist_ok=True)
                            shutil.copy2(key, file_dst_path)
                            try:
                                filedict.pop(comparable_filename(src))
                            except KeyError:
                                raise renerr

            create_7zip_from_filelist(outpath,
                                      basedir,
                                      filedict.values(),
                                      copymode=copymode,
                                      append=append,
                                      sevenzip_bin=sevenzip_bin)

            create_7zip_from_filelist(outpath,
                                      stage_dir,
                                      os.listdir(stage_dir),
                                      copymode=copymode,
                                      append=True,
                                      sevenzip_bin=sevenzip_bin)


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
                f.write("\n".join([str(i).replace("\\", "/") for i in filelist]))

            subprocess.call([sevenzip_bin, 'a', '-y'] + mode + [str(outpath), f"@{filelist_txt}"])
