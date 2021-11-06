from locate import this_dir
import subprocess
import sys
from locate import allow_relative_location_imports
allow_relative_location_imports("..")
from app_builder import exec_py

def compatable_app_builder_caller():
    py_caller = Path(sys.executable).resolve()
    app_dir = py_caller.parent.parent.parent.parent
    if app_dir.name != "app-builder":
        return None

    version_link = app_dir.glob("GitHub commit *.lnk")
    if len(version_link) != 1:
        return None
    version_link = version_link[0]

    version = version_link.name.split("GitHub commit ", 1)[-1]
    version = version.split("-")[0]
    version = version.split(".")
    if not len(version) == 3:
        return None

    def int_able(x):
        try:
            int(x)
            return True
        except:
            return False

    version = (int(i) for i in version if int_able(i))
    if not len(version) == 3:
        return None

    if version >= (0,1,1):
        return True
    else:
        return False


if __name__ == "__main__":

    compat = compatable_app_builder_caller()

    # For now shadow the legacy application
    if compat in (None, True):
        exec_py.exec_py(this_dir().joinpath("src-legacy", "tools", "application.py"), globals())
    else:
        print("Error: this version requires app-builder installer v0.1.1 or higher")
        print("Download and install here: https://github.com/AutoActuary/app-builder/releases")
        sys.exit(-1)
        