import ast
import fnmatch
import os
import re
import subprocess
import sys
from functools import cache
from pathlib import Path
from typing import List


def iglob(p: str | Path, pattern: str) -> List[Path]:
    rule = re.compile(fnmatch.translate(pattern), re.IGNORECASE)
    return [f for f in Path(p).glob("*") if rule.match(f.name)]


# App directories
app_dir = Path(__file__).resolve().parent.parent
tools_dir = Path(app_dir, "tools")
temp_dir = Path(tools_dir, "temp", "package-downloads")
py_dir = Path(app_dir, "bin", "python")
julia_dir = Path(app_dir, "bin", "julia")
r_dir = app_dir.joinpath("bin", "r")

# deploy-tools directories
legacy_dir = Path(__file__).resolve().parent / "src-legacy"
template_dir = legacy_dir / "templates"
asset_dir = legacy_dir / "assets"

# Binaries
ps_bin = (
    Path(
        os.environ["SYSTEMROOT"],
        "System32",
        "WindowsPowerShell",
        "v1.0",
        "powershell.exe",
    )
    if sys.platform == "win32"
    else Path("/usr/bin/powershell")
)
sevenz_bin = legacy_dir / "bin" / "7z.exe"
sevenz_dll = legacy_dir / "bin" / "7z.dll"
rcedit_bin = legacy_dir / "bin" / "rcedit.exe"
python_bin = Path(py_dir, "python", "python.exe")
julia_bin = Path(julia_dir, "julia.exe")
r_bin = r_dir.joinpath("bin", "Rscript.exe")


@cache
def python_site_packages() -> Path:
    command: List[str | Path] = [
        python_bin,
        "-c",
        "import sys; print(repr(sys.path))",
    ]

    try:
        result = subprocess.run(
            args=command, check=True, stdout=subprocess.PIPE, text=True
        )
        last_line = result.stdout.strip().split("\n")[-1]
        paths = ast.literal_eval(last_line)

        # return the first site-packages instance
        path = [
            i
            for i in paths
            if i.replace("\\", "/").lower().endswith("/lib/site-packages")
        ][0]
        return Path(path)

    except subprocess.CalledProcessError as e:
        cmd_str = " ".join([f'"{i}"' for i in command])
        raise RuntimeError(
            f"Could not find `site-packages` directory from command `{cmd_str}`"
        ) from e
