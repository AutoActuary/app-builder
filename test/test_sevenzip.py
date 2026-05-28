from __future__ import annotations

import contextlib
import io
import os
import subprocess
import unittest
from pathlib import Path, PurePosixPath
from tempfile import TemporaryDirectory
from unittest.mock import patch

from app_builder import sevenzip


class TestSevenZipPayloadArchive(unittest.TestCase):
    def test_vendored_7zip_assets_match_recorded_hashes(self) -> None:
        files = sevenzip.vendored_7zip_files()

        self.assertEqual({"bin/7z.exe", "bin/7z.dll"}, set(files.values()))
        for source in files:
            self.assertTrue(source.exists())

    def test_filter_7z_output_suppresses_routine_noise(self) -> None:
        output = "\n".join(
            [
                "7-Zip 19.00 (x64) : Copyright (c) 1999-2018 Igor Pavlov : 2019-02-21",
                "Scanning the drive:",
                "3 files, 12 bytes (1 KiB)",
                "Creating archive: demo.7z",
                "Everything is Ok",
                "Real warning",
            ]
        )

        self.assertEqual("Real warning", sevenzip._filter_7z_output(output))

    def test_validate_archive_path_rejects_escape_paths(self) -> None:
        for value in (
            "../outside.txt",
            "bin/../../outside.txt",
            "C:/temp/outside.txt",
            "/absolute/path.txt",
            "//server/share/file.txt",
            "bin/name:stream.txt",
            "",
        ):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    sevenzip.validate_archive_path(value)

    @unittest.skipIf(os.name != "nt", "vendored 7z.exe runs on Windows")
    def test_create_7z_payload_supports_remap_and_version_quietly(self) -> None:
        with TemporaryDirectory() as temp_dir_str:
            project_root = Path(temp_dir_str) / "project"
            project_root.mkdir()
            (project_root / "plain.txt").write_text("plain", encoding="utf-8")
            (project_root / "src").mkdir()
            (project_root / "src" / "app.txt").write_text("app", encoding="utf-8")
            archive = Path(temp_dir_str) / "payload.7z"
            extract_dir = Path(temp_dir_str) / "extract"
            remap_table = {
                project_root / "plain.txt": PurePosixPath("plain.txt"),
                project_root / "src" / "app.txt": PurePosixPath("renamed/app.txt"),
            }
            stdout = io.StringIO()
            stderr = io.StringIO()

            with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                sevenzip.create_7z_payload_archive(
                    archive,
                    project_root,
                    remap_table,
                    version="1.2.3",
                )

            self.assertEqual("", stdout.getvalue())
            self.assertEqual("", stderr.getvalue())
            _extract_7z(archive, extract_dir)
            self.assertEqual("plain", (extract_dir / "plain.txt").read_text())
            self.assertEqual("app", (extract_dir / "renamed" / "app.txt").read_text())
            self.assertEqual("1.2.3", (extract_dir / "version.txt").read_text())

    @unittest.skipIf(os.name != "nt", "vendored 7z.exe runs on Windows")
    def test_locked_files_are_staged_before_7z_archiving(self) -> None:
        with TemporaryDirectory() as temp_dir_str:
            project_root = Path(temp_dir_str) / "project"
            project_root.mkdir()
            locked = project_root / "locked.txt"
            locked.write_text("locked", encoding="utf-8")
            archive = Path(temp_dir_str) / "payload.7z"
            extract_dir = Path(temp_dir_str) / "extract"

            with (
                patch("app_builder.sevenzip.can_7z_read_file", return_value=False),
                patch(
                    "app_builder.sevenzip._stage_file",
                    wraps=sevenzip._stage_file,
                ) as stage_file,
            ):
                sevenzip.create_7z_payload_archive(
                    archive,
                    project_root,
                    {locked: PurePosixPath("locked.txt")},
                    version="2.0.0",
                )

            self.assertTrue(stage_file.called)
            _extract_7z(archive, extract_dir)
            self.assertEqual("locked", (extract_dir / "locked.txt").read_text())


def _extract_7z(archive: Path, destination: Path) -> None:
    destination.mkdir()
    subprocess.run(
        [
            str(sevenzip.vendored_7zip_executable()),
            "x",
            "-y",
            "-bd",
            f"-o{destination}",
            str(archive),
        ],
        check=True,
        capture_output=True,
        text=True,
    )


if __name__ == "__main__":
    unittest.main()
