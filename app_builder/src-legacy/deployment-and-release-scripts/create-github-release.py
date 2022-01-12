# Note that currently this script forwards the commandline arguments to create-releases.py
import os
import subprocess
from contextlib import suppress
from datetime import date
from path import Path as _Path
from pathlib import Path

import github_release
import sys

from requests import HTTPError

from app_builder import exec_py

from locate import allow_relative_location_imports

allow_relative_location_imports('.')
import misc
import app_paths

strdate = date.today().strftime("%Y-%m-%d")

try:
    # Works both with https and ssh GitHub urls
    name_repo = "/".join(misc.sh('git config --get remote.origin.url').split('.git')[0].split(':')[-1].split("/")[-2:])
except subprocess.CalledProcessError:
    raise RuntimeError("For a GitHub release a remote GitHub url must exist: `git config --get remote.origin.url`")


# ***********************************
# Register Github token
# os.environ['GITHUB_TOKEN'] = '58e4ca071ba3afba52be7de006aa26553d4ed4ef'
# ***********************************
no_msg = r"""
*** Register pipeline ***

This pipeline needs to be registered on your GitHub account. Do so by going to
https://github.com/settings/tokens/new and follow step (2) or directly in
Github.com and follow from step (1):

(1) -> Top right corner circle
    -> Settings
    -> Developer Settings
    -> Personal access tokens
    -> Generate New Token

(2) Name your token anything like "Automated releases"

(3) Select scopes -> choose only "Full control of private repositories":
    [x] repo
      [x] repo:status
      [x] repo_tools ...
      [x] security_events
    [ ] write:packages ...
    [ ] admin:gpg_key

(4) Copy the newly generated ac89b6d5-like token and paste it here.

"""

no_msg = no_msg.encode("utf-8", "ignore").decode("utf-8")

tokenpath = app_paths.tools_dir.joinpath('.github_token')


def create_token():
    if not tokenpath.is_file():
        subprocess.Popen(['explorer', 'https://github.com/settings/tokens/new'])
        print(no_msg.strip())
        token = input("Please enter your GitHub token here: ")
        tokenpath.open('w').write(token)

    token = tokenpath.open().read().strip()
    os.environ['GITHUB_TOKEN'] = token

create_token()

github_release.get_releases()

# *********************************
# After token is sorted out
# *********************************
with _Path(app_paths.app_dir):  # run git commands from chdir basedir

    # *************************************
    # Ensure that the environment is as expected
    # ************************************

    main_branch = misc.sh("git symbolic-ref refs/remotes/origin/HEAD").split("/")[-1]
    if misc.sh('git branch --show-current') != main_branch:
        print(f"You need to be on {main_branch}, checkout {main_branch} and try again.")
        sys.exit()

    print("Downloading GitHub tag information...")
    misc.sh('git fetch origin')
    misc.sh('git fetch --tags')

    if 'Your branch is up to date with' not in misc.sh('git status -uno'):
        print(f"You need to be in sync with Github and on the latest {main_branch} commit:")
        print(f'git pull origin {main_branch}')
        print(f'git push origin {main_branch}')
        sys.exit()

    # *************************************
    # Get all the tag information
    # ************************************
    recent_tag = ""
    try:
        recent_tag = misc.sh('git describe --tags')
    except:
        pass

    msg = (f"Type new version number for brand new release, else type current version number \n"
           f"{recent_tag} to upload assets: v")
    tagname = "v" + input(msg)

    print(f"Compiling exe for {tagname}...")

    # *************************************
    # Ensure the release on Github side
    # ************************************
    if tagname != recent_tag:
        github_release.gh_release_create(name_repo,
                                         tagname,
                                         publish=True,
                                         name=f"Released {strdate} {tagname}"
                                         )

    print("\nYou can add a description to the release online...\n")
    subprocess.Popen(["explorer", f"https://github.com/{name_repo}/releases/edit/{tagname}"])

    # *************************************
    # Build the exe from scratch (to contain correct git info)
    # ************************************
    misc.sh(f'git fetch --tags')
    exec_py.exec_py(str(Path(app_paths.deployment_and_release_scripts_dir, "create-releases.py")), global_names=globals())

# **********************************************
# implicitely run any script named "pre-github-upload.bat/.cmd" in dedicated locations
for scriptsdir in [".", "bin", "src", "scripts"]:
    for ext in ("bat", "cmd"):
        for script in Path(app_paths.app_dir).joinpath(scriptsdir).glob(f"pre-github-upload.{ext}"):
            subprocess.call(script)

# *************************************
# Upload exe to github
# ************************************
print()
print(f"Uploading to GitHub tag {tagname}, this may take a while...")
github_release.gh_asset_upload(name_repo, tagname, rf"{app_paths.tools_dir}\releases\*{tagname}*.exe")
github_release.gh_asset_upload(name_repo, tagname, rf"{app_paths.tools_dir}\releases\*{tagname}*.zip")


# **********************************************
# implicitely run any script named "post-github-upload.bat/.cmd" in dedicated locations
for scriptsdir in [".", "bin", "src", "scripts"]:
    for ext in ("bat", "cmd"):
        for script in Path(app_paths.app_dir).joinpath(scriptsdir).glob(f"post-github-upload.{ext}"):
            subprocess.call(script)