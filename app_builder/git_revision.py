import os
import subprocess
import tempfile
import urllib
from contextlib import suppress
from json import loads
from pathlib import Path
from urllib.request import urlopen

from .paths import temp_dir
from .util import rmtree
from .shell import sh_lines, sh_quiet
from .util import working_directory

repo_dir = Path(__file__).resolve().parent.parent


def ensure_git():
    """
    Do some wild gymnastics to ensure git is in the PATH. If not, then download
    portable version from github and put that into temporary path.
    """
    git = "git.exe"

    # Make sure bundled git is in path as a fallback (end of path)
    bin_dir = repo_dir / "bin"
    if not bin_dir.joinpath("python", "python.exe").is_file():
        bin_dir = temp_dir.joinpath("bin")

    git_bundled = bin_dir.joinpath("git", "bin", "git.exe")
    git_bundled_dir = git_bundled.parent.parent
    if f";{git_bundled_dir.joinpath('bin')};" not in f";{os.environ['PATH']};":
        os.environ["PATH"] = f"{os.environ['PATH']};{git_bundled_dir.joinpath('bin')}"

    # Is git installed?
    try:
        sh_lines([git, "--version"], stderr=subprocess.DEVNULL)

    # Download portable git from github
    except (subprocess.CalledProcessError, FileNotFoundError):
        github_latest = (
            "https://api.github.com/repos/git-for-windows/git/releases/latest"
        )
        if not git_bundled.is_file():
            giturl = None
            d = loads(urlopen(github_latest).read().decode("utf-8"))
            for s in d["assets"]:
                if "browser_download_url" in s:
                    url = s["browser_download_url"]
                    if url.endswith(".7z.exe") and "64-bit" in url:
                        giturl = url

            if giturl is None:
                raise RuntimeError(f"Could not find git url at {github_latest}")

            with tempfile.TemporaryDirectory() as tmp:
                dlpath = Path(tmp).joinpath(Path(giturl).name)
                print(f"Downloading git from '{giturl}'")
                urllib.request.urlretrieve(giturl, dlpath)
                os.makedirs(git_bundled_dir, exist_ok=True)
                subprocess.call(
                    [
                        str(this_dir().joinpath("src-legacy", "bin", "7z.exe")),
                        "x",
                        str(dlpath),
                        f"-o{git_bundled_dir}",
                        "-y",
                    ],
                    stdout=subprocess.DEVNULL,
                )

        e = None
        try:
            sh_lines([git, "--version"], stderr=subprocess.DEVNULL)
        except (subprocess.CalledProcessError, FileNotFoundError):
            try:
                sh_lines([str(git_bundled), "--version"], stderr=subprocess.DEVNULL)
                git = str(git_bundled)
            except (subprocess.CalledProcessError, FileNotFoundError) as e:
                raise RuntimeError(
                    "Could not use system Git and could not successfully download and set up an portable alternative."
                )
        finally:
            if e is not None:
                raise e

    return git


def git_download(git_source, dest, revision=None):
    os.makedirs(dest, exist_ok=True)

    with working_directory(dest):
        if Path(os.getcwd()).resolve() != Path(dest).resolve():
            raise (RuntimeError(f"Could not create and enter {dest}"))

        git = ensure_git()

        # Test if we are currently tracking the ref
        def is_on_ref(revision):
            if revision is None:
                return False
            try:
                commit = sh_lines([git, "rev-parse", "HEAD"])[0]
                return (
                    commit
                    == sh_lines(
                        [git, "rev-list", "-n", "1", revision],
                        stderr=subprocess.DEVNULL,
                    )[0]
                )
            except subprocess.CalledProcessError:
                return False

        if Path(".git").is_dir():
            if is_on_ref(revision):
                sh_quiet([git, "reset", "--hard"])
                sh_quiet([git, "clean", "-qdfx"])
                return None

        gitremote = None  # noqa
        with suppress(subprocess.CalledProcessError):
            gitremote = sh_lines([git, "config", "--get", "remote.origin.url"])[0]

        # If not correct git source, re-download
        if gitremote != git_source:
            for i in Path(".").glob("*"):
                if i.is_file():
                    os.remove(i)
                else:
                    rmtree(i)

            subprocess.call([git, "clone", git_source, str(Path(".").resolve())])
            if not Path("./.git").is_dir():
                raise (RuntimeError(f"Could not `git clone {git_source} .`"))

        sh_quiet([git, "reset", "--hard"])
        sh_quiet([git, "clean", "-qdfx"])

        for do_upstream_fetch in [False, True]:
            if do_upstream_fetch:
                for branch in sh_lines([git, "branch", "-a"]):
                    if "->" in branch:
                        continue
                    sh_quiet([git, "branch", "--track", branch.split("/")[-1], branch])

            sh_quiet([git, "fetch", "--all"])
            sh_quiet([git, "fetch", "--tags", "--force"])

            # set revision to default branch
            if revision is None:
                revision = sh_lines([git, "symbolic-ref", "refs/remotes/origin/HEAD"])[
                    0
                ].split("/")[-1]

            sh_quiet([git, "pull", "origin", revision])
            sh_quiet([git, "checkout", "--force", revision])

            if is_on_ref(revision):
                return None

        raise RuntimeError(f"Could not check out {revision}")
