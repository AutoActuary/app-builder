import os
import shutil
import subprocess
import textwrap
from itertools import chain
from pathlib import Path
from subprocess import list2cmdline
from tempfile import TemporaryDirectory
from typing import Iterable, Mapping, Any

from path import Path as _Path

from .app_builder__misc import rmpath, mapped_zip, get_config, make_launcher
from .app_builder__paths import (
    template_dir,
    sevenz_bin,
    asset_dir,
    tools_dir,
    app_dir,
    rcedit_bin,
)
from .app_builder__versioning import git_describe, get_githuburl
from .file_pattern_7zip import create_7zip_from_include_exclude_and_rename_list
from .get_dependencies import get_dependencies
from .scripts import iter_scripts
from .util import split_dos

_create_shortcut_code_template_with_icon = r"""
if exist __prog_installpath__ (
    if exist __icon_installpath__ (
        __program_installpath_icon_installpath__
    ) else (
        __program_installpath_icon_name__
    )
) else (
    if exist __icon_installpath__ (
        __program_name_icon_installpath__
    ) else (
        __program_name_icon_name__
    )
)
"""

_create_shortcut_code_template_without_icon = r"""
if exist __prog_installpath__ (
    __program_installpath_icon_name__
) else (
    __program_name_icon_name__
)
"""


def create_shortcut_cmd_code(
    command: str,
    link_output: str | Path | None = None,
    icon: str | None = None,
) -> str:
    if icon is None:
        icon = ""

    program, *args = split_dos(command)

    if link_output is None:
        link_output = Path("%menudir%", Path(program).with_suffix("").name + ".lnk")

    def cmdstr(s: str | Path) -> str:
        wrap = list2cmdline([s])
        if (wrap[0] + wrap[-1]) != '""' and "%" in wrap:
            wrap = f'"{wrap}"'
        return wrap

    def cmdargs(args: Iterable[str | Path]) -> str:
        return cmdstr(" ".join([cmdstr(arg) for arg in args]))

    def shortcut_code(progpath: str | Path, iconpath: str | Path) -> str:
        return f"call :CREATE-SHORTCUT {cmdstr(progpath)} {cmdstr(link_output)} {cmdargs(args)} {cmdstr(iconpath)}"

    program_installpath = Path("%installdir%", program)
    icon_installpath = Path("%installdir%", icon)

    replace_dict = {
        "__prog_installpath__": program_installpath,
        "__icon_installpath__": icon_installpath,
        "__program_installpath_icon_name__": shortcut_code(
            program_installpath,
            icon,
        ),
        "__program_name_icon_name__": shortcut_code(
            program,
            icon,
        ),
        "__program_installpath_icon_installpath__": shortcut_code(
            program_installpath,
            icon_installpath,
        ),
        "__program_name_icon_installpath__": shortcut_code(
            program,
            icon_installpath,
        ),
    }

    def replace(s: str, d: Mapping[str, Any]) -> str:
        for key, val in d.items():
            s = s.replace(key, str(val))
        return s

    if icon:
        code = replace(_create_shortcut_code_template_with_icon, replace_dict)
    else:
        code = replace(_create_shortcut_code_template_without_icon, replace_dict)

    # :CREATE-SHORTCUT requires an additional indirection \" -> \""
    return code.replace(r"\"", r'\""')


