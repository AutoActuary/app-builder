import os
import sys
from pathlib import Path

from .paths import get_app_base_directory

# App directories
app_dir = get_app_base_directory(Path(".").resolve())
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
