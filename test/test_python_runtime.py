from __future__ import annotations

import json
import hashlib
import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import MagicMock, patch
from zipfile import ZipFile

from click.testing import CliRunner

from app_builder.main import main
from app_builder.poetry_dependencies import DEV_GROUP, MAIN_GROUP, PoetryLock
from app_builder.python_runtime import (
    EXE_WRAP_VERSION,
    PythonEnvironmentMaterializer,
    PythonRuntimePackage,
    PythonVersionNotFoundError,
    _copy_bundled_runtime_support,
    _create_self_contained_venv,
    _download_cache_path,
    _dependency_state_matches,
    _ensure_bundled_python,
    _ensure_downloaded_file,
    _exe_wrap_launcher_matches,
    _exe_wrap_python_config,
    _extract_python_runtime_package,
    _EXE_WRAP_DIGESTS,
    _EXE_WRAP_SOURCE_MARKER,
    _install_exe_wrap_python_launchers,
    _matches_version_pattern,
    _load_python_runtime_packages,
    _load_python_index_json,
    _download_file,
    _python_source_marker_matches,
    _promote_runtime,
    _read_base_site_packages,
    _select_python_runtime_version,
    _resolve_exe_wrap_package,
    _self_contained_venv_matches,
    _self_contained_venv_python_executable,
    _venv_matches_bundled_python,
    _write_python_source_marker,
    _write_dependency_state,
    _write_base_site_packages,
    ensure_python_environments,
)
from app_builder.schema import PythonBundledOptions, PythonVenvOptions
from app_builder_meta.environment import AppBuilderEnvironment

_TEST_PYTHON_DIGEST = "sha256:" + "0" * 64


def _write_fake_python_runtime(package: ZipFile) -> None:
    for relative_path in (
        "python.exe",
        "pythonw.exe",
        "python312.dll",
        "Lib/os.py",
        "Lib/ensurepip/__init__.py",
        "Lib/venv/__init__.py",
        "Lib/tkinter/__init__.py",
        "DLLs/_tkinter.pyd",
    ):
        package.writestr(relative_path, relative_path)
    package.writestr("Lib/site-packages/pip/__init__.py", "pip")
    package.writestr("Scripts/pip.exe", "pip")


def _write_fake_exe_wrap_package(package_path: Path) -> None:
    with ZipFile(package_path, "w") as package:
        package.writestr("ExeWrap-console.exe", b"console-launcher")
        package.writestr("ExeWrap-windowed.exe", b"windowed-launcher")


