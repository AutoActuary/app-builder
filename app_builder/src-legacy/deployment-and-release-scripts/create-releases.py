import os
import shutil
import subprocess
import textwrap
from pathlib import Path

import sys
from locate import allow_relative_location_imports
from path import Path as _Path

allow_relative_location_imports('.')
import misc
import versioning
import app_paths

import util

config = misc.get_config()

# dash in name TODO: fix
create_dependencies = __import__('create-dependencies')

name = config['Application']['name']


# **********************************************
# Make 100% sure all .bat files have \r\n endings
# **********************************************
def make_bat_lrln(filename):
    filename = Path(filename)
    txt = filename.open('rb').read()
    if b'\n' in txt and not b'\r\n' in txt:
        print('Lrln conversion: ', filename)
        txt = b'\r\n'.join(txt.split(b'\n'))
        filename.open('wb').write(txt)


for path in app_paths.app_dir.rglob("*"):
    if not path.is_dir() and os.path.splitext(str(path))[-1].lower() == '.bat':
        make_bat_lrln(path)

# **********************************************
# Create all dependencies
# **********************************************
create_dependencies.create_all_dependencies()

# **********************************************
# Create application entry points with correct icons
# Deprecated (want to move to more explicit launchers)
# **********************************************
entrypointpath = app_paths.tools_dir.joinpath("entrypoint")
os.makedirs(entrypointpath, exist_ok=True)
if 'entrypoint' in config['Application']:
    entrytxt = app_paths.template_dir.joinpath("entrypoint.bat").open().read()
    entrytxt = entrytxt.replace("__entrypoint__", config['Application']['entrypoint'])

    if config['Application']['pause']:
        entrytxt = entrytxt.replace("__pause__", "true")

    os.makedirs(entrypointpath, exist_ok=True)

    entrybat = entrypointpath.joinpath(name + ".bat")
    entrybat.open("w").write(
        entrytxt
    )

    entryexe = entrypointpath.joinpath(config['Application']['name'] + ".exe")
    misc.make_launcher(app_paths.app_dir.joinpath(config['Application']['launcher']),
                       entryexe,
                       app_paths.app_dir.joinpath(config['Application']['icon'])
                       )

# **********************************************
# Create installer / uninstaller bat
# **********************************************
asciibanner = open(app_paths.app_dir.joinpath(config['Application']['asciibanner'])).read()
asciibanner_lines = []
for line in [""] + asciibanner.split('\n'):
    if line.strip() == "":
        asciibanner_lines.append("echo:")
    else:
        asciibanner_lines.append("echo " + "".join(["^" + i for i in line]))
asciibanner = "\n".join(asciibanner_lines)

for xstall in ["Uninstall", "Install"]:
    xnstalltxt = app_paths.template_dir.joinpath(f"{xstall}er.bat").open().read()
    xnstalltxt = xnstalltxt.replace("__name__", name)
    xnstalltxt = xnstalltxt.replace("__installdir__", config['Application']['installdir'])
    menu_name = config['Application']["menuname"] \
        if "menuname" in config['Application'] \
        else rf"AutoActuary\{config['Application']['name']}"
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
txt = installout.open().read().replace(
    "::__githuburl__",
    f'call :CREATE-SHORTCUT "%SYSTEMROOT%\\explorer.exe" "%installdir%\\GitHub commit {versioning.get_gitversion()}.lnk" "{versioning.get_githuburl()}" ""'
)
with installout.open("w") as f: f.write(txt)

# **********************************************
# Add shortcuts to installer (this is quite a hack)
# **********************************************
if "startmenu" in config['Application']:
    cmds = []
    for file in config["Application"]["startmenu"]:
        file = _Path(file).abspath().relpath()
        link = file.basename().splitext()[0] + '.lnk'
        cmds.append(f'call :CREATE-SHORTCUT "%installdir%\\{file}" "%menudir%\\{link}"')
    txt = installout.open().read().replace("::__shortcuts__", '\n'.join(cmds))
    with installout.open("w") as f:
        f.write(txt)

# **********************************************
# If there are any scripts that should be run before
# compressing everything into an exe, do it now
# **********************************************
run_external_script = False
for i, arg in enumerate(sys.argv):
    if arg.lower() == '--build-script' or arg.lower() == '-s':
        run_external_script = sys.argv[i + 1:]

