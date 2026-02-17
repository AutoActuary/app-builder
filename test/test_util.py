import os
import shutil
import stat
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from app_builder.util import rmtree


class TestRmTree(unittest.TestCase):
    def test_1(self) -> None:

        with TemporaryDirectory() as tmp_dir_str:
            tmp_dir = Path(tmp_dir_str)

            d1 = tmp_dir.joinpath("tmp")
            d1.mkdir()

            f1 = tmp_dir.joinpath("tmp/f1")
            f1.write_text("tmp")

            os.chmod(f1, stat.S_IREAD | stat.S_IRGRP | stat.S_IROTH)

            self.assertTrue(d1.exists())
            self.assertTrue(f1.exists())

            if sys.platform == "win32":
                # On Windows, shutil.rmtree will fail, but ours will work.
                with self.assertRaises(WindowsError):
                    shutil.rmtree(d1)
                self.assertTrue(d1.exists())
                self.assertTrue(f1.exists())
                rmtree(d1)
                self.assertFalse(d1.exists())
                self.assertFalse(f1.exists())

            else:
                # On Linux, we can delete it without changing the permissions.
                shutil.rmtree(d1)
                self.assertFalse(d1.exists())
                self.assertFalse(f1.exists())