class TestPythonOrgRuntimeSelection(unittest.TestCase):
    def test_atomic_runtime_promotion_replaces_complete_tree(self) -> None:
        with TemporaryDirectory() as temp_dir_str:
            runtime_root = Path(temp_dir_str) / "runtime"
            runtime_root.mkdir()
            (runtime_root / "old.txt").write_text("old", encoding="utf-8")
            staging_root = Path(temp_dir_str) / "staging"
            staging_root.mkdir()
            (staging_root / "new.txt").write_text("new", encoding="utf-8")

            _promote_runtime(staging_root, runtime_root)

            self.assertFalse((runtime_root / "old.txt").exists())
            self.assertEqual("new", (runtime_root / "new.txt").read_text())

    def test_failed_dependency_install_preserves_existing_runtime(self) -> None:
        with TemporaryDirectory() as temp_dir_str:
            project_root = Path(temp_dir_str)
            runtime_root = project_root / "bin" / "python"
            runtime_root.mkdir(parents=True)
            sentinel = runtime_root / "existing.txt"
            sentinel.write_text("still valid", encoding="utf-8")

            def build(staging_root: Path, _options: object) -> Path:
                executable = staging_root / "python" / "python.exe"
                executable.parent.mkdir(parents=True)
                executable.write_bytes(b"python")
                return executable

            with (
                patch(
                    "app_builder.python_runtime._bundled_runtime_matches",
                    return_value=False,
                ),
                patch(
                    "app_builder.python_runtime._build_bundled_runtime_at",
                    side_effect=build,
                ),
                patch("app_builder.python_runtime._ensure_pip"),
                patch(
                    "app_builder.python_runtime.install_locked_poetry_dependencies",
                    side_effect=RuntimeError("pip failed"),
                ),
                self.assertRaisesRegex(RuntimeError, "pip failed"),
            ):
                _ensure_bundled_python(
                    project_root,
                    PythonBundledOptions(path="bin/python", python_version="3.12.10"),
                    PoetryLock(packages=(), sha256="lock"),
                )

            self.assertEqual("still valid", sentinel.read_text(encoding="utf-8"))
            self.assertFalse(
                any(
                    "app-builder-building" in path.name
                    for path in runtime_root.parent.iterdir()
                )
            )

    @patch(
        "app_builder.python_runtime._python_runtime_architecture_tag", return_value="64"
    )
    @patch("app_builder.python_runtime._load_python_index_json")
    def test_reads_python_core_runtime_and_digest_from_chained_index(
        self, load_json: object, _architecture: object
    ) -> None:
        assert hasattr(load_json, "side_effect")
        load_json.side_effect = [
            {
                "versions": [
                    {
                        "company": "PythonCore",
                        "id": "pythoncore-3.12-64",
                        "tag": "3.12-64",
                        "sort-version": "3.12.10",
                        "url": "https://www.python.org/ftp/python/3.12.10/python-3.12.10-amd64.zip",
                        "hash": {"sha256": "a" * 64},
                    },
                    {
                        "company": "PythonEmbed",
                        "id": "pythonembed-3.12-64",
                        "tag": "3.12-64",
                        "sort-version": "3.12.10",
                        "url": "https://www.python.org/ftp/python/3.12.10/python-3.12.10-embeddable-amd64.zip",
                        "hash": {"sha256": "b" * 64},
                    },
                ],
                "next": "index-windows-recent.json",
            },
            {"versions": []},
        ]

        packages = _load_python_runtime_packages()

        self.assertEqual(1, len(packages))
        self.assertEqual("3.12.10", packages[0].version)
        self.assertEqual("pythoncore-3.12-64", packages[0].runtime_id)
        self.assertEqual("sha256:" + "a" * 64, packages[0].digest)

    @patch(
        "app_builder.python_runtime._python_runtime_architecture_tag", return_value="64"
    )
    @patch("app_builder.python_runtime._load_python_index_json")
    def test_excludes_free_threaded_runtime_variants(
        self, load_json: object, _architecture: object
    ) -> None:
        assert hasattr(load_json, "return_value")
        load_json.return_value = {
            "versions": [
                {
                    "company": "PythonCore",
                    "id": "pythoncore-3.13-64",
                    "tag": "3.13-64",
                    "sort-version": "3.13.7",
                    "url": "https://www.python.org/ftp/python/3.13.7/python-3.13.7-amd64.zip",
                    "hash": {"sha256": "a" * 64},
                },
                {
                    "company": "PythonCore",
                    "id": "pythoncore-3.13t-64",
                    "tag": "3.13t-64",
                    "sort-version": "3.13.7",
                    "url": "https://www.python.org/ftp/python/3.13.7/python-3.13.7t-amd64.zip",
                    "hash": {"sha256": "b" * 64},
                },
            ]
        }

        packages = _load_python_runtime_packages()

        self.assertEqual(["pythoncore-3.13-64"], [item.runtime_id for item in packages])

    @patch("app_builder.python_runtime.urllib.request.urlopen")
    def test_python_index_requests_have_bounded_timeouts_and_retries(
        self, urlopen: MagicMock
    ) -> None:
        assert hasattr(urlopen, "side_effect")
        urlopen.side_effect = TimeoutError("stalled")

        with self.assertRaisesRegex(RuntimeError, "after 3 attempts"):
            _load_python_index_json("https://www.python.org/ftp/python/index.json")

        self.assertEqual(3, urlopen.call_count)
        self.assertTrue(
            all(call.kwargs["timeout"] == 30.0 for call in urlopen.call_args_list)
        )

    def test_matches_prefix_and_wildcard_versions(self) -> None:
        self.assertTrue(_matches_version_pattern("3.12", "3.12.10"))
        self.assertTrue(_matches_version_pattern("3.12.*", "3.12.10"))
        self.assertTrue(_matches_version_pattern("3.12.10", "3.12.10.0"))
        self.assertTrue(_matches_version_pattern("3.15.0-beta", "3.15.0b4"))
        self.assertTrue(_matches_version_pattern("3.15.0-rc.2", "3.15.0rc2"))
        self.assertFalse(_matches_version_pattern("3.11", "3.12.10"))

    def test_selects_latest_stable_matching_python_version(self) -> None:
        versions = [
            "3.12.9",
            "3.12.10",
            "3.12.11a1",
            "3.13.1",
        ]

        self.assertEqual(
            "3.12.10",
            _select_python_runtime_version(versions, "3.12"),
        )

    def test_selects_latest_matching_prerelease(self) -> None:
        self.assertEqual(
            "3.15.0b10",
            _select_python_runtime_version(
                ["3.15.0b4", "3.15.0b10", "3.15.0rc1"],
                "3.15.0-beta",
            ),
        )

    def test_missing_python_version_error_suggests_same_minor_versions(self) -> None:
        with self.assertRaises(PythonVersionNotFoundError) as error:
            _select_python_runtime_version(
                ["3.11.9", "3.12.9", "3.12.10", "3.13.1"],
                "3.12.99",
            )

        self.assertIn("Python.org Windows runtime index", str(error.exception))
        self.assertIn("3.12.10", str(error.exception))
        self.assertIn("3.12.9", str(error.exception))


