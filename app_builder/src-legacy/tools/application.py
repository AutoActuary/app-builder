import sys
from textwrap import dedent
from pathlib import Path
from locate import allow_relative_location_imports, this_dir

# Borrow implementation from non-legacy future application
sys.path.append(str(Path(__file__).resolve().parent.parent.parent.parent))
from app_builder import exec_py

# Reshuffle args in order to call future scripts
command = sys.argv[1].lower()
sys.argv = sys.argv[0:1] + sys.argv[2:]


def help():
    print(dedent("""
        Usage: app-builder [Options]
        Options:
          -h, --help             Print these options
          -p, --get-python       Download and extract python to bin/python
          -d, --get-dependencies Ensure all the dependencies are set up properly
          -b, --branch-excel <file> <branch>
          -l, --local-release [--build-script <script> [args...]]
          -g, --github-release [--build-script <script> [args...]]
          -i, --create-inputs-installer       Create inputs version control installer
          --update-inputs-tables [Options]    Run sub script and pass options
          --extract-inputs-tables [Options]   Run sub script and pass options
        """))


if command in ("-h", "--help"):
    help()

elif command in ("-d", "--get-dependencies"):
    exec_py(this_dir().joinpath("..", "deployment-and-release-scripts", "create-dependencies.py"), globals())

elif command in ("-l", "--local-release"):
    exec_py(this_dir().joinpath("..", "deployment-and-release-scripts", "create-releases.py"), globals())

elif command in ("-g", "--github-release"):
    exec_py(this_dir().joinpath("..", "deployment-and-release-scripts", "create-github-release.py"), globals())

else:
    print("Error: wrong commandline arguments")
    help()
