import subprocess
from path import Path as _Path
from locate import allow_relative_location_imports

allow_relative_location_imports('../includes')
import paths


def sh(cmd):
    return subprocess.check_output(cmd, shell=True).decode('utf-8').strip()


def get_githuburl():
    with _Path(paths.app_dir):
        commit = sh('git rev-parse HEAD')
        giturl = sh('git config --get remote.origin.url')
        giturl = giturl.split('@')[1].replace('.git', "").replace(':', "/")
        if giturl.startswith('github.com'):
            giturl = f"https://{giturl}"

        giturl = f'{giturl}/commit/{commit}'
    return giturl


def get_gitversion():
    with _Path(paths.app_dir):
        try:
            return sh("git describe --tags")
        except subprocess.CalledProcessError:
            return ""