class TestPythonOrgRuntimeExtraction(unittest.TestCase):
    @patch("app_builder.python_runtime.urllib.request.urlopen")
    def test_downloads_have_bounded_timeouts_and_leave_no_partial_file(
        self, urlopen: MagicMock
    ) -> None:
        assert hasattr(urlopen, "side_effect")
        urlopen.side_effect = TimeoutError("stalled")
        with TemporaryDirectory() as temp_dir_str:
            destination = Path(temp_dir_str) / "runtime.zip"

            with self.assertRaisesRegex(RuntimeError, "after 3 attempts"):
                _download_file("https://example.invalid/runtime.zip", destination)

            self.assertFalse(destination.exists())
        self.assertEqual(3, urlopen.call_count)
        self.assertTrue(
            all(call.kwargs["timeout"] == 30.0 for call in urlopen.call_args_list)
        )

    def test_download_cache_path_uses_configured_content_keyed_cache(self) -> None:
        url = "https://www.python.org/ftp/python/3.12.10/python-3.12.10-amd64.zip"
        cache_root = Path("cache").resolve()
        environment = AppBuilderEnvironment(
            cache_root=cache_root,
            install_root=Path("app-builder").resolve(),
            pip_cache_dir=None,
            poetry_cache_dir=None,
        )
        with patch(
            "app_builder.python_runtime.get_environment", return_value=environment
        ):
            path = _download_cache_path(url)

        self.assertEqual(
            cache_root
            / "downloads"
            / hashlib.sha256(url.encode("utf-8")).hexdigest()[:16]
            / "python-3.12.10-amd64.zip",
            path,
        )

    def test_download_cache_hit_avoids_network_and_promotion_is_atomic(self) -> None:
        with TemporaryDirectory() as temp_dir_str:
            payload = b"complete archive"
            digest = "sha256:" + hashlib.sha256(payload).hexdigest()
            environment = AppBuilderEnvironment(
                cache_root=Path(temp_dir_str),
                install_root=Path(temp_dir_str),
                pip_cache_dir=None,
                poetry_cache_dir=None,
            )

            def download(_url: str, destination: Path) -> None:
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_bytes(payload)

            with (
                patch(
                    "app_builder.python_runtime.get_environment",
                    return_value=environment,
                ),
                patch(
                    "app_builder.python_runtime._download_file",
                    side_effect=download,
                ) as download_file,
            ):
                first = _ensure_downloaded_file(
                    "https://example.invalid/runtime.zip", digest
                )
                second = _ensure_downloaded_file(
                    "https://example.invalid/runtime.zip", digest
                )

            self.assertEqual(first, second)
            self.assertEqual(payload, first.read_bytes())
            download_file.assert_called_once()
            self.assertFalse(
                any(path.suffix == ".tmp" for path in first.parent.iterdir())
            )

    def test_failed_download_does_not_poison_cache(self) -> None:
        with TemporaryDirectory() as temp_dir_str:
            environment = AppBuilderEnvironment(
                cache_root=Path(temp_dir_str),
                install_root=Path(temp_dir_str),
                pip_cache_dir=None,
                poetry_cache_dir=None,
            )

            def fail_download(_url: str, destination: Path) -> None:
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_bytes(b"partial")
                raise RuntimeError("connection lost")

            with (
                patch(
                    "app_builder.python_runtime.get_environment",
                    return_value=environment,
                ),
                patch(
                    "app_builder.python_runtime._download_file",
                    side_effect=fail_download,
                ),
                self.assertRaisesRegex(RuntimeError, "connection lost"),
            ):
                _ensure_downloaded_file("https://example.invalid/runtime.zip")

            expected = environment.download_path("https://example.invalid/runtime.zip")
            self.assertFalse(expected.exists())
            self.assertFalse(
                expected.parent.exists()
                and any(path.suffix == ".tmp" for path in expected.parent.iterdir())
            )

    def test_digest_mismatch_does_not_poison_cache(self) -> None:
        with TemporaryDirectory() as temp_dir_str:
            environment = AppBuilderEnvironment(
                cache_root=Path(temp_dir_str),
                install_root=Path(temp_dir_str),
                pip_cache_dir=None,
                poetry_cache_dir=None,
            )

            def download(_url: str, destination: Path) -> None:
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_bytes(b"unexpected content")

            url = "https://example.invalid/runtime.zip"
            with (
                patch(
                    "app_builder.python_runtime.get_environment",
                    return_value=environment,
                ),
                patch(
                    "app_builder.python_runtime._download_file",
                    side_effect=download,
                ),
                self.assertRaisesRegex(RuntimeError, "did not match expected"),
            ):
                _ensure_downloaded_file(url, "sha256:" + "0" * 64)

            self.assertFalse(environment.download_path(url).exists())

    def test_source_marker_records_python_org_package_origin(self) -> None:
        with TemporaryDirectory() as temp_dir_str:
            python_root = Path(temp_dir_str) / "bin" / "python"
            python_root.mkdir(parents=True)

            _write_python_source_marker(
                python_root,
                PythonRuntimePackage(
                    version="3.12.10",
                    runtime_id="pythoncore-3.12-64",
                    download_url="https://www.python.org/ftp/python/3.12.10/python-3.12.10-amd64.zip",
                    digest=_TEST_PYTHON_DIGEST,
                ),
            )

            self.assertTrue(_python_source_marker_matches(python_root, "3.12"))
            self.assertTrue(_python_source_marker_matches(python_root, "3.12.10"))
            self.assertFalse(_python_source_marker_matches(python_root, "3.11"))

    def test_extracts_python_org_payload_into_bundled_python_layout(self) -> None:
        with TemporaryDirectory() as temp_dir_str:
            temp_dir = Path(temp_dir_str)
            package_path = temp_dir / "python-3.12.10-amd64.zip"
            python_root = temp_dir / "bin" / "python"

            with ZipFile(package_path, "w") as package:
                _write_fake_python_runtime(package)

            _extract_python_runtime_package(package_path, python_root)

            self.assertTrue((python_root / "python" / "python.exe").exists())
            self.assertTrue((python_root / "python" / "python312.dll").exists())
            self.assertTrue((python_root / "python" / "Lib" / "os.py").exists())
            self.assertTrue(
                (python_root / "python" / "Lib" / "tkinter" / "__init__.py").exists()
            )
            self.assertTrue((python_root / "python" / "DLLs" / "_tkinter.pyd").exists())
            self.assertTrue(
                (python_root / "Lib" / "site-packages" / "pip" / "__init__.py").exists()
            )
            self.assertFalse(
                (
                    python_root
                    / "python"
                    / "Lib"
                    / "site-packages"
                    / "pip"
                    / "__init__.py"
                ).exists()
            )
            self.assertIn(
                "include-system-site-packages = false",
                (python_root / "pyvenv.cfg").read_text(encoding="utf-8"),
            )

    def test_rejects_python_runtime_archive_paths_outside_staging(self) -> None:
        with TemporaryDirectory() as temp_dir_str:
            temp_dir = Path(temp_dir_str)
            package_path = temp_dir / "python-malicious.zip"
            python_root = temp_dir / "bin" / "python"
            escaped_path = temp_dir / "escaped.txt"

            with ZipFile(package_path, "w") as package:
                package.writestr("../escaped.txt", "must not be written")

            with self.assertRaisesRegex(RuntimeError, "unsafe archive path"):
                _extract_python_runtime_package(package_path, python_root)

            self.assertFalse(escaped_path.exists())


