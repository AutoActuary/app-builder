"""
Run tests with and without optional requirements.
"""

import sys
from subprocess import run
from typing import Sequence
from pathlib import Path
import os
import doctest
import unittest
import locate

src_dir = Path(__file__).parent / "app_builder"


def main() -> None:
    """
    Run all tests, with and without optional requirements.
    """

    run_tests()

    with locate.prepend_sys_path(src_dir):
        suite = unittest.TestSuite()
        loader = unittest.defaultTestLoader
        suite = load_doctests(loader, suite, None)
        runner = unittest.TextTestRunner(verbosity=2)
        runner.run(suite)


def run_tests() -> None:
    run(
        args=[
            sys.executable,
            "-m",
            "unittest",
        ],
        cwd=src_dir,
        check=True,
    )


def run_silently_unless_error(*, args: Sequence[str]) -> None:
    completed = run(
        args=args,
        cwd=src_dir,
        capture_output=True,
    )
    if completed.returncode != 0:
        raise RuntimeError(completed.stderr.decode())


def load_doctests(loader, tests, ignore):
    """
    Discover and load all doctests in the specified directory.
    """

    # Traverse the directory tree to find Python files
    for f in src_dir.glob("*"):
        if f.suffix == ".py":
            tests.addTests(doctest.DocTestSuite(f.with_suffix("").name))

    return tests


if __name__ == "__main__":
    main()