if run_external_script:
    with _Path(app_paths.app_dir):
        run_external_script[0] = Path(run_external_script[0]).resolve()
    subprocess.call(run_external_script)

# **********************************************
# implicitely run any script named "pre-build.bat" or "pre-build.cmd" in dedicated locations
for scriptsdir in [".", "bin", "src", "scripts"]:
    for ext in ("bat", "cmd"):
        for script in Path(app_paths.app_dir).joinpath(scriptsdir).glob(f"pre-build.{ext}"):
            subprocess.call(script)
        for script in Path(app_paths.app_dir).joinpath(scriptsdir).glob(f"pre-release.{ext}"):
            subprocess.call(script)

# **********************************************
# Zip all the application files as one thing
# **********************************************
programzip = app_paths.tools_dir.joinpath('releases', config['Application']['name'] + ".7z")

data_fields = {'programdata', 'data'}.intersection(config['Application'])
if len(data_fields) == 2:
    raise RuntimeError("Application.yaml cannot have a 'data' field and a legacy 'programdata' together - choose one.")

if len(data_fields) == 0:
    raise RuntimeError("Application.yaml must have either a 'data' field or a legacy 'programdata' field.")

# **********************************************
# Legacy zip creation
# **********************************************
if data_fields == {'programdata'}:
    mapping = config['Application']['programdata'] + [
        ["./tools/entrypoint/" + uninstallout.name, "./bin/" + uninstallout.name],
        [f"{app_paths.asset_dir}/uninstall.ico", "./bin/uninstall.ico"]]


    misc.mapped_zip(programzip,
                    mapping,
                    basedir=app_paths.app_dir)

    installzip = app_paths.tools_dir.joinpath('releases', config['Application']['name'] + "_.7z")

    mapping = [
        ["./tools/entrypoint/" + installout.name, "./" + installout.name],
        ["./bin/7z.exe", "./bin/7z.exe"],
        ["./bin/7z.dll", "./bin/7z.dll"],
        ["./tools/releases/" + programzip.name, "./" + programzip.name]
    ]
    # Copy any script named "pre-install.bat/cmd" to installer
    for scriptsdir in [".", "bin", "src", "scripts"]:
        for ext in ("bat", "cmd"):
            for script in Path(app_paths.app_dir).joinpath(scriptsdir).resolve().glob(f"pre-install.{ext}"):
                relpath = ("./"+str(script.relative_to(app_paths.app_dir))).replace("\\", "/").replace("//", "/")
                mapping.append([relpath, relpath])

    misc.mapped_zip(installzip,
                    mapping,
                    basedir=app_paths.app_dir,
                    copymode=True)

# **********************************************
# New zip creation
# **********************************************
if data_fields == {'data'}:
    raise NotImplementedError("Application.yaml new 'data' field.")


with _Path(installzip.parent.resolve()):
    open("config.txt", "wb").write(
        textwrap.dedent(
            f"""
            ;!@Install@!UTF-8!
            RunProgram="{installout.name}"
            ;!@InstallEnd@!
            """
        ).strip().encode("utf-8")
    )

    shutil.copy(Path(app_paths.sevenz_bin.parent, '7zSD.sfx'), '7zSD.sfx')
    subprocess.call([
        app_paths.rcedit_bin,
        '7zSD.sfx',
        "--set-icon",
        app_paths.app_dir.joinpath(config['Application']['icon'])
    ])

    exefname = _Path(programzip).basename().stripext().replace(" ", "-")
    installexe = _Path(programzip).dirname().joinpath(exefname + "-" + versioning.get_gitversion() + ".exe")

    with open(installexe, 'wb') as fw:
        shutil.copyfileobj(open('7zSD.sfx', 'rb'), fw)
        shutil.copyfileobj(open("config.txt", 'rb'), fw)
        shutil.copyfileobj(open(installzip, 'rb'), fw)

    misc.rmpath("config.txt")
    misc.rmpath('7zSD.sfx')

misc.rmpath(installzip)


# **********************************************
# implicitely run any script named "post-build.bat" or "post-build.cmd" in dedicated locations
for scriptsdir in [".", "bin", "src", "scripts"]:
    for ext in ("bat", "cmd"):
        for script in Path(app_paths.app_dir).joinpath(scriptsdir).glob(f"post-build.{ext}"):
            subprocess.call(script)
        for script in Path(app_paths.app_dir).joinpath(scriptsdir).glob(f"post-release.{ext}"):
            subprocess.call(script)