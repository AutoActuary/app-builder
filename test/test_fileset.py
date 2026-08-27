from __future__ import annotations

import unittest
import time
from pathlib import Path, PurePosixPath
from tempfile import TemporaryDirectory

from app_builder.fileset import (
    build_remap_table,
    collect_files,
    validate_archive_path,
    validate_remap_table,
)


class TestArchiveDestinationValidation(unittest.TestCase):
    def test_payload_selection_requires_every_include_and_a_nonempty_result(
        self,
    ) -> None:
        with TemporaryDirectory() as temp_dir_str:
            project_root = Path(temp_dir_str)
            (project_root / "present.txt").write_text("present", encoding="utf-8")

            with self.assertRaisesRegex(FileNotFoundError, "matched nothing"):
                collect_files(project_root, ["missing.txt"], [])
            with self.assertRaisesRegex(ValueError, "file set is empty"):
                collect_files(project_root, ["present.txt"], ["present.txt"])

    def test_remap_source_must_exist_and_be_selected(self) -> None:
        with TemporaryDirectory() as temp_dir_str:
            project_root = Path(temp_dir_str)
            selected = project_root / "selected.txt"
            unselected = project_root / "unselected.txt"
            selected.write_text("selected", encoding="utf-8")
            unselected.write_text("unselected", encoding="utf-8")

            with self.assertRaisesRegex(FileNotFoundError, "does not exist"):
                build_remap_table(
                    project_root, [selected], [("missing.txt", "renamed.txt")]
                )
            with self.assertRaisesRegex(ValueError, "resolved file set"):
                build_remap_table(
                    project_root, [selected], [("unselected.txt", "renamed.txt")]
                )

    def test_rejects_paths_unsafe_for_windows_extraction(self) -> None:
        for value in (
            "../outside.txt",
            "bin/../../outside.txt",
            r"bin\..\outside.txt",
            "C:/temp/outside.txt",
            "/absolute/path.txt",
            "//server/share/file.txt",
            "bin/name:stream.txt",
            "bin//file.txt",
            "bin/file.txt.",
            "bin/NUL.txt",
            "",
        ):
            with self.subTest(value=value):
                with self.assertRaisesRegex(ValueError, "Unsafe archive path"):
                    validate_archive_path(value)

    def test_normalizes_windows_separators(self) -> None:
        self.assertEqual(
            PurePosixPath("bin/program.exe"),
            validate_archive_path(r"bin\program.exe"),
        )

    def test_rejects_case_insensitive_destination_collision(self) -> None:
        with self.assertRaisesRegex(ValueError, "destination collision"):
            validate_remap_table(
                {
                    Path("first.txt"): PurePosixPath("bin/App.txt"),
                    Path("second.txt"): PurePosixPath("BIN/app.TXT"),
                }
            )

    def test_rejects_file_directory_collision(self) -> None:
        with self.assertRaisesRegex(ValueError, "file/directory collision"):
            validate_remap_table(
                {
                    Path("first.txt"): PurePosixPath("bin"),
                    Path("second.txt"): PurePosixPath("bin/app.txt"),
                }
            )

    def test_rejects_app_builder_reserved_destination(self) -> None:
        with self.assertRaisesRegex(ValueError, "reserved by app-builder"):
            validate_remap_table(
                {Path("custom.txt"): PurePosixPath("VERSION.txt")},
                reserved_paths=("version.txt",),
            )

    def test_large_remap_validation_is_not_quadratic(self) -> None:
        remap_table = {
            Path(f"source-{index}.txt"): PurePosixPath(
                f"packages/group-{index // 1000}/file-{index}.txt"
            )
            for index in range(32_000)
        }

        started = time.monotonic()
        validate_remap_table(remap_table)
        elapsed = time.monotonic() - started

        self.assertLess(elapsed, 3.0)

    def test_build_remap_table_rejects_unsafe_and_duplicate_remaps(self) -> None:
        with TemporaryDirectory() as temp_dir_str:
            project_root = Path(temp_dir_str)
            first = project_root / "first.txt"
            second = project_root / "second.txt"
            first.write_text("first", encoding="utf-8")
            second.write_text("second", encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "Unsafe archive path"):
                build_remap_table(
                    project_root,
                    [first],
                    [("first.txt", "../outside.txt")],
                )
            with self.assertRaisesRegex(ValueError, "destination collision"):
                build_remap_table(
                    project_root,
                    [first, second],
                    [
                        ("first.txt", "same.txt"),
                        ("second.txt", "SAME.txt"),
                    ],
                )


if __name__ == "__main__":
    unittest.main()
