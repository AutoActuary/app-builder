from __future__ import annotations

import subprocess
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parents[1]
BRIDGE_SOURCE = (PROJECT_ROOT / "__app_builder_0x_version_bridge__" / "src").resolve()
if str(BRIDGE_SOURCE) not in sys.path:
    sys.path.insert(0, str(BRIDGE_SOURCE))

import __app_builder_0x_version_bridge__.activate as bridge_activate
from __app_builder_0x_version_bridge__.context import legacy_repo_for_executable


def _write_legacy_cache(root: Path) -> tuple[Path, Path]:
    version_dir = root / "versions" / "1.5.0"
    executable = version_dir / "venv" / "Scripts" / "python.exe"
    executable.parent.mkdir(parents=True)
    executable.write_bytes(b"")
    (version_dir / "app-builder.cmd").write_text(
        '@call "%~dp0\\venv\\Scripts\\python.exe" '
        '"%~dp0repo\\app_builder\\main.py" %*',
        encoding="utf-8",
    )
    (version_dir / "run.log").write_text("", encoding="utf-8")
    repo = version_dir / "repo"
    (repo / "app_builder").mkdir(parents=True)
    (repo / "app_builder_meta").mkdir()
    for relative_path in (
        "app_builder/__init__.py",
        "app_builder/__main__.py",
        "app_builder/main.py",
        "app_builder_meta/__init__.py",
    ):
        (repo / relative_path).write_text("", encoding="utf-8")
    (repo / "pyproject.toml").write_text(
        '[project]\nname = "app-builder"\nversion = "1.5.0"\n',
        encoding="utf-8",
    )
    return executable, repo


class TestLegacyVersionBridge(unittest.TestCase):
    def test_recognizes_exact_legacy_version_cache(self) -> None:
        with TemporaryDirectory() as temp_dir_str:
            executable, repo = _write_legacy_cache(Path(temp_dir_str))

            resolved = legacy_repo_for_executable(executable, platform="nt")

        self.assertEqual(repo.resolve(), resolved)

    def test_rejects_temporary_or_unrecognized_layout(self) -> None:
        with TemporaryDirectory() as temp_dir_str:
            temp_dir = Path(temp_dir_str)
            executable, _ = _write_legacy_cache(temp_dir)
            version_dir = executable.parents[2]
            invalid_root = temp_dir / "assembly" / version_dir.name
            invalid_root.parent.mkdir()
            version_dir.rename(invalid_root)
            moved_executable = invalid_root / "venv" / "Scripts" / "python.exe"

            resolved = legacy_repo_for_executable(moved_executable, platform="nt")

        self.assertIsNone(resolved)

    def test_activation_places_repo_first_exactly_once(self) -> None:
        repo = Path("C:/legacy cache/versions/1.5.0/repo")
        initial_path = ["existing", str(repo), "tail"]
        with (
            patch.object(
                bridge_activate, "legacy_repo_for_executable", return_value=repo
            ),
            patch.object(sys, "path", initial_path),
        ):
            bridge_activate.activate()
            bridge_activate.activate()

            self.assertEqual(str(repo), sys.path[0])
            self.assertEqual(1, sys.path.count(str(repo)))

    def test_root_requirements_explains_legacy_compatibility(self) -> None:
        requirements = (PROJECT_ROOT / "requirements.txt").read_text(encoding="utf-8")

        self.assertIn("Compatibility-only", requirements)
        self.assertIn("app-builder 0.x launchers", requirements)
        self.assertIn("./__app_builder_0x_version_bridge__", requirements)
        self.assertNotIn("app-builder-0x-version-bridge==", requirements)

    def test_bridge_dependencies_are_derived_from_the_committed_lock(self) -> None:
        setup_source = (
            PROJECT_ROOT / "__app_builder_0x_version_bridge__" / "setup.py"
        ).read_text(encoding="utf-8")
        build_config = (
            PROJECT_ROOT / "__app_builder_0x_version_bridge__" / "pyproject.toml"
        ).read_text(encoding="utf-8")

        self.assertIn('PROJECT_ROOT / "poetry.lock"', setup_source)
        self.assertIn('requirement = f"{name}=={version}"', setup_source)
        self.assertNotIn("setuptools>=", build_config)

    def test_main_py_remains_a_direct_entrypoint(self) -> None:
        completed = subprocess.run(
            [sys.executable, str(PROJECT_ROOT / "app_builder" / "main.py"), "--help"],
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
            check=False,
        )

        self.assertEqual(0, completed.returncode, completed.stderr)
        self.assertIn("Full help:", completed.stdout)
        self.assertIn("Build and package Windows-first", completed.stdout)


if __name__ == "__main__":
    unittest.main()
