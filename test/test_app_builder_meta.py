from __future__ import annotations

import builtins
import hashlib
import os
import subprocess
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any
from unittest.mock import patch

from app_builder_meta.cache_lock import exclusive_cache_lock
from app_builder_meta.environment import get_environment

from app_builder_meta.config_probe import ConfigProbeError, read_plain_yaml_version
from app_builder_meta.dispatch import (
    CurrentInstall,
    Legacy0x,
    LegacyConfigErrorTarget,
    LegacyVersionErrorTarget,
    Managed1xVersion,
    choose_target,
    dispatch,
    run_target,
)
from app_builder_meta.legacy_0x import bridge_executable, run_legacy_bridge
from app_builder_meta.version_cache import (
    ManagedVersion,
    _cache_key,
    _resolve_source_ref,
    _run_cache_git,
    _source_file_sha256,
    default_cache_root,
    managed_version_manifests,
    remove_managed_version,
    run_managed_version,
)


class TestAppBuilderMetaDispatch(unittest.TestCase):
    def test_no_config_routes_to_current_without_importing_app_builder(self) -> None:
        with TemporaryDirectory() as temp_dir_str:
            temp_dir = Path(temp_dir_str)

            real_import = builtins.__import__

            def guarded_import(
                name: str,
                globals: dict[str, Any] | None = None,
                locals: dict[str, Any] | None = None,
                fromlist: tuple[str, ...] = (),
                level: int = 0,
            ) -> Any:
                if name == "app_builder" or name.startswith("app_builder."):
                    raise AssertionError(f"unexpected app_builder import: {name}")
                return real_import(name, globals, locals, fromlist, level)

            with patch("builtins.__import__", side_effect=guarded_import):
                target = choose_target(["--help"], temp_dir)

        self.assertEqual(CurrentInstall(argv=["--help"]), target)

    def test_explicit_0x_selector_strips_selector(self) -> None:
        with TemporaryDirectory() as temp_dir_str:
            target = choose_target(["0.x", "release"], Path(temp_dir_str))

        self.assertEqual(Legacy0x(argv=["release"]), target)

    def test_legacy_application_yaml_errors_without_auto_dispatch(self) -> None:
        with TemporaryDirectory() as temp_dir_str:
            temp_dir = Path(temp_dir_str)
            legacy_config = temp_dir / "application.yaml"
            legacy_config.write_text("app_builder: v0.20.0\n", encoding="utf-8")

            target = choose_target(["release"], temp_dir)

        self.assertEqual(LegacyConfigErrorTarget(path=legacy_config.resolve()), target)

    def test_current_version_routes_to_current(self) -> None:
        with TemporaryDirectory() as temp_dir_str:
            temp_dir = Path(temp_dir_str)
            (temp_dir / "app_builder.yaml").write_text(
                "app_builder_version: current\n", encoding="utf-8"
            )

            target = choose_target(["release"], temp_dir)

        self.assertEqual(CurrentInstall(argv=["release"]), target)

    def test_hyphenated_config_filename_is_not_a_project_config(self) -> None:
        with TemporaryDirectory() as temp_dir_str:
            temp_dir = Path(temp_dir_str)
            (temp_dir / "app-builder.yaml").write_text(
                "app_builder_version: 1.5.0\n", encoding="utf-8"
            )

            target = choose_target(["release"], temp_dir)

        self.assertEqual(CurrentInstall(argv=["release"]), target)

    def test_explicit_1x_ref_routes_to_managed_cache(self) -> None:
        with TemporaryDirectory() as temp_dir_str:
            temp_dir = Path(temp_dir_str)
            (temp_dir / "app_builder.yaml").write_text(
                "app_builder_version: v1.0.0\n", encoding="utf-8"
            )

            target = choose_target(["release"], temp_dir)

        self.assertEqual(Managed1xVersion(ref="v1.0.0", argv=["release"]), target)

    def test_cache_management_stays_in_current_outer_cli(self) -> None:
        with TemporaryDirectory() as temp_dir_str:
            temp_dir = Path(temp_dir_str)
            (temp_dir / "app_builder.yaml").write_text(
                "app_builder_version: v1.0.0\n", encoding="utf-8"
            )

            cache_target = choose_target(["cache", "path"], temp_dir)
            remove_target = choose_target(["versions", "remove", "v1.0.0"], temp_dir)

        self.assertEqual(CurrentInstall(argv=["cache", "path"]), cache_target)
        self.assertEqual(
            CurrentInstall(argv=["versions", "remove", "v1.0.0"]),
            remove_target,
        )

    def test_legacy_version_in_1x_config_errors(self) -> None:
        with TemporaryDirectory() as temp_dir_str:
            temp_dir = Path(temp_dir_str)
            (temp_dir / "app_builder.yaml").write_text(
                "app_builder_version: 0.x\n", encoding="utf-8"
            )

            target = choose_target(["release"], temp_dir)

        self.assertEqual(LegacyVersionErrorTarget(version="0.x"), target)

    def test_plain_yaml_probe_rejects_bad_yaml(self) -> None:
        with TemporaryDirectory() as temp_dir_str:
            config_path = Path(temp_dir_str) / "app_builder.yaml"
            config_path.write_text("app_builder_version: [", encoding="utf-8")

            with self.assertRaises(ConfigProbeError):
                read_plain_yaml_version(config_path)

    def test_run_target_defers_current_import_to_execution(self) -> None:
        with patch("app_builder_meta.dispatch._run_current", return_value=0) as current:
            result = run_target(CurrentInstall(argv=["--help"]), cwd=Path.cwd())

        self.assertEqual(0, result)
        current.assert_called_once_with(["--help"])

    def test_dispatch_reports_legacy_config_instruction(self) -> None:
        with TemporaryDirectory() as temp_dir_str:
            temp_dir = Path(temp_dir_str)
            (temp_dir / "application.yaml").write_text("app_builder: v0.20.0\n")

            with patch("sys.stderr") as stderr:
                result = dispatch(["release"], cwd=temp_dir)

        self.assertEqual(2, result)
        written = "".join(call.args[0] for call in stderr.write.call_args_list)
        self.assertIn("app-builder 0.x <command>", written)


