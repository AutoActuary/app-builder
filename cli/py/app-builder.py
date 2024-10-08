import os
import shutil
import subprocess
import tempfile
from pathlib import Path
import fnmatch
import re
from textwrap import dedent
import time

import sys

from locate import allow_relative_location_imports

allow_relative_location_imports("../..")

from app_builder import git_revision
from app_builder import paths
from app_builder.exec_py import exec_py
from app_builder.shell import copy
from app_builder.util import help, init, rmtree


class ApplicationYamlError(Exception):
    pass


def iglob(p, pattern):
    rule = re.compile(fnmatch.translate(pattern), re.IGNORECASE)
    return [f for f in Path(p).glob("*") if rule.match(f.name)]


def get_app_base_directory(start_dir) -> Path:
    """
    Travel up from the starting directory to find the application's base directory, pattern contains 'Application.yaml'.
    """
    d = start_dir.resolve()
    err = ApplicationYamlError(
        "Expected git repository with 'application.yaml' at base. To initiate app-builder within"
        " the current repo, use `app-builder --init`"
    )
    for i in range(1000):
        if len(iglob(d, "application.yaml") + iglob(d, ".git")) == 2:
            return d.resolve()

        if d.parent == d:  # like "c:" == "c:"
            raise err

        d = d.parent

    raise err


def get_app_version():
    base = get_app_base_directory(Path(".").resolve())
    version = None
    with open(base.joinpath("application.yaml"), "r") as f:
        for line in f.readlines():
            line = line.split("#")[0].strip()
            if line == "":
                continue

            # Allow both app-builder and app_builder for legacy reasons
            if ":" not in line or line.split(":")[0].strip().lower() not in (
                "app-builder",
                "app_builder",
            ):
                raise ApplicationYamlError(
                    "app-builder expects 'application.yaml' files to start with `app_builder: <version>`"
                )
            else:
                version = line.split(":", 1)[1].strip()
                if (version[0] + version[-1]) in ('""', "''"):
                    version = version[1:-1]
                assert version != ""
                break

    return version


def ensure_app_version():
    rev = get_app_version()
    path_rev = paths.versions.joinpath(rev)

    # Maybe no work needed
    if not path_rev.joinpath("run.py").is_file():

        print(f"Requested version '{rev}' in application.yaml")
        print(f"Initiate app-builder '{rev}' dependencies")
        git_revision.git_download(
            "https://github.com/AutoActuary/app-builder.git", paths.live_repo, rev
        )

        # Use temp directory so that we can't accidently end up half way
        with tempfile.TemporaryDirectory() as tdir:
            tdir = Path(tdir)

            tmp_rev_repo = tdir.joinpath("repo")
            tmp_site = tdir.joinpath("site-packages")
            os.makedirs(tmp_rev_repo, exist_ok=True)
            os.makedirs(tmp_site, exist_ok=True)

            for i in paths.live_repo.glob("*"):
                if i.name == ".git":
                    continue
                copy(i, tmp_rev_repo.joinpath(i.name))

            assert 0 == subprocess.call(
                [
                    sys.executable,
                    "-m",
                    "pip",
                    "install",
                    "-r",
                    tmp_rev_repo.joinpath("requirements.txt"),
                    "--no-warn-script-location",
                ]
            )

            rmtree(path_rev, ignore_errors=True)
            os.makedirs(path_rev.parent, exist_ok=True)
            shutil.copytree(tdir, path_rev)

        print(f"App-builder version '{rev}' successful")
        print()

    # Inject launcher - note that launcher may change with the app-builder version driving this, so keep it volatile
    with open(path_rev.joinpath("run.py"), "w") as fw:
        fw.write(
            dedent(
                r"""
                from pathlib import Path
                import subprocess
                import sys
                import os
                from textwrap import dedent

                this_dir = Path(__file__).resolve().parent
                site_dir = this_dir.joinpath('site-packages')
                script = this_dir.joinpath("repo", "app_builder", "main.py")
                
                def repr_str(x):
                    return repr(str(x))
                
                sys.exit(
                    subprocess.call(
                        [
                            sys.executable,
                            "-c",
                            dedent(f'''
                                import sys;
                                sys.argv = sys.argv[0:1]+{repr(sys.argv[1:])};
                                sys.path.insert(0, {repr_str(site_dir)});
                                script = f{repr_str(script)};
                                globs = globals();
                                globs["__file__"] = script;
                                globs["__name__"] = "__main__";
                                file = open(script, 'rb');
                                script_txt = file.read();
                                file.close();
                                exec(compile(script_txt, script, 'exec'), globs);
                            '''),
                        ]
                    )
                )
                """
            )
        )

    return rev


def version_cleanup():
    """
    Use arbitrary filter choices to not let the version directory blow up in size
    """
    vdict = {}
    for i in paths.versions.glob("*"):
        run_log = i.joinpath("run.log")

        if run_log.is_file():
            vdict[os.path.getmtime(run_log)] = i

    # Sort from oldest to newest and allow versions older than the last 10 used versions to be discarded
    maybe_discard = sorted(list(vdict.keys()))[:-10]

    # Try to an extra 40 more versions
    discard = set(maybe_discard).difference(maybe_discard[-40:])

    # But don't keep any of those 40 versions if they haven't been used within the last 30 days
    discard = discard.union(
        [i for i in maybe_discard if time.time() - i > 60 * 60 * 24 * 30]
    )

    for i in discard:
        rmtree(vdict[i])


def run_versioned_main():

    try:
        rev = ensure_app_version()

    # If something is wrong with application.yaml rather print help menu
    except ApplicationYamlError:
        if len(sys.argv) < 2 or (
            len(sys.argv) >= 2 and sys.argv[1].lower() in ["-h", "--help"]
        ):
            help()

        elif len(sys.argv) >= 2 and sys.argv[1].lower() in ["-i", "--init"]:
            init()

        else:
            raise

        sys.exit()

    rev_path = paths.versions.joinpath(rev)

    # run
    exec_py(rev_path.joinpath("run.py"))

    # Leave trail
    with open(rev_path.joinpath("run.log"), "w") as fw:
        pass

    # Clean up some old versions
    version_cleanup()


if __name__ == "__main__":
    run_versioned_main()
