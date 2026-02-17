import sys
import unittest
from pathlib import Path
from shutil import which
from subprocess import run
from tempfile import TemporaryDirectory

from app_builder.file_pattern_7zip import (
    create_7zip_from_include_exclude_and_rename_list,
    globlist,
)
from app_builder.util import working_directory

repo_dir = Path(__file__).resolve().parent.parent
seven_zip = (
    (repo_dir / "app_builder/src-legacy/bin/7z.exe")
    if sys.platform == "win32"
    else Path(which("7z") or "7z")
)


class TestCreate7zipFromIncludeExcludeAndRenameList(unittest.TestCase):
    def test_1(self) -> None:
        with TemporaryDirectory() as d:
            with working_directory(d):
                for i in [
                    "1/i/a.txt",
                    "1/i/b.txt",
                    "1/ii.txt",
                    "1/iii/c.txt",
                    "2/i/d.txt",
                    "2/ii/eee.txt",
                ]:
                    dst = Path(d, i)
                    dst.parent.mkdir(parents=True, exist_ok=True)
                    dst.write_text("")

                create_7zip_from_include_exclude_and_rename_list(
                    outpath=Path("temp.7z"),
                    basedir=Path("."),
                    include_glob_list=["*", sys.executable],
                    exclude_glob_list=["2/ii/e.txt"],
                    rename_list=[(sys.executable, "blap"), ("2", "3")],
                    copymode=False,
                    append=False,
                    sevenzip_bin=seven_zip.as_posix(),
                )

                # Check the created archive:
                completed = run(
                    args=[
                        seven_zip.as_posix(),
                        "l",
                        "temp.7z",
                    ],
                    check=False,
                    capture_output=True,
                    text=True,
                )

                files = []
                found_header = False
                for line in completed.stdout.splitlines():
                    if line.startswith("------------"):
                        if not found_header:
                            found_header = True
                        else:
                            break
                    elif found_header:
                        files.append(Path(line.split()[-1]).as_posix())

                self.assertEqual(
                    [
                        "1/i/a.txt",
                        "1/i/b.txt",
                        "1/ii.txt",
                        "1/iii/c.txt",
                        "3/i/d.txt",
                        "3/ii/eee.txt",
                        "blap",
                    ],
                    files,
                )


class TestGlobList(unittest.TestCase):
    def test_1(self) -> None:
        with TemporaryDirectory() as d:
            with working_directory(d):
                for i in [
                    "1/i/a.txt",
                    "1/i/b.txt",
                    "1/ii.txt",
                    "1/iii/c.txt",
                    "2/i/d.txt",
                    "2/ii/e.txt",
                ]:
                    dst = Path(d, i)
                    dst.parent.mkdir(parents=True, exist_ok=True)
                    dst.write_text("")
            result = [
                p.as_posix()
                for p in globlist(d, ["*"], ["1/i", "2/*/e.txt"], ["1/i/b.txt"])
            ]

        self.assertEqual(["1/ii.txt", "1/iii/c.txt", "2/i/d.txt", "1/i/b.txt"], result)

    def test_2(self) -> None:
        result = globlist(".", [sys.executable])
        self.assertEqual([Path(sys.executable)], result)