class TestExeWrapPythonLaunchers(unittest.TestCase):
    @patch(
        "app_builder.python_runtime._exe_wrap_platform_tag",
        return_value="windows-x64",
    )
    def test_resolves_pinned_exe_wrap_release_asset(self, _platform: object) -> None:
        package = _resolve_exe_wrap_package()

        self.assertEqual("ExeWrap-v2.1.0-windows-x64.zip", package.asset_name)
        self.assertIn("/releases/download/v2.1.0/", package.download_url)
        self.assertEqual(
            "sha256:42c64c90d6620d4942b88e56b615679a8667eaa64902444aa7b21769998936cb",
            package.digest,
        )

    def test_stamps_scripts_python_launchers_with_venv_python_targets(self) -> None:
        with TemporaryDirectory() as temp_dir_str:
            temp_dir = Path(temp_dir_str)
            package_path = temp_dir / "ExeWrap.zip"
            venv_root = temp_dir / "venv"
            _write_fake_exe_wrap_package(package_path)

            _install_exe_wrap_python_launchers(venv_root, package_path=package_path)

            python_launcher = venv_root / "Scripts" / "python.exe"
            pythonw_launcher = venv_root / "Scripts" / "pythonw.exe"
            self.assertTrue(
                _exe_wrap_launcher_matches(
                    python_launcher, _exe_wrap_python_config("python.exe")
                )
            )
            self.assertTrue(
                _exe_wrap_launcher_matches(
                    pythonw_launcher, _exe_wrap_python_config("pythonw.exe")
                )
            )
            self.assertIn(b"console-launcher", python_launcher.read_bytes())
            self.assertIn(b"windowed-launcher", pythonw_launcher.read_bytes())
            self.assertIn(b"@{args}", python_launcher.read_bytes())


