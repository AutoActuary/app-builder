from __future__ import annotations

import subprocess
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from app_builder.release_outputs import (
    describe_output,
    prepare_configured_output_locations,
    resolve_configured_outputs,
    select_publication_outputs,
    validate_output_declarations,
)
from app_builder.schema import ConfigError, ReleaseOutputSpec, load_app_builder_config
from app_builder.build import build_release


class TestReleaseOutputs(unittest.TestCase):
    def test_static_output_errors_fail_before_dependency_or_hook_execution(
        self,
    ) -> None:
        with TemporaryDirectory() as temp_dir_str:
            project_root = Path(temp_dir_str)
            subprocess.run(
                ["git", "init"], cwd=project_root, check=True, capture_output=True
            )
            (project_root / "app_builder.yaml").write_text(
                """
installer:
  name: Demo
  install_directory: "%LOCALAPPDATA%\\\\Demo"
outputs:
  - name: 9-invalid
    pattern: "*.exe"
""".strip(),
                encoding="utf-8",
            )

            with (
                patch("app_builder.build._run_dependency_stages") as deps,
                patch("app_builder.build.run_hook_commands") as hooks,
                self.assertRaisesRegex(ConfigError, "beginning with a letter"),
            ):
                build_release(project_root, version="1.0.0")

            deps.assert_not_called()
            hooks.assert_not_called()

    def test_declaration_validation_rejects_unknown_publication_names(self) -> None:
        with self.assertRaisesRegex(ConfigError, "unknown output"):
            validate_output_declarations([], ["missing"])

        with self.assertRaisesRegex(ConfigError, "unknown output"):
            load_app_builder_config(
                {
                    "installer": {
                        "name": "Demo",
                        "install_directory": r"%LOCALAPPDATA%\Demo",
                    },
                    "publications": {"github": {"outputs": ["missing"]}},
                }
            )

    def test_prepares_named_outputs_by_removing_only_stale_candidates(self) -> None:
        with TemporaryDirectory() as temp_dir_str:
            dist = Path(temp_dir_str) / "dist"
            wheels = dist / "wheels"
            wheels.mkdir(parents=True)
            stale = wheels / "demo.whl"
            unrelated = dist / "keep.txt"
            protected = dist / "demo-installer.exe"
            stale.write_bytes(b"stale")
            unrelated.write_bytes(b"keep")
            protected.write_bytes(b"installer")

            removed = prepare_configured_output_locations(
                dist,
                [ReleaseOutputSpec(name="wheels", pattern="wheels/*.whl")],
                protected_paths=(protected,),
            )

            self.assertEqual((stale.resolve(),), removed)
            self.assertFalse(stale.exists())
            self.assertTrue(unrelated.exists())
            self.assertTrue(protected.exists())

            with self.assertRaisesRegex(ConfigError, "protected built-in"):
                prepare_configured_output_locations(
                    dist,
                    [
                        ReleaseOutputSpec(
                            name="signed-installer", pattern="demo-installer.exe"
                        )
                    ],
                    protected_paths=(protected,),
                )

    def test_resolves_a_deterministic_named_collection_inside_dist(self) -> None:
        with TemporaryDirectory() as temp_dir_str:
            dist = Path(temp_dir_str) / "dist"
            wheels = dist / "wheels"
            wheels.mkdir(parents=True)
            second = wheels / "demo-b.whl"
            first = wheels / "demo-a.whl"
            second.write_bytes(b"second")
            first.write_bytes(b"first")

            outputs = resolve_configured_outputs(
                dist,
                [
                    ReleaseOutputSpec(
                        name="wheels",
                        pattern="wheels/*.whl",
                        min_matches=1,
                        max_matches=None,
                    )
                ],
                occupied_paths=(),
            )

        self.assertEqual(
            (("wheels", first.resolve()), ("wheels", second.resolve())), outputs
        )

    def test_rejects_unsafe_broad_or_unsatisfied_pickups(self) -> None:
        with TemporaryDirectory() as temp_dir_str:
            dist = Path(temp_dir_str) / "dist"
            dist.mkdir()
            for pattern, error in (
                ("../*.exe", "safe path"),
                ("**/*.exe", "safe path"),
                ("*/asset.exe", "wildcards are allowed only"),
                ("missing/*.exe", "matched 0 files"),
            ):
                with self.subTest(pattern=pattern):
                    with self.assertRaisesRegex(ConfigError, error):
                        resolve_configured_outputs(
                            dist,
                            [ReleaseOutputSpec(name="extra", pattern=pattern)],
                            occupied_paths=(),
                        )

    def test_rejects_reserved_names_path_collisions_and_match_overflow(self) -> None:
        with TemporaryDirectory() as temp_dir_str:
            dist = Path(temp_dir_str) / "dist"
            dist.mkdir()
            artifact = dist / "asset.exe"
            artifact.write_bytes(b"asset")

            with self.assertRaisesRegex(ConfigError, "reserved output name"):
                resolve_configured_outputs(
                    dist,
                    [ReleaseOutputSpec(name="installer", pattern="asset.exe")],
                    occupied_paths=(),
                )
            with self.assertRaisesRegex(ConfigError, "collides"):
                resolve_configured_outputs(
                    dist,
                    [ReleaseOutputSpec(name="extra", pattern="asset.exe")],
                    occupied_paths=(artifact,),
                )
            with self.assertRaisesRegex(ConfigError, "expected at most 0"):
                resolve_configured_outputs(
                    dist,
                    [
                        ReleaseOutputSpec(
                            name="extra",
                            pattern="asset.exe",
                            min_matches=0,
                            max_matches=0,
                        )
                    ],
                    occupied_paths=(),
                )

    def test_publication_expands_named_outputs_and_rejects_filename_collisions(
        self,
    ) -> None:
        with TemporaryDirectory() as temp_dir_str:
            root = Path(temp_dir_str)
            installer = root / "demo.exe"
            first = root / "one" / "demo.whl"
            second = root / "two" / "DEMO.WHL"
            installer.parent.mkdir(parents=True, exist_ok=True)
            first.parent.mkdir()
            second.parent.mkdir()
            installer.write_bytes(b"installer")
            first.write_bytes(b"first")
            second.write_bytes(b"second")
            outputs = (
                describe_output("installer", installer),
                describe_output("wheels", first),
                describe_output("wheels", second),
            )

            self.assertEqual(
                (installer,),
                tuple(
                    output.path
                    for output in select_publication_outputs(outputs, ["installer"])
                ),
            )
            with self.assertRaisesRegex(ConfigError, "filename collision"):
                select_publication_outputs(outputs, ["wheels"])

            self.assertEqual(
                (),
                select_publication_outputs(
                    outputs,
                    ["optional-symbols"],
                    declared_names=["optional-symbols"],
                ),
            )


if __name__ == "__main__":
    unittest.main()
