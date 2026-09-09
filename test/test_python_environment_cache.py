from __future__ import annotations

import io
import os
import shutil
import unittest
from concurrent.futures import ThreadPoolExecutor
from contextlib import redirect_stderr
from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
from zipfile import ZipFile

from click.testing import CliRunner

from app_builder import python_environment_cache as cache
from app_builder import python_runtime as runtime
from app_builder.build import ensure_python_environments
from app_builder.main import main
from app_builder.poetry_dependencies import PoetryLock
from app_builder.schema import PythonBundledOptions, PythonVenvOptions
from app_builder_meta.environment import _read_environment, get_environment


class TestCacheControls(unittest.TestCase):
    def tearDown(self) -> None:
        get_environment.cache_clear()

    def test_independent_opt_ins_and_subprocess_inheritance(self) -> None:
        for enabled in ("BIN", "VENV"):
            values = {f"APP_BUILDER_CACHE_PYTHON_{enabled}": " 1 "}
            environment = _read_environment(values)
            self.assertEqual(enabled == "BIN", environment.cache_python_bin)
            self.assertEqual(enabled == "VENV", environment.cache_python_venv)
            inherited = _read_environment(environment.subprocess_environment(values))
            self.assertEqual(environment.cache_python_bin, inherited.cache_python_bin)
            self.assertEqual(environment.cache_python_venv, inherited.cache_python_venv)
        for value in ("", "0"):
            self.assertFalse(
                _read_environment(
                    {"APP_BUILDER_CACHE_PYTHON_BIN": value}
                ).cache_python_bin
            )
        with self.assertRaisesRegex(ValueError, "must be 1"):
            _read_environment({"APP_BUILDER_CACHE_PYTHON_VENV": "autory-v1"})

    def test_keys_follow_inputs_and_work_without_bin_cache(self) -> None:
        environment = _read_environment({"APP_BUILDER_CACHE_PYTHON_VENV": "1"})
        options = PythonVenvOptions(python_version="3.12.10")
        bundled = PythonBundledOptions(python_version="3.12.10")
        lock = PoetryLock((), sha256="lock-a", content_hash="config")
        with patch.object(cache, "get_environment", return_value=environment):
            first = cache.runtime_cache("python-venv", options, lock, {"dev"}, bundled)
            self.assertIsNotNone(first)
            assert first is not None
            self.assertIsNone(
                cache.runtime_cache("python-bin", bundled, lock, {"main"})
            )
            variants = (
                (options, replace(lock, sha256="lock-b"), {"dev"}, bundled),
                (replace(options, python_version="3.13.2"), lock, {"dev"}, bundled),
                (options, lock, {"main", "dev"}, bundled),
                (options, lock, {"dev"}, replace(bundled, path="runtime")),
            )
            for variant in variants:
                changed = cache.runtime_cache("python-venv", *variant)
                assert changed is not None
                self.assertNotEqual(first.path, changed.path)
            repeated = cache.runtime_cache(
                "python-venv", options, lock, {"dev"}, bundled
            )
            assert repeated is not None
            self.assertEqual(first.path, repeated.path)

    def test_clear_is_scoped_and_preserves_live_environments(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            with patch.dict(
                os.environ, {"APP_BUILDER_CACHE_ROOT": str(root / "cache")}
            ):
                get_environment.cache_clear()
                for stage in cache.STAGES:
                    folder = cache.cache_root() / stage
                    folder.mkdir(parents=True)
                    (folder / "entry.7z").write_bytes(b"archive")
                live = root / "venv"
                live.mkdir()
                (live / "added.txt").write_text("developer addition")
                result = CliRunner().invoke(main, ["cache", "clear", "python-bin"])
                self.assertEqual(0, result.exit_code, result.output)
                self.assertIn("1 entries, 7 bytes", result.output)
                self.assertFalse(cache.cache_files("python-bin"))
                self.assertEqual(1, len(cache.cache_files("python-venv")))
                self.assertTrue((live / "added.txt").exists())
                self.assertNotEqual(
                    0, CliRunner().invoke(main, ["cache", "clear", "python"]).exit_code
                )
                self.assertIn(
                    "disabled", CliRunner().invoke(main, ["cache", "info"]).output
                )


@unittest.skipUnless(os.name == "nt", "Uses the vendored Windows 7-Zip executable")
class TestSnapshotOutcomes(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        environment = _read_environment(
            {"APP_BUILDER_CACHE_ROOT": str(self.root / "cache")}
        )
        patcher = patch.object(cache, "get_environment", return_value=environment)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.source = self.root / "fresh runtime"
        self.source.mkdir()
        (self.source / "pyvenv.cfg").write_text("home = original")
        (self.source / "package.txt").write_text("locked package")
        self.snapshot = cache.PythonEnvironmentCache("python-bin", "a" * 64)

    def test_roundtrip_excludes_later_hook_changes(self) -> None:
        self.snapshot.save(self.source)
        (self.source / "post-hook.txt").write_text("hook output")
        destination = self.root / "another checkout" / "runtime"
        self.assertTrue(self.snapshot.restore(destination, lambda: True))
        self.assertEqual("locked package", (destination / "package.txt").read_text())
        self.assertFalse((destination / "post-hook.txt").exists())

    def test_corruption_and_failed_probe_leave_no_partial_runtime(self) -> None:
        for corrupt in (True, False):
            with self.subTest(corrupt=corrupt):
                self.snapshot.save(self.source)
                if corrupt:
                    self.snapshot.path.write_bytes(b"broken archive")
                destination = self.root / "restored"
                output = io.StringIO()
                with redirect_stderr(output):
                    self.assertFalse(self.snapshot.restore(destination, lambda: False))
                self.assertFalse(destination.exists())
                self.assertFalse(self.snapshot.path.exists())
                self.assertIn("Rebuilding normally", output.getvalue())
                self.snapshot.save(self.source)
                self.assertTrue(self.snapshot.restore(destination, lambda: True))
                shutil.rmtree(destination)
                self.snapshot.path.unlink()

    def test_unsafe_archive_cannot_write_outside_destination(self) -> None:
        self.snapshot.path.parent.mkdir(parents=True)
        with ZipFile(self.snapshot.path, "w") as archive:
            archive.writestr("pyvenv.cfg", "home = original")
            archive.writestr("../escaped.txt", "unsafe")
        destination = self.root / "restored"
        self.assertFalse(self.snapshot.restore(destination, lambda: True))
        self.assertFalse((self.root / "escaped.txt").exists())
        self.assertFalse(destination.exists())

    def test_concurrent_capture_publishes_a_usable_archive(self) -> None:
        with ThreadPoolExecutor(max_workers=2) as workers:
            list(workers.map(lambda _: self.snapshot.save(self.source), range(2)))
        self.assertEqual([self.snapshot.path], cache.cache_files("python-bin"))
        self.assertTrue(self.snapshot.restore(self.root / "restored", lambda: True))

    def test_pruning_keeps_recent_entry_across_both_stages(self) -> None:
        older = cache.cache_root() / "python-venv" / "old.7z"
        older.parent.mkdir(parents=True)
        older.write_bytes(b"x" * 4096)
        os.utime(older, (1, 1))
        with patch.object(cache, "MAX_BYTES", 4096):
            self.snapshot.save(self.source)
        self.assertFalse(older.exists())
        self.assertTrue(self.snapshot.path.exists())

    def test_clearing_venv_refreshes_untracked_base_customization(self) -> None:
        snapshot = cache.PythonEnvironmentCache("python-venv", "b" * 64)
        venv = self.root / "fresh venv"
        venv.mkdir()
        (venv / "pyvenv.cfg").write_text("home = base")
        runtime._copy_bundled_runtime_support(self.source, venv)
        snapshot.save(venv)
        (self.source / "package.txt").write_text("base hook changed")
        restored = self.root / "restored"
        self.assertTrue(snapshot.restore(restored, lambda: True))
        self.assertEqual("locked package", (restored / "package.txt").read_text())
        cache.clear_cache("python-venv")
        runtime._copy_bundled_runtime_support(self.source, venv)
        snapshot.save(venv)
        shutil.rmtree(restored)
        self.assertTrue(snapshot.restore(restored, lambda: True))
        self.assertEqual("base hook changed", (restored / "package.txt").read_text())

    def test_hydration_preserves_hooks_and_does_not_seed_existing_environments(
        self,
    ) -> None:
        environment = _read_environment(
            {
                "APP_BUILDER_CACHE_ROOT": str(self.root / "cache"),
                "APP_BUILDER_CACHE_PYTHON_BIN": "1",
            }
        )
        lock = PoetryLock((), sha256="locked-fixture")
        hydrated = []

        def create(root: Path, options: PythonBundledOptions) -> Path:
            root.mkdir(parents=True)
            (root / "pyvenv.cfg").write_text("home = original")
            (root / "python").mkdir()
            python = root / "python/python.exe"
            python.write_bytes(b"fixture interpreter")
            hydrated.append(root)
            return python

        def install(*, python_executable: Path, **kwargs: object) -> None:
            (python_executable.parent.parent / "package.txt").write_text("installed")

        with (
            patch.object(runtime, "get_environment", return_value=environment),
            patch.object(cache, "get_environment", return_value=environment),
            patch.object(runtime, "ensure_poetry_lock", return_value=lock),
            patch.object(runtime, "_build_bundled_runtime_at", side_effect=create),
            patch.object(runtime, "_ensure_pip"),
            patch.object(
                runtime, "install_locked_poetry_dependencies", side_effect=install
            ),
            patch.object(runtime, "_prepare_runtime_launchers"),
            patch.object(
                runtime, "_python_matches", side_effect=lambda p, v: p.is_file()
            ),
            patch.object(runtime, "_python_source_marker_matches", return_value=True),
        ):
            for name in ("first", "relocated"):
                project = self.root / name
                project.mkdir()
                (project / "app_builder.yaml").write_text("""python_bundled:
  python_version: 3.12.10
python_venv: null
installer:
  name: Fixture
  install_directory: '%localappdata%/Fixture'
build_hooks:
  pre_python_bundled: [[cmd.exe, /D, /C, 'echo pre>>events.txt']]
  post_python_bundled: [[cmd.exe, /D, /C, 'echo post>>events.txt & echo patched>bin/python/post.txt']]
""")
                ensure_python_environments(project)
                self.assertEqual(
                    ["pre", "post"],
                    [
                        line.strip()
                        for line in (project / "events.txt").read_text().splitlines()
                    ],
                )
                self.assertEqual(
                    "installed", (project / "bin/python/package.txt").read_text()
                )
                self.assertTrue((project / "bin/python/post.txt").is_file())
            self.assertEqual(1, len(hydrated))
            cache.clear_cache("python-bin")
            extra = project / "bin/python/developer.txt"
            extra.write_text("keep")
            ensure_python_environments(project)
            self.assertTrue(extra.exists())
            self.assertFalse(cache.cache_files("python-bin"))
            self.assertEqual(1, len(hydrated))


if __name__ == "__main__":
    unittest.main()
