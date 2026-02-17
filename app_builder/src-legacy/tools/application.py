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
        with append_sys_path("../deployment-and-release-scripts"):
            from get_dependencies import get_dependencies
        get_dependencies()

    elif command in ("-l", "--local-release"):
        with append_sys_path("../deployment-and-release-scripts"):
            from create_releases import create_releases
        create_releases()

    elif command in ("-g", "--github-release"):
        with append_sys_path("../deployment-and-release-scripts"):
            from create_github_release import create_github_release
        create_github_release()

    else:
        print("Error: wrong commandline arguments")
        util.help()


if __name__ == "__main__":
    main()
