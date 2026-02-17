import os
import subprocess
import sys
from datetime import date

import github_release
from path import Path as _Path

from .app_builder__misc import sh, last_seen_git_tag_only_on_this_branch, get_config
from .app_builder__paths import tools_dir, app_dir
from .create_release import create_release
from .scripts import iter_scripts


def create_github_release() -> None:
    strdate = date.today().strftime("%Y-%m-%d")

    try:
        # Works both with https and ssh GitHub urls
        name_repo = "/".join(
            sh("git config --get remote.origin.url")
            .split(".git")[0]
            .split(":")[-1]
            .split("/")[-2:]
        )
    except subprocess.CalledProcessError:
        raise RuntimeError(
            "For a GitHub release a remote GitHub url must exist: `git config --get remote.origin.url`"
        )

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
          [x] repo_deployment
          ...
          [x] security_events
        [ ] write:packages 
        ...
        [ ] admin:gpg_key
    
    (4) Copy the newly generated ac89b6d5-like token and paste it here.
    
    """

    no_msg = no_msg.encode("utf-8", "ignore").decode("utf-8")

    tokenpath = tools_dir.joinpath(".github_token")

    def create_token() -> None:
        if not tokenpath.is_file():
            subprocess.Popen(["explorer", "https://github.com/settings/tokens/new"])
            print(no_msg.strip())
            token = input("Please enter your GitHub token here: ")
            tokenpath.open("w").write(token)

        token = tokenpath.open().read().strip()
        os.environ["GITHUB_TOKEN"] = token

    create_token()

    try:
        github_release.get_releases(name_repo)
    except Exception as e:
        errstr = str(e).lower()
        if ("401 client error" in errstr) or ("404 client error" in errstr):
            os.unlink(tokenpath)
            create_token()
        else:
            e.add_note(
                "Connectivity errors can occur when 'tools/.github_token' became invalid. "
                "You can delete the file and try again to reset the token."
            )
            raise e

    # *********************************
    # After token is sorted out
    # *********************************
    with _Path(app_dir):  # run git commands from chdir basedir

        # *************************************
        # Ensure that the environment is as expected
        # ************************************
        config = get_config()

        current_branch = sh("git branch --show-current")
        try:
            main_branch = sh("git symbolic-ref refs/remotes/origin/HEAD", True).split(
                "/"
            )[-1]
        except subprocess.CalledProcessError as e:
            # HEAD branch not set yet
            if "exit status 128" in str(e):
                main_branch = current_branch
            else:
                raise

        if "allowed_branches" in config:
            allowed_branches = config["allowed_branches"]
            if isinstance(allowed_branches, str):
                allowed_branches = [allowed_branches]
        else:
            allowed_branches = [main_branch]

        if current_branch not in allowed_branches:
            print(
                f"You can only create releases from these branches {allowed_branches}, git checkout and try again."
            )
            sys.exit()

        print("Downloading GitHub tag information...")
        sh("git fetch origin")
        sh("git fetch --tags")

        if "Your branch is up to date with" not in sh("git status -uno"):
            print(
                f"You need to be in sync with Github and on the latest commit of your branch:"
            )
            print(f"git pull origin {current_branch}")
            print(f"git push origin {current_branch}")
            sys.exit()

        target_commitish = sh("git rev-parse HEAD")

        # *************************************
        # Get all the tag information
        # ************************************
        recent_tag = None
        current_tag = None
        try:
            recent_tag = last_seen_git_tag_only_on_this_branch(current_branch)
            current_tag = sh(f"git describe --tags")
        except:
            pass

        if recent_tag == current_tag and recent_tag is not None:
            msg = f"You are still on commit version {recent_tag}, retype to upload additional assets: v"
        else:
            msg = (
                f"Type new version number for this release"
                + (
                    f" (last version on {current_branch} was {recent_tag})"
                    if recent_tag is not None
                    else ""
                )
                + ": v"
            )

        while (user_input := input(msg)).strip() == "":
            pass

        tagname = "v" + user_input

        print(f"Compiling exe for {tagname}...")

        # *************************************
        # Ensure the release on Github side
        # ************************************
        if tagname != recent_tag:
            github_release.gh_release_create(
                name_repo,
                tagname,
                publish=True,
                name=f"Released {strdate} {tagname}",
                target_commitish=target_commitish,
            )

        print("\nYou can add a description to the release online...\n")
        subprocess.Popen(
            ["explorer", f"https://github.com/{name_repo}/releases/edit/{tagname}"]
        )

        # *************************************
        # Build the exe from scratch (to contain correct git info)
        # ************************************
        sh(f"git fetch --tags")
        create_release(tagname)

    # Find and run scripts named "pre-github-upload.bat/.cmd"
    for script in iter_scripts(
        base_dir=app_dir,
        sub_dirs=[".", "bin", "src", "scripts"],
        extensions=["bat", "cmd"],
        names=["pre-github-upload"],
    ):
        subprocess.run(args=script, check=True)

    # *************************************
    # Upload exe to github
    # ************************************
    print()
    print(f"Uploading to GitHub tag {tagname}, this may take a while...")
    github_release.gh_asset_upload(
        name_repo, tagname, rf"{tools_dir}\releases\*{tagname}*.exe"
    )
    github_release.gh_asset_upload(
        name_repo, tagname, rf"{tools_dir}\releases\*{tagname}*.zip"
    )

    # **********************************************
    # Find and run scripts named "post-github-upload.bat/.cmd"
    for script in iter_scripts(
        base_dir=app_dir,
        sub_dirs=[".", "bin", "src", "scripts"],
        extensions=["bat", "cmd"],
        names=["post-github-upload"],
    ):
        subprocess.run(args=script, check=True)
