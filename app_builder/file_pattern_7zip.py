from util import working_directory
import tempfile
from pathlib import Path
import subprocess
import os
import glob
from typing import Optional, List, Tuple, Union
import shutil
import sys
import subprocess
import sys
import os
import re

nothing_line = re.compile(r"^(\s*\r)|(\s*\n)$")

suppress_7zip_noise = [
    re.compile(r"^7-Zip .* Copyright \(c\) 1999.* Igor Pavlov \: .*$"),
    re.compile(r"^Open archive\: .*$"),
    re.compile(r"^\-\-.*$"),
    re.compile(r"^Path \= .*$"),
    re.compile(r"^Type \= .*$"),
    re.compile(r"^Physical Size \= .*$"),
    re.compile(r"^Headers Size \= .*$"),
    re.compile(r"^Method \= .*$"),
    re.compile(r"^Solid \= .*$"),
    re.compile(r"^Blocks \= .*$"),
    re.compile(r"^Scanning the drive:.*$"),
    re.compile(r"^.* files*, .* bytes.*$"),
    re.compile(r"^Updating archive\: .*$"),
    re.compile(r"^Creating archive\: .*$"),
    re.compile(r"^Add new data to archive\: .*$"),
    re.compile(r"^ .*M Scan .*$"),
    re.compile(r"^Files read from disk\: .*$"),
    re.compile(r"^Archive size\: .*$"),
    re.compile(r"^Everything is Ok.*$"),
    re.compile(r"^  0\%.*$"),
]


def run_and_suppress_7z_noise(command, check=True, **kwargs):
    """Executes a python command with real-time output streaming and raises exceptions if check=True.

    Args:
        command (list): The Python command to execute as a list.
        check (bool): If True, raises CalledProcessError on failure.
        kwargs: Additional arguments for subprocess.Popen.

    Raises:
        subprocess.CalledProcessError: If check is True and the command fails.

    """
    # Ensure default arguments for subprocess.Popen
    kwargs.setdefault("stdout", subprocess.PIPE)
    kwargs.setdefault("stderr", subprocess.STDOUT)

    # Start the subprocess
    process = subprocess.Popen(command, **kwargs)

    # Stream the output in real time
    first_output = [True]
    nothing_lines = []
    buffer = []

    def write_buffer():
        line = (b"".join(buffer)).decode("utf-8")
        buffer.clear()

        for re_suppress in suppress_7zip_noise:
            if re.match(re_suppress, line):
                return

        if re.match(nothing_line, line):
            nothing_lines.append(line)
        else:
            if first_output[0]:
                nothing_lines.clear()

            sys.stdout.write("".join([*nothing_lines[-1:], line]))
            nothing_lines.clear()
            first_output[0] = False

    for char in iter(lambda: process.stdout.read(1), b""):
        buffer.append(char)
        if char in (b"\n", b"\r"):
            write_buffer()

    write_buffer()
    if not first_output[0] and nothing_lines:
        print()

    # Wait for the process to complete
    returncode = process.wait()

    # If check is True and the return code is non-zero, raise an exception
    if check and returncode != 0:
        raise subprocess.CalledProcessError(returncode, command)


def expand_to_all_sub_files(path: Path) -> List[Path]:
    def recursive_helper(p: Path):
        if p.is_dir():
            for i in p.glob("*"):
                yield from recursive_helper(i)
        else:
            yield p

    return list(recursive_helper(path))


def filename_as_key(fname):
    return str(Path(fname).resolve()).lower()


def globlist(basedir, *include_exclude_include_exclude_etc: List[str]) -> List[str]:
    r"""
    Build a list of files from a sequence of include and exclude glob lists. These glob lists work in sequential order
    (i.e. where the next list of glob filters takes preference over the previous ones).

    >>> with tempfile.TemporaryDirectory() as d:
    ...     with working_directory(d):
    ...         for i in ["1/i/a.txt", "1/i/b.txt", "1/ii.txt", "1/iii/c.txt", "2/i/d.txt", "2/ii/e.txt"]:
    ...             Path(i).write_text("")
    ...     [str(i) for i in globlist(d, ["*"], ["1/i", "2/*/e.txt"], ["1/i/b.txt"])]
    ['1\\ii.txt', '1\\iii\\c.txt', '2\\i\\d.txt', '1\\i\\b.txt']

    >>> globlist(".", [sys.executable]) #doctest: +ELLIPSIS
    [...python.exe...]
    """

    with working_directory(basedir):
        fileset = {}

        for i, globs in enumerate(include_exclude_include_exclude_etc):
            for g in globs:
                for path in glob.glob(g):
                    for file in expand_to_all_sub_files(Path(path)):
                        # include
                        if i % 2 == 0:
                            fileset[filename_as_key(file)] = file
                        # exclude
                        else:
                            fileset.pop(filename_as_key(file), None)

    return list(fileset.values())


