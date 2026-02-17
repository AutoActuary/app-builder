import sys
from pathlib import Path

from locate import append_sys_path

from .util import help, init


def caller_version_tuple():
    """
    This is a workaround to get the version of the caller cli if app-builder is not called directly (but from the cli).
    Note: the cli also acts as a wrapper and puppeteer for maintaining different versions of this app and dispatching to the correct one.
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


def main() -> None:
    version = caller_version_tuple()
    if version is not None and version < (0, 1, 0):
        print()
        print(
            "Error: this version requires an installation of App-Builder-v0.1.0.exe or higher"
        )
        print(
            "Please Download and install here: https://github.com/AutoActuary/app-builder/releases"
        )
        sys.exit(-1)

    # Reshuffle args in order to call future scripts
    command = "-h" if len(sys.argv) < 2 else sys.argv[1].lower()
    sys.argv = sys.argv[0:1] + sys.argv[2:]

    if command in ("-h", "--help"):
        help()

    elif command in ("-i", "--init"):
        init()

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
        help()


if __name__ == "__main__":
    main()
