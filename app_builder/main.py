from locate import this_dir
import subprocess
import sys
from pathlib import Path
from locate import allow_relative_location_imports

allow_relative_location_imports("..")
from app_builder import exec_py


def caller_version_tuple():
    """
    This a a hack to get the version of the caller cli if app-builder is not called directly, but rather from the cli
    (which is wrapper for app-builder and is also responsible for maintaining different versions of this app).
    """

    py_caller = Path(sys.executable).resolve()
    app_dir = py_caller.parent.parent.parent
    if app_dir.name != "app-builder":
        return None

    version_link = list(app_dir.glob("GitHub commit *.lnk"))
    if len(version_link) != 1:
        return None
    version_link = version_link[0]

    version = version_link.name.split("GitHub commit v", 1)[-1].split(".lnk", 1)[0]
    version = version.split("-")[0]
    version = tuple(version.split("."))

    if not len(version) == 3:
        return None

    def int_able(x):
        try:
            int(x)
            return True
        except:
            return False

    version = tuple(int(i) for i in version if int_able(i))
    if not len(version) == 3:
        return None

    return version


if __name__ == "__main__":

    vertup = caller_version_tuple()

    if vertup is None or vertup >= (0, 1, 0):
        exec_py.exec_py(
            this_dir().joinpath("src-legacy", "tools", "application.py"), globals()
        )

    else:
        print()
        print(
            "Error: this version requires an installation of App-Builder-v0.1.0.exe or higher"
        )
        print(
            "Please Download and install here: https://github.com/AutoActuary/app-builder/releases"
        )
        sys.exit(-1)
