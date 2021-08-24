import os
from pathlib import Path
import fnmatch
import re
import locate

def iglob(p, pattern):
    rule = re.compile(fnmatch.translate(pattern), re.IGNORECASE)
    return [f for f in Path(p).glob("*") if rule.match(f.name)]


def find_application_base_directory(start_dir) -> Path:
    """
    Travel up from the starting directory to find the application's base directory, pattern contains 'Application.yaml'.
    """
    d = start_dir.resolve()
    for i in range(1000):
        if len(iglob(d, "application.yaml") + iglob(d, ".git")) == 2:
            return d.resolve()

        parent = d.parent
        if parent == d:  # like "c:" == "c:"
            raise FileNotFoundError("Expected git repository with `Application.yaml` at base!")
        d = parent

    raise FileNotFoundError("Expected git repository with `Application.yaml` at base!")


# App directories
deployment_and_release_scripts_dir = locate.this_dir().joinpath('..', 'deployment-and-release-scripts').resolve()

app_dir = find_application_base_directory(Path(".").resolve())
tools_dir = Path(app_dir, 'tools')
temp_dir = Path(tools_dir, 'temp', 'package-downloads')
py_dir = Path(app_dir, "bin", "python")
julia_dir = Path(app_dir, "bin", "julia")
rpath = app_dir.joinpath("bin", "r")

# deploy-tools directories
template_dir = Path(locate.this_dir(), '..', 'templates').resolve()
asset_dir = Path(locate.this_dir(), '..', "assets").resolve()

# Binaries
ps_bin = Path(os.environ['SYSTEMROOT'], 'System32', 'WindowsPowerShell', 'v1.0', 'powershell.exe')
sevenz_bin = Path(locate.this_dir(), '..', 'bin', '7z.exe').resolve()
rcedit_bin = Path(locate.this_dir(), '..', 'bin', 'rcedit.exe').resolve()
pip_bin = Path(py_dir, 'Scripts', 'pip')
python_bin = Path(py_dir, 'python.exe')
julia_bin = Path(julia_dir, 'julia.exe')
rbin = rpath.joinpath("bin", "Rscript.exe")

# FIXME: This is an import side effect, and should be moved to a function that we call only when really needed.
temp_dir.mkdir(parents=True, exist_ok=True)
