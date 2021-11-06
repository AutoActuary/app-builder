from locate import this_dir
import subprocess
import sys
from exec_py import exec_py

if __name__ == "__main__":
    # For now shadow the legacy application
    exec_py(this_dir().joinpath("src-legacy", "tools", "application.py"), globals())
