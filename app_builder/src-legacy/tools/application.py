import sys
from textwrap import dedent
from pathlib import Path
from locate import allow_relative_location_imports, this_dir

# Borrow implementation from non-legacy future application
allow_relative_location_imports('../../..')
from app_builder import exec_py
from app_builder import util

# Reshuffle args in order to call future scripts
command = "-h" if len(sys.argv) < 2 else sys.argv[1].lower()
sys.argv = sys.argv[0:1] + sys.argv[2:]


if command in ("-h", "--help"):
    util.help()

elif command in ("-d", "--get-dependencies"):
    exec_py.exec_py(this_dir().joinpath("..", "deployment-and-release-scripts", "create-dependencies.py"), globals())

elif command in ("-l", "--local-release"):
    exec_py.exec_py(this_dir().joinpath("..", "deployment-and-release-scripts", "create-releases.py"), globals())

elif command in ("-g", "--github-release"):
    exec_py.exec_py(this_dir().joinpath("..", "deployment-and-release-scripts", "create-github-release.py"), globals())

else:
    print("Error: wrong commandline arguments")
    util.help()