class TestBundledPythonCli(unittest.TestCase):
    def test_python_command_materializes_only_bundled_runtime(self) -> None:
        with TemporaryDirectory() as temp_dir_str:
            project_root = Path(temp_dir_str)
            (project_root / ".git").mkdir()
            bundled_python = project_root / "bin" / "python" / "python" / "python.exe"
            runner = CliRunner()
            current_dir = Path.cwd()
            try:
                os.chdir(project_root)
                with (
                    patch(
                        "app_builder.main.ensure_bundled_python",
                        return_value=bundled_python,
                    ) as ensure_bundled,
                    patch("app_builder.main.ensure_python_environments") as ensure_all,
                ):
                    result = runner.invoke(main, ["python"])
            finally:
                os.chdir(current_dir)

        self.assertEqual(0, result.exit_code, result.output)
        ensure_bundled.assert_called_once_with(project_root.resolve())
        ensure_all.assert_not_called()
        self.assertIn(str(bundled_python), result.output)


class TestPoetryDependencyPlacement(unittest.TestCase):
    def test_materializer_exposes_real_bundled_and_venv_boundaries(self) -> None:
        with TemporaryDirectory() as temp_dir_str:
            project_root = Path(temp_dir_str)
            (project_root / "app_builder.yaml").write_text(
                """
python_bundled:
  path: bin/python
  python_version: 3.12.10
python_venv:
  path: venv
  python_version: 3.12.10
installer:
  name: Demo
  install_directory: "%localappdata%\\\\Demo"
""".strip(),
                encoding="utf-8",
            )
            bundled_python = project_root / "bin" / "python" / "python" / "python.exe"
            venv_python = project_root / "venv" / "Scripts" / "python.exe"

            with (
                patch(
                    "app_builder.python_runtime.ensure_poetry_lock",
                    return_value=PoetryLock(packages=()),
                ),
                patch(
                    "app_builder.python_runtime._ensure_bundled_python",
                    return_value=bundled_python,
                ) as ensure_bundled,
                patch(
                    "app_builder.python_runtime._ensure_venv",
                    return_value=venv_python,
                ) as ensure_venv,
            ):
                materializer = PythonEnvironmentMaterializer(project_root)

                self.assertEqual(
                    bundled_python,
                    materializer.materialize_bundled(),
                )
                ensure_bundled.assert_called_once()
                ensure_venv.assert_not_called()

                self.assertEqual(venv_python, materializer.materialize_venv())
                ensure_venv.assert_called_once_with(
                    project_root,
                    materializer.config.python_venv,
                    materializer.poetry_lock,
                    {DEV_GROUP},
                    bundled_root=project_root / "bin" / "python",
                )

                result = materializer.result()

        self.assertEqual(bundled_python, result.python_bundled)
        self.assertEqual(venv_python, result.python_venv)

    def test_main_group_installs_to_bundled_python_and_dev_group_to_venv(self) -> None:
        with TemporaryDirectory() as temp_dir_str:
            project_root = Path(temp_dir_str)
            (project_root / "app_builder.yaml").write_text(
                """
python_bundled:
  path: bin/python
  python_version: 3.12.10
python_venv:
  path: venv
  python_version: 3.12.10
installer:
  name: Demo
  install_directory: "%localappdata%\\\\Demo"
""".strip(),
                encoding="utf-8",
            )
            bundled_python = project_root / "bin" / "python" / "python" / "python.exe"
            venv_python = project_root / "venv" / "Scripts" / "python.exe"
            poetry_lock = PoetryLock(packages=())

            with (
                patch(
                    "app_builder.python_runtime.ensure_poetry_lock",
                    return_value=poetry_lock,
                ) as ensure_lock,
                patch(
                    "app_builder.python_runtime._ensure_bundled_python",
                    return_value=bundled_python,
                ) as ensure_bundled,
                patch(
                    "app_builder.python_runtime._ensure_venv",
                    return_value=venv_python,
                ) as ensure_venv,
            ):
                result = ensure_python_environments(project_root)

        self.assertEqual(bundled_python, result.python_bundled)
        self.assertEqual(venv_python, result.python_venv)
        ensure_lock.assert_called_once_with(project_root)
        ensure_bundled.assert_called_once_with(
            project_root,
            unittest.mock.ANY,
            poetry_lock,
        )
        ensure_venv.assert_called_once_with(
            project_root,
            unittest.mock.ANY,
            poetry_lock,
            {DEV_GROUP},
            bundled_root=project_root / "bin" / "python",
        )

    def test_venv_only_materializes_self_contained_python_for_all_groups(self) -> None:
        with TemporaryDirectory() as temp_dir_str:
            project_root = Path(temp_dir_str)
            (project_root / "app_builder.yaml").write_text(
                """
python_bundled: null
python_venv:
  path: venv
  python_version: 3.12.10
installer:
  name: Demo
  install_directory: "%localappdata%\\\\Demo"
""".strip(),
                encoding="utf-8",
            )
            venv_python = project_root / "venv" / "Scripts" / "python.exe"
            poetry_lock = PoetryLock(packages=())

            with (
                patch(
                    "app_builder.python_runtime.ensure_poetry_lock",
                    return_value=poetry_lock,
                ),
                patch(
                    "app_builder.python_runtime._ensure_venv",
                    return_value=venv_python,
                ) as ensure_venv,
            ):
                result = ensure_python_environments(project_root)

        self.assertIsNone(result.python_bundled)
        self.assertEqual(venv_python, result.python_venv)
        ensure_venv.assert_called_once_with(
            project_root,
            unittest.mock.ANY,
            poetry_lock,
            {MAIN_GROUP, DEV_GROUP},
            bundled_root=None,
        )


