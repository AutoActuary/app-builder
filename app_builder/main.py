from locate import this_dir
import subprocess
import sys
from locate import allow_relative_location_imports
allow_relative_location_imports("..")
from app_builder import exec_py

if __name__ == "__main__":
    # For now shadow the legacy application
    exec_py.exec_py(this_dir().joinpath("src-legacy", "tools", "application.py"), globals())
