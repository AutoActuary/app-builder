import os
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Optional, List, Tuple, Union, Generator, Any

from .run_and_suppress import run_and_suppress_7z
from .util import working_directory


def expand_to_all_sub_files(path: Path) -> List[Path]:
    def recursive_helper(p: Path) -> Generator[Path, None, None]:
        if p.is_dir():
            for i in p.glob("*"):
                yield from recursive_helper(i)
        else:
            yield p

    return list(recursive_helper(path))


def filename_as_key(fname: str | Path) -> str:
    return str(Path(fname).resolve()).lower()


def globlist(
    basedir: str | Path,
    *include_exclude_include_exclude_etc: List[Union[str, Path]],
) -> List[Path]:
    r"""
    Build a list of files from a sequence of include and exclude glob lists. These glob lists work in sequential order
    (i.e. where the next list of glob filters takes preference over the previous ones).
    """
    basedir = Path(basedir)

    with working_directory(basedir):
        fileset = {}
        dotdir = Path(".")

        for i, globs in enumerate(include_exclude_include_exclude_etc):
            for g in globs:
                # Avoid NotImplementedError: Non-relative patterns are unsupported
                g_path = Path(g)
                if g_path.is_absolute():
                    iterator = Path(g_path.anchor).glob(
                        str(g_path.relative_to(g_path.anchor))
                    )
                else:
                    iterator = dotdir.glob(str(g))

                for path in iterator:
                    for file in expand_to_all_sub_files(path):
                        # include
                        if i % 2 == 0:
                            fileset[filename_as_key(file)] = file
                        # exclude
                        else:
                            fileset.pop(filename_as_key(file), None)

    return [Path(i) for i in fileset.values()]


def create_7zip_from_filelist(
    outpath: Path,
    basedir: Path,
    filelist: List[Path],
    copymode: bool = False,
    append: bool = False,
    sevenzip_bin: str = "7z",
    show_progress: bool = True,
) -> None:
    """
    Use 7zip to create an archive from a list of files
    """

    basedir = Path(basedir)

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
            filelist_txt.write_text(
                "\n".join(
                    [
                        Path(i).resolve().relative_to(basedir.resolve()).as_posix()
                        for i in filelist
                    ]
                ),
                encoding="utf-8",
            )

            run_and_suppress_7z(
                [sevenzip_bin, "a", "-y"]
                + (["-bsp1"] if show_progress else [])
                + mode
                + [str(outpath), f"@{filelist_txt}"]
            )


def can_7z_read_file(filepath: str | Path) -> bool:
    """
    Returns True if the file cannot be opened for both read and write with
    zero sharing (exclusive access).
    """
    if sys.platform != "win32":
        # On non-Windows platforms, we assume that we have access.
        return True

    from win32 import win32file
    import win32con

    dwDesiredAccess = win32con.GENERIC_READ | win32con.GENERIC_WRITE
    dwShareMode = 0  # no sharing; request exclusive
    dwCreationDisposition = win32con.OPEN_EXISTING

    try:
        handle: Any = win32file.CreateFile(
            str(filepath),
            dwDesiredAccess,
            dwShareMode,
            None,
            dwCreationDisposition,
            0,
            None,
        )
        # If we get here, we could open the file exclusively.
        win32file.CloseHandle(handle)
        return True
    except Exception:
        # If CreateFile fails with a sharing-violation error,
        # it typically means the file is locked.
        return False


def create_7zip_from_include_exclude_and_rename_list(
    outpath: Path,
    basedir: Path,
    include_glob_list: List[Union[str, Path]],
    exclude_glob_list: Optional[List[Union[str, Path]]] = None,
    rename_list: Optional[List[Tuple[str, str]]] = None,
    copymode: bool = False,
    append: bool = False,
    sevenzip_bin: str = "7z",
    show_progress: bool = True,
) -> None:
    outpath = Path(os.path.abspath(outpath))

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
                        f" be renamed to a relative path using a 'rename' entry: '{str(fpath)}'"
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

                    if filedict.pop(filename_as_key(rename_src), None) is None:
                        raise renerr

                elif os.path.isdir(rename_src):
                    rename_src_key_slash = filename_as_key(rename_src) + (
                        "\\" if sys.platform == "win32" else "/"
                    )

                    for fpath_key, fpath in list(filedict.items()):

                        if fpath_key.startswith(rename_src_key_slash):

                            file_dst_relative = os.path.abspath(fpath)[
                                len(rename_src_key_slash) :
                            ]
                            file_dst_abs = rename_dst_abs.joinpath(file_dst_relative)

                            os.makedirs(file_dst_abs.parent, exist_ok=True)
                            shutil.copy2(fpath_key, file_dst_abs)

                            if filedict.pop(fpath_key, None) is None:
                                raise renerr

            # Also use renaming trick on any file that is locked for 7zip to read
            for fpath_key, fpath in list(filedict.items()):
                if not can_7z_read_file(fpath):
                    filedict.pop(fpath_key)

                    file_dst_abs = Path(
                        stage_dir, fpath.resolve().relative_to(basedir.resolve())
                    )
                    os.makedirs(file_dst_abs.parent, exist_ok=True)
                    shutil.copy2(fpath, file_dst_abs)

            create_7zip_from_filelist(
                outpath,
                basedir,
                list(filedict.values()),
                copymode=copymode,
                append=append,
                sevenzip_bin=sevenzip_bin,
                show_progress=show_progress,
            )

            renamed_file_list = [i for i in Path(stage_dir).rglob("*") if i.is_file()]
            if renamed_file_list:
                create_7zip_from_filelist(
                    outpath,
                    Path(stage_dir),
                    renamed_file_list,
                    copymode=copymode,
                    append=True,
                    sevenzip_bin=sevenzip_bin,
                    show_progress=show_progress,
                )
