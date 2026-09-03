from __future__ import annotations

import os
import subprocess
import sys
import unittest
from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import cast
from unittest.mock import patch
from zipfile import ZipFile

from app_builder import _runtime_launcher_support as support
from app_builder.python_runtime import (
    _install_runtime_launcher_support,
    _prepare_runtime_launchers,
)


def _entry_point_launcher(shebang: bytes) -> bytes:
    from pip._vendor.distlib.scripts import WRAPPERS

    archive_bytes = BytesIO()
    with ZipFile(archive_bytes, "w") as archive:
        archive.writestr("__main__.py", "print('hello')\n")
    wrapper = cast(bytes, WRAPPERS["t64.exe"])
    return wrapper + shebang + b"\n" + archive_bytes.getvalue()


def _write_entry_point_wheel(path: Path) -> None:
    dist_info = "relocatable_demo-1.0.dist-info"
    with ZipFile(path, "w") as wheel:
        wheel.writestr(
            "relocatable_demo/__init__.py",
            "def main():\n    print('relative launcher works')\n",
        )
        wheel.writestr(
            f"{dist_info}/METADATA",
            "Metadata-Version: 2.1\nName: relocatable-demo\nVersion: 1.0\n",
        )
        wheel.writestr(
            f"{dist_info}/WHEEL",
            "Wheel-Version: 1.0\nRoot-Is-Purelib: true\nTag: py3-none-any\n",
        )
        wheel.writestr(
            f"{dist_info}/entry_points.txt",
            "[console_scripts]\nrelocatable-demo = relocatable_demo:main\n",
        )
        wheel.writestr(f"{dist_info}/RECORD", "")


@unittest.skipUnless(os.name == "nt", "Windows launchers are Windows-only")
class TestRuntimeLauncherSupport(unittest.TestCase):
    def test_existing_launcher_is_healed_when_support_is_already_current(self) -> None:
        with TemporaryDirectory() as temp_dir_str:
            runtime = Path(temp_dir_str) / "venv"
            subprocess.run([sys.executable, "-m", "venv", str(runtime)], check=True)
            python = runtime / "Scripts" / "python.exe"
            _prepare_runtime_launchers(runtime, python)

            launcher = runtime / "Scripts" / "stale.exe"
            launcher.write_bytes(_entry_point_launcher(b'#!"C:\\old venv\\python.exe"'))
            _prepare_runtime_launchers(runtime, python)

            healed = launcher.read_bytes()
            self.assertIn(b"#!<launcher_dir>\\python.exe\n", healed)
            self.assertNotIn(b"old venv", healed)

    def test_future_pip_launcher_survives_venv_relocation(self) -> None:
        with TemporaryDirectory() as temp_dir_str:
            temp_dir = Path(temp_dir_str)
            original_venv = temp_dir / "initial venv"
            relocated_venv = temp_dir / "relocated venv"
            wheel = temp_dir / "relocatable_demo-1.0-py3-none-any.whl"
            _write_entry_point_wheel(wheel)
            subprocess.run(
                [sys.executable, "-m", "venv", str(original_venv)], check=True
            )
            _install_runtime_launcher_support(original_venv)
            original_python = original_venv / "Scripts" / "python.exe"
            subprocess.run(
                [
                    str(original_python),
                    "-m",
                    "pip",
                    "install",
                    "--disable-pip-version-check",
                    "--no-deps",
                    str(wheel),
                ],
                check=True,
                capture_output=True,
                text=True,
            )
            launcher = original_venv / "Scripts" / "relocatable-demo.exe"
            payload = launcher.read_bytes()
            self.assertIn(b"#!<launcher_dir>\\python.exe\n", payload)
            self.assertNotIn(str(original_venv).encode(), payload)

            os.replace(original_venv, relocated_venv)
            completed = subprocess.run(
                [str(relocated_venv / "Scripts" / "relocatable-demo.exe")],
                check=True,
                capture_output=True,
                text=True,
            )

            self.assertEqual("relative launcher works", completed.stdout.strip())

    def test_existing_launcher_is_repaired_without_changing_its_program(self) -> None:
        with TemporaryDirectory() as temp_dir_str:
            runtime = Path(temp_dir_str) / "venv"
            scripts = runtime / "Scripts"
            scripts.mkdir(parents=True)
            launcher = scripts / "demo.exe"
            original = _entry_point_launcher(b'#!"C:\\staging path\\python.exe"')
            launcher.write_bytes(original)

            with (
                patch.object(support, "_scripts_directory", return_value=scripts),
                patch.object(
                    support,
                    "_relative_launcher_executable",
                    return_value=r"<launcher_dir>\python.exe",
                ),
            ):
                support.heal_existing_launchers()

            healed = launcher.read_bytes()
            self.assertIn(b"#!<launcher_dir>\\python.exe\n", healed)
            self.assertNotIn(b"staging path", healed)
            with ZipFile(launcher) as archive:
                self.assertEqual(
                    "print('hello')\n", archive.read("__main__.py").decode()
                )


if __name__ == "__main__":
    unittest.main()