def create_release(
    *,
    version: str | None = None,
) -> None:
    config = get_config()

    name = config["application"]["name"]

    if version is None:
        version = git_describe() or "unknown"

    # **********************************************
    # Make 100% sure all .bat files have \r\n endings
    # **********************************************
    def make_bat_lrln(filename: str | Path) -> None:
        filename = Path(filename)
        txt = filename.open("rb").read()
        if b"\n" in txt and not b"\r\n" in txt:
            print("Lrln conversion: ", filename)
            txt = b"\r\n".join(txt.split(b"\n"))
            filename.open("wb").write(txt)

    for path in chain(
        app_dir.rglob("*.bat"),
        app_dir.rglob("*.cmd"),
    ):
        if not path.is_dir():
            make_bat_lrln(path)

    get_dependencies()

    # **********************************************
    # Create application entry points with correct icons
    # Deprecated (want to move to more explicit launchers)
    # **********************************************
    entrypointpath = tools_dir.joinpath("entrypoint")
    os.makedirs(entrypointpath, exist_ok=True)
    if "entrypoint" in config["application"]:
        entrytxt = template_dir.joinpath("entrypoint.bat").open().read()
        entrytxt = entrytxt.replace(
            "__entrypoint__", config["application"]["entrypoint"]
        )

        if config["application"]["pause"]:
            entrytxt = entrytxt.replace("__pause__", "true")

        os.makedirs(entrypointpath, exist_ok=True)

        entrybat = entrypointpath.joinpath(name + ".bat")
        entrybat.open("w").write(entrytxt)

        entryexe = entrypointpath.joinpath(config["application"]["name"] + ".exe")
        make_launcher(
            app_dir.joinpath(config["application"]["launcher"]),
            entryexe,
            app_dir.joinpath(config["application"]["icon"]),
        )

    # **********************************************
    # Create installer / uninstaller bat
    # **********************************************
    asciibanner = open(app_dir.joinpath(config["application"]["asciibanner"])).read()
    asciibanner_lines = []
    for line in [""] + asciibanner.split("\n"):
        if line.strip() == "":
            asciibanner_lines.append("echo:")
        else:
            asciibanner_lines.append("echo " + "".join(["^" + i for i in line]))
    asciibanner = "\n".join(asciibanner_lines)

    for xstall in ["Uninstall", "Install"]:
        xnstalltxt = template_dir.joinpath(f"{xstall}er.bat").open().read()
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
            f'call :CREATE-SHORTCUT "%SYSTEMROOT%\\explorer.exe" "%installdir%\\GitHub commit {version}.lnk" "{get_githuburl()}" ""',
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
                create_shortcut_cmd_code(file)

            elif isinstance(file, list) and len(file) in (2, 3):
                cmd = file[0]
                link = Path(
                    file[1] if file[1].lower().endswith(".lnk") else file[1] + ".lnk"
                )
                if not link.expanduser().is_absolute():
                    link = Path("%menudir%", link)
                icon = None if len(file) == 2 else file[2]
                cmd = create_shortcut_cmd_code(cmd, link, icon)

            else:
                err = (
                    f"application.yaml shortcuts must either be a single string entry or a list of 2 or 3 entries, "
                    f"[<command>, <dest>, <optional icon>], got: {file}"
                )
                raise RuntimeError(err)

            cmds.append(cmd)

        txt = installout.open().read().replace("::__shortcuts__", "\n".join(cmds))
        with installout.open("w") as f:
            f.write(txt)

    # Find and run scripts named "pre-build.bat" or "pre-build.cmd" or "pre-release.bat" or "pre-release.cmd"
    for script in iter_scripts(
        base_dir=app_dir,
        sub_dirs=[".", "bin", "src", "scripts"],
        extensions=["bat", "cmd"],
        names=["pre-build", "pre-release"],
    ):
        subprocess.run(args=script, check=True)

    # **********************************************
    # Zip all the application files as one thing
    # **********************************************
    zipext = f".{config['application'].get('compression', '7z')}"
    if zipext not in (".zip", ".7z"):
        raise RuntimeError(
            f"Unknown compression type: {zipext[1:]}; required to be either 'zip' or '7z'"
        )

    programzip = tools_dir.joinpath("releases", config["application"]["name"] + zipext)

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
            [f"{asset_dir}/uninstall.ico", "./bin/uninstall.ico"],
            [f"{config['application']['icon']}", "./bin/icon.ico"],
        ]

        mapped_zip(programzip, mapping, basedir=app_dir)

        installzip = tools_dir.joinpath(
            "releases", config["application"]["name"] + "_.7z"
        )

        mapping = [
            ["./tools/entrypoint/" + installout.name, "./" + installout.name],
            ["./bin/7z.exe", "./bin/7z.exe"],
            ["./bin/7z.dll", "./bin/7z.dll"],
            ["./tools/releases/" + programzip.name, "./" + programzip.name],
        ]
        # Copy any script named "pre-install.bat/cmd" to installer
        for script in iter_scripts(
            base_dir=app_dir,
            sub_dirs=[".", "bin", "src", "scripts"],
            extensions=["bat", "cmd"],
            names=["pre-install"],
        ):
            relpath = (
                ("./" + str(script.relative_to(app_dir.resolve())))
                .replace("\\", "/")
                .replace("//", "/")
            )
            mapping.append([relpath, relpath])

        mapped_zip(installzip, mapping, basedir=app_dir, copymode=True)

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
            app_dir,
            globs_include,
            globs_exclude,
            [(i, j) for i, j in paths_rename],
            False,
            False,
            sevenz_bin,
        )

        # Add system-default things like uninstaller
        paths_rename = {
            f"tools/entrypoint/{uninstallout.name}": f"bin/{uninstallout.name}",
            f"{asset_dir}/uninstall.ico": "bin/uninstall.ico",
            f"{config['application']['icon']}": "bin/icon.ico",
        }

        create_7zip_from_include_exclude_and_rename_list(
            programzip,
            app_dir,
            include_glob_list=list(paths_rename),
            rename_list=list(paths_rename.items()),
            append=True,
            sevenzip_bin=sevenz_bin,
            show_progress=False,
        )

        # Inject a text file containing the version string.
        with TemporaryDirectory() as tmp_dir_str:
            tmp_dir = Path(tmp_dir_str)

            version_txt = tmp_dir / "version.txt"
            version_txt.open("w").write(version)

            create_7zip_from_include_exclude_and_rename_list(
                outpath=programzip,
                basedir=tmp_dir,
                include_glob_list=["version.txt"],
                append=True,
                sevenzip_bin=sevenz_bin,
                show_progress=False,
            )

        print(f"Creating 7zip installer for version {version}:")
        installzip = tools_dir.joinpath(
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
        for script in iter_scripts(
            base_dir=app_dir,
            sub_dirs=[".", "bin", "src", "scripts"],
            extensions=["bat", "cmd"],
            names=["pre-install"],
        ):
            globs_include.append(str(script.relative_to(app_dir.resolve())))

        create_7zip_from_include_exclude_and_rename_list(
            installzip,
            app_dir,
            include_glob_list=globs_include,
            rename_list=paths_rename,
            copymode=False,
            append=False,
            sevenzip_bin=sevenz_bin,
            show_progress=False,
        )

        create_7zip_from_include_exclude_and_rename_list(
            installzip,
            app_dir / "tools" / "releases",
            include_glob_list=[programzip.name],
            copymode=True,
            append=True,
            sevenzip_bin=sevenz_bin,
            show_progress=False,
        )

    with _Path(installzip.parent.resolve()):

        open("config.txt", "wb").write(textwrap.dedent(f"""
                ;!@Install@!UTF-8!
                RunProgram="{installout.name}"
                ;!@InstallEnd@!
                """).strip().encode("utf-8"))

        shutil.copy(Path(sevenz_bin.parent, "7zSD.sfx"), "7zSD.sfx")
        subprocess.call(
            [
                rcedit_bin,
                "7zSD.sfx",
                "--set-icon",
                app_dir.joinpath(config["application"]["icon"]),
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

        rmpath("config.txt")
        rmpath("7zSD.sfx")

    rmpath(installzip)

    # Find and run scripts named "post-build.bat" or "post-build.cmd" or "post-release.bat" or "post-release.cmd"
    for script in iter_scripts(
        base_dir=app_dir,
        sub_dirs=[".", "bin", "src", "scripts"],
        extensions=["bat", "cmd"],
        names=["post-build", "post-release"],
    ):
        subprocess.run(args=script, check=True)
