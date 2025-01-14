import os
import shutil
import subprocess
import textwrap
from pathlib import Path

import sys
from locate import allow_relative_location_imports
from path import Path as _Path
from itertools import chain

allow_relative_location_imports(".")
import app_builder__misc
import app_builder__versioning
import app_builder__paths
from file_pattern_7zip import create_7zip_from_include_exclude_and_rename_list

create_dependencies = __import__("create-dependencies")


def create_releases(version=None):
    config = app_builder__misc.get_config()

    name = config["application"]["name"]

    if version is None:
        version = app_builder__versioning.get_gitversion()

    # **********************************************
    # Make 100% sure all .bat files have \r\n endings
    # **********************************************
    def make_bat_lrln(filename):
        filename = Path(filename)
        txt = filename.open("rb").read()
        if b"\n" in txt and not b"\r\n" in txt:
            print("Lrln conversion: ", filename)
            txt = b"\r\n".join(txt.split(b"\n"))
            filename.open("wb").write(txt)

    for path in chain(app_builder__paths.app_dir.rglob("*.bat"), app_builder__paths.app_dir.rglob("*.cmd")):
        if not path.is_dir():
            make_bat_lrln(path)

    # **********************************************
    # Create all dependencies
    # **********************************************
    create_dependencies.create_all_dependencies()

    # **********************************************
    # Create application entry points with correct icons
    # Deprecated (want to move to more explicit launchers)
    # **********************************************
    entrypointpath = app_builder__paths.tools_dir.joinpath("entrypoint")
    os.makedirs(entrypointpath, exist_ok=True)
    if "entrypoint" in config["application"]:
        entrytxt = app_builder__paths.template_dir.joinpath("entrypoint.bat").open().read()
        entrytxt = entrytxt.replace(
            "__entrypoint__", config["application"]["entrypoint"]
        )

        if config["application"]["pause"]:
            entrytxt = entrytxt.replace("__pause__", "true")

        os.makedirs(entrypointpath, exist_ok=True)

        entrybat = entrypointpath.joinpath(name + ".bat")
        entrybat.open("w").write(entrytxt)

        entryexe = entrypointpath.joinpath(config["application"]["name"] + ".exe")
        app_builder__misc.make_launcher(
            app_builder__paths.app_dir.joinpath(config["application"]["launcher"]),
            entryexe,
            app_builder__paths.app_dir.joinpath(config["application"]["icon"]),
        )

    # **********************************************
    # Create installer / uninstaller bat
    # **********************************************
    asciibanner = open(
        app_builder__paths.app_dir.joinpath(config["application"]["asciibanner"])
    ).read()
    asciibanner_lines = []
    for line in [""] + asciibanner.split("\n"):
        if line.strip() == "":
            asciibanner_lines.append("echo:")
        else:
            asciibanner_lines.append("echo " + "".join(["^" + i for i in line]))
    asciibanner = "\n".join(asciibanner_lines)

    for xstall in ["Uninstall", "Install"]:
        xnstalltxt = app_builder__paths.template_dir.joinpath(f"{xstall}er.bat").open().read()
        xnstalltxt = xnstalltxt.replace("__name__", name)
        xnstalltxt = xnstalltxt.replace(
            "__installdir__", config["application"]["installdir"]
        )
        menu_name = (
            config["application"]["menuname"]
            if "menuname" in config["application"]
            else rf"AutoActuary\{config['application']['name']}"
        )
        xnstalltxt = xnstalltxt.replace("__menuname__", menu_name)

        # replace whole section
        xnstalltxt = xnstalltxt.replace("::__echobanner__", asciibanner)

        xnstallout = entrypointpath.joinpath(f"{xstall} {name}.bat")
        with xnstallout.open("w") as f:
            f.write(xnstalltxt)

        # keep as variables
        if xstall == "Install":
            installout = xnstallout
        else:
            uninstallout = xnstallout

    # **********************************************
    # Add shortcut to githuburl
    # **********************************************
    txt = (
        installout.open()
        .read()
        .replace(
            "::__githuburl__",
            f'call :CREATE-SHORTCUT "%SYSTEMROOT%\\explorer.exe" "%installdir%\\GitHub commit {version}.lnk" "{app_builder__versioning.get_githuburl()}" ""',
        )
    )
    with installout.open("w") as f:
        f.write(txt)

    # **********************************************
    # Add shortcuts to installer (this is quite a hack)
    # **********************************************
    if "startmenu" in config["application"]:
        cmds = []
        for file in config["application"]["startmenu"]:
            if isinstance(file, str):
                if not Path(file).expanduser().is_absolute():
                    file = Path("%installdir%", file)

                link = Path("%menudir%", os.path.splitext(file.name)[0] + ".lnk")

                cmd = f'call :CREATE-SHORTCUT "{file}" "{link}"'

            elif isinstance(file, list) and len(file) in (2, 3):
                file_ = Path(file[0])
                link = Path(
                    file[1] if file[1].lower().endswith(".lnk") else file[1] + ".lnk"
                )
                icon = Path(file_ if len(file) == 2 else file[2])

                if not file_.expanduser().is_absolute():
                    file_ = Path("%installdir%", file_)

                if not link.expanduser().is_absolute():
                    link = Path("%menudir%", link)

                if not icon.expanduser().is_absolute():
                    icon = Path("%installdir%", icon)

                cmd = f'call :CREATE-SHORTCUT "{file_}" "{link}" "" "{icon}"'

            else:
                err = (
                    f"application.yaml shortcuts must either be a single string entry or a list of 2 or 3 entries, "
                    f"[<source>, <dest>, <optional icon>], got: {file}"
                )
                raise RuntimeError(err)

            cmds.append(cmd)

        txt = installout.open().read().replace("::__shortcuts__", "\n".join(cmds))
        with installout.open("w") as f:
            f.write(txt)

    # **********************************************
    # If there are any scripts that should be run before
    # compressing everything into an exe, do it now
    # **********************************************
    run_external_script = False
    for i, arg in enumerate(sys.argv):
        if arg.lower() == "--build-script" or arg.lower() == "-s":
            run_external_script = sys.argv[i + 1 :]

    if run_external_script:
        with _Path(app_builder__paths.app_dir):
            run_external_script[0] = Path(run_external_script[0]).resolve()
        subprocess.call(run_external_script)

    # **********************************************
    # implicitely run any script named "pre-build.bat" or "pre-build.cmd" in dedicated locations
    for scriptsdir in [".", "bin", "src", "scripts"]:
        for ext in ("bat", "cmd"):
            for script in (
                Path(app_builder__paths.app_dir).joinpath(scriptsdir).glob(f"pre-build.{ext}")
            ):
                subprocess.call(script)
            for script in (
                Path(app_builder__paths.app_dir).joinpath(scriptsdir).glob(f"pre-release.{ext}")
            ):
                subprocess.call(script)

    # **********************************************
    # Zip all the application files as one thing
    # **********************************************
    zipext = f".{config['application'].get('compression', '7z')}"
    if zipext not in (".zip", ".7z"):
        raise RuntimeError(
            f"Unknown compression type: {zipext[1:]}; required to be either 'zip' or '7z'"
        )

    programzip = app_builder__paths.tools_dir.joinpath(
        "releases", config["application"]["name"] + zipext
    )

    data_fields = {"programdata", "data"}.intersection(config["application"])
    if len(data_fields) == 2:
        raise RuntimeError(
            "application.yaml cannot have a 'data' field and a legacy 'programdata' field together - choose one."
        )

    if len(data_fields) == 0:
        raise RuntimeError(
            "application.yaml must have either a 'data' field or a legacy 'programdata' field."
        )

    # **********************************************
    # Legacy zip creation
    # **********************************************
    if data_fields == {"programdata"}:
        mapping = config["application"]["programdata"] + [
            ["./tools/entrypoint/" + uninstallout.name, "./bin/" + uninstallout.name],
            [f"{app_builder__paths.asset_dir}/uninstall.ico", "./bin/uninstall.ico"],
            [f"{config['application']['icon']}", "./bin/icon.ico"],
        ]

        app_builder__misc.mapped_zip(programzip, mapping, basedir=app_builder__paths.app_dir)

        installzip = app_builder__paths.tools_dir.joinpath(
            "releases", config["application"]["name"] + "_.7z"
        )

        mapping = [
            ["./tools/entrypoint/" + installout.name, "./" + installout.name],
            ["./bin/7z.exe", "./bin/7z.exe"],
            ["./bin/7z.dll", "./bin/7z.dll"],
            ["./tools/releases/" + programzip.name, "./" + programzip.name],
        ]
        # Copy any script named "pre-install.bat/cmd" to installer
        for scriptsdir in [".", "bin", "src", "scripts"]:
            for ext in ("bat", "cmd"):
                for script in (
                    Path(app_builder__paths.app_dir)
                    .joinpath(scriptsdir)
                    .resolve()
                    .glob(f"pre-install.{ext}")
                ):
                    relpath = (
                        ("./" + str(script.relative_to(app_builder__paths.app_dir)))
                        .replace("\\", "/")
                        .replace("//", "/")
                    )
                    mapping.append([relpath, relpath])

        app_builder__misc.mapped_zip(installzip, mapping, basedir=app_builder__paths.app_dir, copymode=True)

    if data_fields == {"data"}:
        # Add user-defined input
        globs_include = (
            config["application"]["data"]["include"]
            if "include" in config["application"]["data"]
            else []
        )
        globs_exclude = (
            config["application"]["data"]["exclude"]
            if "exclude" in config["application"]["data"]
            else []
        )
        paths_rename = (
            config["application"]["data"]["rename"]
            if "rename" in config["application"]["data"]
            else []
        )

        print("Creating 7zip archive:")
        create_7zip_from_include_exclude_and_rename_list(
            programzip,
            app_builder__paths.app_dir,
            globs_include,
            globs_exclude,
            [(i, j) for i, j in paths_rename],
            False,
            False,
            app_builder__paths.sevenz_bin,
        )

        # Add system-default things like uninstaller
        paths_rename = {
            f"tools/entrypoint/{uninstallout.name}": f"bin/{uninstallout.name}",
            f"{app_builder__paths.asset_dir}/uninstall.ico": "bin/uninstall.ico",
            f"{config['application']['icon']}": "bin/icon.ico",
        }

        create_7zip_from_include_exclude_and_rename_list(
            programzip,
            app_builder__paths.app_dir,
            include_glob_list=list(paths_rename),
            rename_list=list(paths_rename.items()),
            append=True,
            sevenzip_bin=app_builder__paths.sevenz_bin,
            show_progress=False,
        )

        print(f"Creating 7zip installer for version {version}:")
        installzip = app_builder__paths.tools_dir.joinpath(
            "releases", config["application"]["name"] + "_.7z"
        )

        globs_include = ["bin/7z.*", f"tools/entrypoint/{installout.name}"]
        paths_rename = [
            (
                f"tools/entrypoint/{installout.name}",
                installout.name,
            )
        ]

        # Copy any script named "pre-install.bat/cmd" directly to installer
        for scriptsdir in [".", "bin", "src", "scripts"]:
            for ext in ("bat", "cmd"):
                for script in (
                    Path(app_builder__paths.app_dir)
                    .joinpath(scriptsdir)
                    .resolve()
                    .glob(f"pre-install.{ext}")
                ):
                    relpath = str(script.relative_to(app_builder__paths.app_dir))
                    globs_include.append(relpath)

        create_7zip_from_include_exclude_and_rename_list(
            installzip,
            app_builder__paths.app_dir,
            include_glob_list=globs_include,
            rename_list=paths_rename,
            copymode=False,
            append=False,
            sevenzip_bin=app_builder__paths.sevenz_bin,
            show_progress=False,
        )

        create_7zip_from_include_exclude_and_rename_list(
            installzip,
            app_builder__paths.app_dir / "tools" / "releases",
            include_glob_list=[programzip.name],
            copymode=True,
            append=True,
            sevenzip_bin=app_builder__paths.sevenz_bin,
            show_progress=False,
        )

    with _Path(installzip.parent.resolve()):

        open("config.txt", "wb").write(
            textwrap.dedent(
                f"""
                ;!@Install@!UTF-8!
                RunProgram="{installout.name}"
                ;!@InstallEnd@!
                """
            )
            .strip()
            .encode("utf-8")
        )

        shutil.copy(Path(app_builder__paths.sevenz_bin.parent, "7zSD.sfx"), "7zSD.sfx")
        subprocess.call(
            [
                app_builder__paths.rcedit_bin,
                "7zSD.sfx",
                "--set-icon",
                app_builder__paths.app_dir.joinpath(config["application"]["icon"]),
            ]
        )

        exefname = _Path(programzip).basename().stripext().replace(" ", "-")
        installexe = (
            _Path(programzip).dirname().joinpath(exefname + "-" + version + ".exe")
        )

        with open(installexe, "wb") as fw:
            shutil.copyfileobj(open("7zSD.sfx", "rb"), fw)
            shutil.copyfileobj(open("config.txt", "rb"), fw)
            shutil.copyfileobj(open(installzip, "rb"), fw)

        app_builder__misc.rmpath("config.txt")
        app_builder__misc.rmpath("7zSD.sfx")

    app_builder__misc.rmpath(installzip)

    # **********************************************
    # implicitely run any script named "post-build.bat" or "post-build.cmd" in dedicated locations
    for scriptsdir in [".", "bin", "src", "scripts"]:
        for ext in ("bat", "cmd"):
            for script in (
                Path(app_builder__paths.app_dir).joinpath(scriptsdir).glob(f"post-build.{ext}")
            ):
                subprocess.call(script)

            for script in (
                Path(app_builder__paths.app_dir).joinpath(scriptsdir).glob(f"post-release.{ext}")
            ):
                subprocess.call(script)


if __name__ == "__main__":
    create_releases()