class TestSelfContainedVenvSupport(unittest.TestCase):
    def test_creates_self_contained_venv_from_python_org_layout(self) -> None:
        with TemporaryDirectory() as temp_dir_str:
            temp_dir = Path(temp_dir_str)
            package_path = temp_dir / "python-3.12.10-amd64.zip"
            venv_root = temp_dir / "venv"
            with ZipFile(package_path, "w") as package:
                _write_fake_python_runtime(package)

            with (
                patch(
                    "app_builder.python_runtime._resolve_python_runtime_package",
                    return_value=PythonRuntimePackage(
                        version="3.12.10",
                        runtime_id="pythoncore-3.12-64",
                        download_url="https://example.invalid/python-3.12.10-amd64.zip",
                        digest=_TEST_PYTHON_DIGEST,
                    ),
                ),
                patch(
                    "app_builder.python_runtime._ensure_downloaded_file",
                    return_value=package_path,
                ),
                patch("app_builder.python_runtime._ensure_pip") as ensure_pip,
                patch(
                    "app_builder.python_runtime._install_exe_wrap_python_launchers"
                ) as install_launchers,
            ):
                python = _create_self_contained_venv(
                    venv_root,
                    PythonVenvOptions(path="venv", python_version="3.12.10"),
                )

            self.assertEqual(venv_root / "Scripts" / "python.exe", python)
            self.assertTrue((venv_root / "python" / "python.exe").exists())
            self.assertTrue((venv_root / "python" / "pythonw.exe").exists())
            self.assertTrue((venv_root / "python" / "Lib" / "os.py").exists())
            self.assertTrue(
                (venv_root / "Lib" / "site-packages" / "pip" / "__init__.py").exists()
            )
            self.assertFalse(
                (
                    venv_root
                    / "python"
                    / "Lib"
                    / "site-packages"
                    / "pip"
                    / "__init__.py"
                ).exists()
            )
            self.assertIn(
                "home =",
                (venv_root / "pyvenv.cfg").read_text(encoding="utf-8"),
            )
            self.assertTrue(_python_source_marker_matches(venv_root, "3.12"))
            ensure_pip.assert_called_once_with(
                _self_contained_venv_python_executable(venv_root)
            )
            install_launchers.assert_called_once_with(venv_root)

    def test_self_contained_venv_validation_checks_wrappers(self) -> None:
        with TemporaryDirectory() as temp_dir_str:
            venv_root = Path(temp_dir_str) / "venv"
            real_python = _self_contained_venv_python_executable(venv_root)
            real_python.parent.mkdir(parents=True)
            real_python.write_text("python", encoding="utf-8")
            (venv_root / "Scripts").mkdir()
            (venv_root / "pyvenv.cfg").write_text(
                f"home = {(venv_root / 'python').resolve().as_posix()}\n",
                encoding="utf-8",
            )
            _write_python_source_marker(
                venv_root,
                PythonRuntimePackage(
                    version="3.12.10",
                    runtime_id="pythoncore-3.12-64",
                    download_url="https://example.invalid/python-3.12.10-amd64.zip",
                    digest=_TEST_PYTHON_DIGEST,
                ),
            )
            (venv_root / "Scripts" / "python.exe").write_bytes(
                b"base" + _exe_wrap_python_config("python.exe")
            )
            (venv_root / "Scripts" / "pythonw.exe").write_bytes(
                b"base" + _exe_wrap_python_config("pythonw.exe")
            )

            with patch("app_builder.python_runtime._python_matches", return_value=True):
                self.assertFalse(_self_contained_venv_matches(venv_root, "3.12"))

            (venv_root / "Scripts" / "python.exe").write_bytes(
                b"base"
                + b"8c0e8d4c-32af-4fd8-9c68-6a0f97efeb6a"
                + _exe_wrap_python_config("python.exe")
            )
            (venv_root / "Scripts" / "pythonw.exe").write_bytes(
                b"base"
                + b"8c0e8d4c-32af-4fd8-9c68-6a0f97efeb6a"
                + _exe_wrap_python_config("pythonw.exe")
            )
            platform_tag = "windows-x64"
            (venv_root / _EXE_WRAP_SOURCE_MARKER).write_text(
                json.dumps(
                    {
                        "version": EXE_WRAP_VERSION,
                        "asset_name": f"ExeWrap-{EXE_WRAP_VERSION}-{platform_tag}.zip",
                        "digest": _EXE_WRAP_DIGESTS[platform_tag],
                    }
                ),
                encoding="utf-8",
            )

            with (
                patch("app_builder.python_runtime._python_matches", return_value=True),
                patch(
                    "app_builder.python_runtime._exe_wrap_platform_tag",
                    return_value=platform_tag,
                ),
            ):
                self.assertTrue(_self_contained_venv_matches(venv_root, "3.12"))


