import os
from pathlib import Path
import fnmatch
import re
import locate
import subprocess
from functools import cache
import ast


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
            raise FileNotFoundError(
                "Expected git repository with `application.yaml` at base!"
            )
        d = parent

    raise FileNotFoundError("Expected git repository with `application.yaml` at base!")


# App directories
deployment_and_release_scripts_dir = (
    locate.this_dir().joinpath("..", "deployment-and-release-scripts").resolve()
)

app_dir = find_application_base_directory(Path(".").resolve())
tools_dir = Path(app_dir, "tools")
temp_dir = Path(tools_dir, "temp", "package-downloads")
py_dir = Path(app_dir, "bin", "python")
julia_dir = Path(app_dir, "bin", "julia")
r_dir = app_dir.joinpath("bin", "r")

# deploy-tools directories
template_dir = Path(locate.this_dir(), "..", "templates").resolve()
asset_dir = Path(locate.this_dir(), "..", "assets").resolve()

# Binaries
ps_bin = Path(
    os.environ["SYSTEMROOT"], "System32", "WindowsPowerShell", "v1.0", "powershell.exe"
)
sevenz_bin = Path(locate.this_dir(), "..", "bin", "7z.exe").resolve()
rcedit_bin = Path(locate.this_dir(), "..", "bin", "rcedit.exe").resolve()
python_bin = Path(py_dir, "python.exe")
julia_bin = Path(julia_dir, "julia.exe")
r_bin = r_dir.joinpath("bin", "Rscript.exe")

# FIXME: This is an import side effect, and should be moved to a function that we call only when really needed.
temp_dir.mkdir(parents=True, exist_ok=True)


_real_python_bin_cache = {}


def python_real_bin() -> Path:
    if _real_python_bin_cache:
        return _real_python_bin_cache["value"]

    command = [
        python_bin,
        "-S",
        "-c",
        "import sys; print(sys.executable)",
    ]

    try:
        result = subprocess.run(command, check=True, stdout=subprocess.PIPE, text=True)
        path = Path(result.stdout.strip())

        _real_python_bin_cache["value"] = path
        return path

    except subprocess.CalledProcessError as e:
        cmd_str = " ".join([f'"{i}"' for i in command])
        raise RuntimeError(
            f"Could not find `site-packages` directory from command `{cmd_str}`"
        ) from e


@cache
def python_real_bin() -> Path:
    command = [
        python_bin,
        "-S",
        "-c",
        "import sys; print(repr(sys.executable))",
    ]

    try:
        result = subprocess.run(command, check=True, stdout=subprocess.PIPE, text=True)
        path = Path(ast.literal_eval(result.stdout))
        return path

    except subprocess.CalledProcessError as e:
        cmd_str = " ".join([f'"{i}"' for i in command])
        raise RuntimeError(
            f"Could not find `site-packages` directory from command `{cmd_str}`"
        ) from e


@cache
def python_lib() -> Path:
    command = [
        python_bin,
        "-S",
        "-c",
        "import pathlib; print(repr(str(pathlib.Path(pathlib.__file__).parent)))",
    ]

    try:
        result = subprocess.run(command, check=True, stdout=subprocess.PIPE, text=True)
        return Path(ast.literal_eval(result.stdout))

    except subprocess.CalledProcessError as e:
        cmd_str = " ".join([f'"{i}"' for i in command])
        raise RuntimeError(
            f"Could not find `Lib` directory from command `{cmd_str}`"
        ) from e


@cache
def python_site_packages() -> Path:
    command = [
        python_bin,
        "-c",
        "import sys; print(repr(sys.path))",
    ]

    try:
        result = subprocess.run(command, check=True, stdout=subprocess.PIPE, text=True)
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
