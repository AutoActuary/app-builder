from __future__ import annotations

import builtins
import subprocess
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

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
from app_builder_meta.legacy_0x import run_legacy_bridge
from app_builder_meta.version_cache import ManagedVersion, _cache_key, run_managed_version


class TestAppBuilderMetaDispatch(unittest.TestCase):
    def test_no_config_routes_to_current_without_importing_app_builder(self) -> None:
        with TemporaryDirectory() as temp_dir_str:
            temp_dir = Path(temp_dir_str)

            real_import = builtins.__import__

            def guarded_import(name: str, *args: object, **kwargs: object) -> object:
                if name == "app_builder" or name.startswith("app_builder."):
                    raise AssertionError(f"unexpected app_builder import: {name}")
                return real_import(name, *args, **kwargs)

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

        self.assertEqual(LegacyConfigErrorTarget(path=legacy_config), target)

    def test_current_version_routes_to_current(self) -> None:
        with TemporaryDirectory() as temp_dir_str:
            temp_dir = Path(temp_dir_str)
            (temp_dir / "app_builder.yaml").write_text(
                "app_builder_version: current\n", encoding="utf-8"
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
    def test_missing_legacy_bridge_reports_expected_path(self) -> None:
        with TemporaryDirectory() as temp_dir_str:
            install_root = Path(temp_dir_str)
            with self.assertRaisesRegex(RuntimeError, "__app_builder_0.x__"):
                run_legacy_bridge(["--help"], cwd=install_root, install_root=install_root)

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
        self.assertEqual("feature-demo", _cache_key("feature/demo"))
        self.assertEqual("unnamed-ref", _cache_key("///"))


if __name__ == "__main__":
    unittest.main()