class TestBundledPythonVenvSupport(unittest.TestCase):
    def test_copies_autory_style_runtime_support_files(self) -> None:
        with TemporaryDirectory() as temp_dir_str:
            temp_dir = Path(temp_dir_str)
            bundled_root = temp_dir / "bin" / "python"
            venv_root = temp_dir / "venv"

            for file_path in [
                bundled_root / "Scripts" / "pip.exe",
                bundled_root / "Scripts" / "python.exe",
                bundled_root / "Lib" / "site-packages" / "package.txt",
                bundled_root / "python" / "python.exe",
                bundled_root / "tools" / "helper.dll",
                bundled_root / "support" / "helper.dll",
            ]:
                file_path.parent.mkdir(parents=True, exist_ok=True)
                file_path.write_text("x", encoding="utf-8")
            (bundled_root / "pyvenv.cfg").write_text("x", encoding="utf-8")

            _copy_bundled_runtime_support(bundled_root, venv_root)

            self.assertTrue((venv_root / "Scripts" / "pip.exe").exists())
            self.assertTrue((venv_root / "support" / "helper.dll").exists())
            self.assertFalse((venv_root / "tools" / "helper.dll").exists())
            self.assertFalse((venv_root / "Scripts" / "python.exe").exists())
            self.assertFalse(
                (venv_root / "Lib" / "site-packages" / "package.txt").exists()
            )
            self.assertFalse((venv_root / "python" / "python.exe").exists())
            self.assertFalse((venv_root / "pyvenv.cfg").exists())

    def test_venv_validation_checks_base_python_and_site_packages(self) -> None:
        with TemporaryDirectory() as temp_dir_str:
            temp_dir = Path(temp_dir_str)
            bundled_root = temp_dir / "bin" / "python"
            venv_root = temp_dir / "venv"
            base_python = bundled_root / "python" / "python.exe"
            base_site_packages = bundled_root / "Lib" / "site-packages"

            base_python.parent.mkdir(parents=True)
            base_python.write_text("x", encoding="utf-8")
            base_site_packages.mkdir(parents=True)
            venv_root.mkdir()
            (venv_root / "pyvenv.cfg").write_text(
                f"executable = {base_python}\n",
                encoding="utf-8",
            )

            _write_base_site_packages(venv_root, base_site_packages)

            self.assertEqual(base_site_packages, _read_base_site_packages(venv_root))
            self.assertTrue(_venv_matches_bundled_python(venv_root, bundled_root))
