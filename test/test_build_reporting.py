from __future__ import annotations

import io
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from tempfile import TemporaryDirectory

from app_builder.build_reporting import BuildReporter


class TestBuildReporter(unittest.TestCase):
    def test_reports_stages_immediately_and_keeps_details_in_log(self) -> None:
        with TemporaryDirectory() as temp_dir_str:
            log_path = Path(temp_dir_str) / "build.log"
            output = io.StringIO()
            with redirect_stdout(output):
                reporter = BuildReporter(log_path, total_stages=1)
                with reporter.stage("Payload selection"):
                    reporter.detail("source.txt -> bin/source.txt")

            visible = output.getvalue()
            log = log_path.read_text(encoding="utf-8")
            self.assertIn("[1/1] Payload selection", visible)
            self.assertIn("DONE", visible)
            self.assertNotIn("source.txt", visible)
            self.assertIn("source.txt -> bin/source.txt", log)

    def test_failed_stage_is_visible_and_recorded(self) -> None:
        with TemporaryDirectory() as temp_dir_str:
            log_path = Path(temp_dir_str) / "build.log"
            output = io.StringIO()
            with self.assertRaisesRegex(RuntimeError, "broken"):
                with redirect_stdout(output):
                    reporter = BuildReporter(log_path, total_stages=1)
                    with reporter.stage("Installer assembly"):
                        raise RuntimeError("broken")

            self.assertIn("FAIL", output.getvalue())
            self.assertIn("RuntimeError: broken", log_path.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