def create_7zip_from_filelist(
    outpath: Path,
    basedir: Path,
    filelist: List[Path],
    copymode: bool = False,
    append: bool = False,
    sevenzip_bin: str = "7z",
    show_progress=True,
):
    """
    Use 7zip to create an archive from a list of files
    """

    # Lastly, zip everything from 1:1 mapping, then from the copied non-1:1 mapping
    # https://stackoverflow.com/a/28474846
    if copymode:
        mode = ["-mx0"]
    else:
        mode = [
            "-t7z",
            "-m0=lzma2:d1024m",
            "-mx=9",
            "-aoa",
            "-mfb=64",
            "-md=32m",
            "-ms=on",
        ]

    if not append and Path(outpath).exists():
        os.remove(outpath)

    with working_directory(basedir):
        with tempfile.TemporaryDirectory() as tmpdir:
            filelist_txt = Path(tmpdir).joinpath("ziplist.txt")
            with open(filelist_txt, "w") as f:
                f.write("\n".join([str(i).replace("\\", "/") for i in filelist]))

            run_and_suppress_7z_noise(
                [sevenzip_bin, "a", "-y"]
                + (["-bsp1"] if show_progress else [])
                + mode
                + [str(outpath), f"@{filelist_txt}"]
            )


def create_7zip_from_include_exclude_and_rename_list(
    outpath: Path,
    basedir: Path,
    include_glob_list: List[Union[str, Path]],
    exclude_glob_list: List[Union[str, Path]] = None,
    rename_list: Optional[List[Tuple[str, str]]] = None,
    copymode: bool = False,
    append: bool = False,
    sevenzip_bin: str = "7z",
    show_progress=True,
):
    r"""
    >>> with tempfile.TemporaryDirectory() as d:
    ...     with working_directory(d):
    ...         for i in ["1/i/a.txt", "1/i/b.txt", "1/ii.txt", "1/iii/c.txt", "2/i/d.txt", "2/ii/eEe.txt"]:
    ...             Path(i).write_text("")
    ...         create_7zip_from_include_exclude_and_rename_list(
    ...             Path("temp.7z"),
    ...             Path("."),
    ...             ["*", sys.executable],
    ...             ["2/ii/e.txt"],
    ...             [[sys.executable, "blap"], ["2", "3"]],
    ...             False,
    ...             False,
    ...             Path(__file__).resolve().parent.joinpath("src-legacy", "bin", "7z.exe")
    ...         )
    """
    outpath = os.path.abspath(outpath)

    exclude_glob_list = exclude_glob_list or []
    rename_list = rename_list or []

    if not append and Path(outpath).exists():
        os.remove(outpath)

    with working_directory(basedir):
        with tempfile.TemporaryDirectory() as stage_dir:
            filelist = globlist(".", include_glob_list, exclude_glob_list)
            filedict = {filename_as_key(i): i for i in filelist}

            for i, j in rename_list:
                if os.path.isabs(j):
                    raise RuntimeError(
                        f"Can only rename to a relative path (relative to the base of the zip). Got {j}"
                    )

            # If an absolute filepath exists, ensure it undergoes a rename to a relative path
            rename_keys = [filename_as_key(i) for i, _ in rename_list]
            for fpath_key, fpath in filedict.items():
                if not os.path.isabs(fpath):
                    continue

                matches = [
                    True
                    for rename_key in rename_keys
                    if (fpath_key + "/").startswith(rename_key + "/")
                ]
                if not matches:
                    raise RuntimeError(
                        "Although absolute filepaths may be given in the 'include' list, it needs to"
                        f" be renamed to a relative path using a 'rename' entry: '{fpath}'"
                    )

            # Copy "renamed" files into a temp location for 7zip to engage with seperately
            for rename_src, rename_dst in rename_list:
                rename_dst_abs = Path(stage_dir).joinpath(rename_dst)
                renerr = RuntimeError(
                    f"Cannot rename path, path is not included for archiving: '{rename_src}'"
                )

                if os.path.isfile(rename_src):
                    os.makedirs(rename_dst_abs.parent, exist_ok=True)
                    shutil.copy2(rename_src, rename_dst_abs)

                    try:
                        filedict.pop(filename_as_key(rename_src))
                    except KeyError:
                        raise renerr

                elif os.path.isdir(rename_src):
                    rename_src_key_slash = filename_as_key(rename_src) + "/"

                    for fpath_key, fpath in list(filedict.items()):

                        if fpath_key.startswith(rename_src_key_slash):

                            file_dst_relative = os.path.abspath(fpath)[
                                len(rename_src_key_slash) :
                            ]
                            file_dst_abs = rename_dst_abs.joinpath(file_dst_relative)

                            os.makedirs(file_dst_abs.parent, exist_ok=True)
                            shutil.copy2(fpath_key, file_dst_abs)

                            try:
                                filedict.pop(fpath_key, None)
                            except KeyError:
                                raise renerr

            create_7zip_from_filelist(
                outpath,
                basedir,
                list(filedict.values()),
                copymode=copymode,
                append=append,
                sevenzip_bin=sevenzip_bin,
                show_progress=show_progress,
            )

            # If rename list exists
            if flist := list(Path(stage_dir).rglob("*")):
                create_7zip_from_filelist(
                    outpath,
                    stage_dir,
                    flist,
                    copymode=copymode,
                    append=True,
                    sevenzip_bin=sevenzip_bin,
                    show_progress=show_progress,
                )
