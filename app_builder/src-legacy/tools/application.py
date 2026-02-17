import sys

from locate import this_dir, append_sys_path

with append_sys_path("../../.."):
    from app_builder import exec_py
    from app_builder import util


def main() -> None:
    # Reshuffle args in order to call future scripts
    command = "-h" if len(sys.argv) < 2 else sys.argv[1].lower()
    sys.argv = sys.argv[0:1] + sys.argv[2:]

    if command in ("-h", "--help"):
        util.help()

    elif command in ("-i", "--init"):
        util.init()

    elif command in ("-d", "--get-dependencies"):
        exec_py.exec_py(
            this_dir().joinpath(
                "..", "deployment-and-release-scripts", "create-dependencies.py"
            ),
            globals(),
        )

    elif command in ("-l", "--local-release"):
        exec_py.exec_py(
            this_dir().joinpath(
                "..", "deployment-and-release-scripts", "create-releases.py"
            ),
            globals(),
        )

    elif command in ("-g", "--github-release"):
        exec_py.exec_py(
            this_dir().joinpath(
                "..", "deployment-and-release-scripts", "create-github-release.py"
            ),
            globals(),
        )

    else:
        print("Error: wrong commandline arguments")
        util.help()


if __name__ == "__main__":
    main()
