from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from app_builder.release_outputs import (
    describe_output,
    prepare_configured_output_locations,
    resolve_configured_outputs,
    select_publication_outputs,
)
from app_builder.schema import ConfigError, ReleaseOutputSpec


class TestReleaseOutputs(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