class TestAppBuilderMetaExecutionAdapters(unittest.TestCase):
    def tearDown(self) -> None:
        get_environment.cache_clear()

    def test_legacy_bridge_uses_import_safe_directory_name(self) -> None:
        install_root = Path("C:/app-builder")

        self.assertEqual(
            install_root / "__app_builder_0x__" / "app-builder.exe",
            bridge_executable(install_root),
        )

    def test_missing_legacy_bridge_reports_expected_path(self) -> None:
        with TemporaryDirectory() as temp_dir_str:
            install_root = Path(temp_dir_str)
            with self.assertRaisesRegex(RuntimeError, "__app_builder_0x__"):
                run_legacy_bridge(
                    ["--help"], cwd=install_root, install_root=install_root
                )

    def test_managed_runner_preserves_cwd_and_uses_selected_venv(self) -> None:
        with TemporaryDirectory() as temp_dir_str:
            temp_dir = Path(temp_dir_str)
            repo_path = temp_dir / "repo"
            venv_python = temp_dir / "venv" / "Scripts" / "python.exe"
            repo_path.mkdir()
            venv_python.parent.mkdir(parents=True)
            venv_python.write_text("python", encoding="utf-8")
            managed = ManagedVersion(
                ref="v1.2.3",
                resolved_commit="abc123",
                root=temp_dir,
                repo_path=repo_path,
                venv_python=venv_python,
            )

            with (
                patch(
                    "app_builder_meta.version_cache.ensure_managed_version",
                    return_value=managed,
                ),
                patch("app_builder_meta.version_cache.subprocess.run") as run,
            ):
                run.return_value = subprocess.CompletedProcess(
                    args=[], returncode=7, stdout="", stderr=""
                )
                result = run_managed_version("v1.2.3", ["--help"], cwd=temp_dir)

        self.assertEqual(7, result)
        args = run.call_args.args[0]
        kwargs = run.call_args.kwargs
        self.assertEqual([str(venv_python), "-P", "-m", "app_builder", "--help"], args)
        self.assertEqual(temp_dir, kwargs["cwd"])
        self.assertIn(str(repo_path), kwargs["env"]["PYTHONPATH"])

    def test_cache_key_keeps_refs_filesystem_safe(self) -> None:
        slash_key = _cache_key("feature/demo")
        hyphen_key = _cache_key("feature-demo")
        self.assertRegex(slash_key, r"^feature-demo-[0-9a-f]{12}$")
        self.assertRegex(_cache_key("///"), r"^unnamed-ref-[0-9a-f]{12}$")
        self.assertNotEqual(slash_key, hyphen_key)

    def test_default_cache_root_is_user_local_and_overrideable(self) -> None:
        with TemporaryDirectory() as temp_dir_str:
            with patch.dict(
                "os.environ", {"APP_BUILDER_CACHE_ROOT": temp_dir_str}, clear=False
            ):
                get_environment.cache_clear()
                self.assertEqual(Path(temp_dir_str).resolve(), default_cache_root())

    def test_cache_git_handles_different_ownership_and_reports_ref_errors(self) -> None:
        with TemporaryDirectory() as temp_dir_str:
            temp_dir = Path(temp_dir_str)
            versions_root = temp_dir / "versions"
            repository = versions_root / "_source" / "repo"
            repository.mkdir(parents=True)
            subprocess.run(
                ["git", "init"], cwd=repository, check=True, capture_output=True
            )
            subprocess.run(
                ["git", "config", "user.email", "cache@example.invalid"],
                cwd=repository,
                check=True,
            )
            subprocess.run(
                ["git", "config", "user.name", "cache test"],
                cwd=repository,
                check=True,
            )
            (repository / "tracked.txt").write_text("one", encoding="utf-8")
            subprocess.run(["git", "add", "."], cwd=repository, check=True)
            subprocess.run(
                ["git", "commit", "-m", "one"],
                cwd=repository,
                check=True,
                capture_output=True,
            )
            subprocess.run(["git", "tag", "v1.0.0"], cwd=repository, check=True)
            branch = subprocess.run(
                ["git", "branch", "--show-current"],
                cwd=repository,
                check=True,
                capture_output=True,
                text=True,
            ).stdout.strip()
            subprocess.run(
                ["git", "update-ref", f"refs/remotes/origin/{branch}", "HEAD"],
                cwd=repository,
                check=True,
            )

            empty_git_config = temp_dir / "empty-gitconfig"
            empty_git_config.touch()
            with patch.dict(
                os.environ,
                {
                    "GIT_TEST_ASSUME_DIFFERENT_OWNER": "1",
                    "GIT_CONFIG_GLOBAL": str(empty_git_config),
                    "GIT_CONFIG_NOSYSTEM": "1",
                },
            ):
                untrusted = subprocess.run(
                    ["git", "status"], cwd=repository, check=False, capture_output=True
                )
                tag_commit, tag_kind = _resolve_source_ref(
                    repository, "v1.0.0", versions_root=versions_root
                )
                branch_commit, branch_kind = _resolve_source_ref(
                    repository, branch, versions_root=versions_root
                )
                staging_repo = versions_root / ".building" / "repo"
                staging_repo.parent.mkdir()
                _run_cache_git(
                    ["clone", str(repository), str(staging_repo)],
                    cwd=repository,
                    versions_root=versions_root,
                )
                _run_cache_git(
                    ["fetch", "--tags", "--prune"],
                    cwd=staging_repo,
                    versions_root=versions_root,
                    also_trust=(repository,),
                )
                _run_cache_git(
                    ["checkout", "--detach", tag_commit],
                    cwd=staging_repo,
                    versions_root=versions_root,
                )
                checked_out = _run_cache_git(
                    ["rev-parse", "HEAD"],
                    cwd=staging_repo,
                    versions_root=versions_root,
                    capture=True,
                ).stdout.strip()
                with self.assertRaises(RuntimeError) as error:
                    _resolve_source_ref(
                        repository, "missing-ref", versions_root=versions_root
                    )
                still_untrusted = subprocess.run(
                    ["git", "status"], cwd=repository, check=False, capture_output=True
                )

        self.assertNotEqual(0, untrusted.returncode)
        self.assertNotEqual(0, still_untrusted.returncode)
        self.assertIn("Git error:", str(error.exception))
        self.assertIn("fatal:", str(error.exception).lower())
        self.assertEqual("tag", tag_kind)
        self.assertEqual("branch", branch_kind)
        self.assertEqual(tag_commit, branch_commit)
        self.assertEqual(tag_commit, checked_out)

    def test_managed_dependency_lock_digest_comes_from_resolved_commit(self) -> None:
        with TemporaryDirectory() as temp_dir_str:
            temp_dir = Path(temp_dir_str)
            versions_root = temp_dir / "versions"
            repository = versions_root / "_source" / "repo"
            repository.mkdir(parents=True)
            subprocess.run(["git", "init"], cwd=repository, check=True)
            subprocess.run(
                ["git", "config", "user.email", "cache@example.invalid"],
                cwd=repository,
                check=True,
            )
            subprocess.run(
                ["git", "config", "user.name", "cache test"],
                cwd=repository,
                check=True,
            )
            lock_path = repository / "poetry.lock"
            lock_path.write_bytes(b"first lock\n")
            subprocess.run(["git", "add", "poetry.lock"], cwd=repository, check=True)
            subprocess.run(["git", "commit", "-m", "lock"], cwd=repository, check=True)
            commit = subprocess.run(
                ["git", "rev-parse", "HEAD"],
                cwd=repository,
                check=True,
                capture_output=True,
                text=True,
            ).stdout.strip()
            lock_path.write_bytes(b"uncommitted replacement\n")

            digest = _source_file_sha256(
                repository,
                commit,
                "poetry.lock",
                versions_root=versions_root,
            )

        self.assertEqual(hashlib.sha256(b"first lock\n").hexdigest(), digest)

    def test_managed_cache_can_be_listed_and_removed_by_ref(self) -> None:
        with TemporaryDirectory() as temp_dir_str:
            cache_root = Path(temp_dir_str)
            managed_root = cache_root / "versions" / _cache_key("feature/demo")
            managed_root.mkdir(parents=True)
            (managed_root / "version-manifest.json").write_text(
                '{"requested_ref":"feature/demo","resolved_commit":"abc","ref_kind":"branch"}',
                encoding="utf-8",
            )

            manifests = managed_version_manifests(cache_root=cache_root)
            removed = remove_managed_version("feature/demo", cache_root=cache_root)

        self.assertEqual("feature/demo", manifests[0]["requested_ref"])
        self.assertTrue(removed)

    def test_managed_cache_lock_rejects_concurrent_writer(self) -> None:
        with TemporaryDirectory() as temp_dir_str:
            lock_path = Path(temp_dir_str) / "versions" / ".locks" / "demo.lock"
            with exclusive_cache_lock(lock_path):
                with self.assertRaisesRegex(TimeoutError, "cache lock"):
                    with exclusive_cache_lock(lock_path, timeout_seconds=0.05):
                        self.fail("concurrent cache writer unexpectedly acquired lock")


if __name__ == "__main__":
    unittest.main()
