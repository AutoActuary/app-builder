from __future__ import annotations

import json
import os
import subprocess
import unittest
import base64
from pathlib import Path


class TestDogfoodPostInstall(unittest.TestCase):
    @unittest.skipUnless(os.name == "nt", "PowerShell hook is Windows-specific")
    def test_path_update_removes_duplicates_and_prepends_one_entry(self) -> None:
        script_path = (
            Path(__file__).resolve().parents[1] / "scripts" / "post-install.ps1"
        )
        command = r"""
$Source = Get-Content -LiteralPath $env:HOOK_PATH -Raw
$FunctionsOnly = $Source.Substring(0, $Source.IndexOf('$InstallDir ='))
Invoke-Expression $FunctionsOnly
$Result = Get-PathWithEntryFirst `
    -CurrentPath 'C:\Before;"C:\App Builder\";C:\Middle;c:\app builder;C:\After' `
    -Entry 'C:\App Builder'
ConvertTo-Json -Compress $Result
"""
        encoded_command = base64.b64encode(command.encode("utf-16-le")).decode("ascii")
        completed = subprocess.run(
            [
                "powershell.exe",
                "-NoLogo",
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-EncodedCommand",
                encoded_command,
            ],
            check=True,
            capture_output=True,
            text=True,
            env={**os.environ, "HOOK_PATH": str(script_path)},
        )

        self.assertEqual(
            r"C:\App Builder;C:\Before;C:\Middle;C:\After",
            json.loads(completed.stdout),
        )


if __name__ == "__main__":
    unittest.main()
