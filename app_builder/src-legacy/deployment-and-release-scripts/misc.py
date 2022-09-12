import os
import shutil
import subprocess
import sys
import tempfile
from contextlib import suppress
from typing import Union, Callable
import textwrap
import collections.abc
import toml

import yaml
from locate import allow_relative_location_imports
import locate
from path import Path as _Path
from pathlib import Path

allow_relative_location_imports('.')
import app_paths
import python_and_r_sources as prs


def nested_update(d, u):
    """
    Update a nested dictionary structure with another nested dictionary structure.
    From https://stackoverflow.com/a/3233356/1490584

    Test a simple example
    >>> dictionary1 = {'level1': {'level2': {'levelA': 0, 'levelB': 1}}, 'alsolevel1': 1}
    >>> update = {'level1': {'level2': {'levelB':10}}}
    >>> nested_update(dictionary1, update)
    {'level1': {'level2': {'levelA': 0, 'levelB': 10}}, 'alsolevel1': 1}
    """
    for k, v in u.items():
        if isinstance(v, collections.abc.Mapping):
            d[k] = nested_update(d.get(k, {}), v)
        else:
            d[k] = v
    return d


def sh(cmd, std_err_to_stdout=False):
    if std_err_to_stdout:
        return subprocess.check_output(cmd, stderr=subprocess.STDOUT, shell=True).decode('utf-8').strip()
    else:
        return subprocess.check_output(cmd, shell=True).decode('utf-8').strip()


def get_config():
    config = yaml.load(
        app_paths.app_dir.joinpath("Application.yaml").open().read(),
        Loader=yaml.FullLoader
    )

    # turn empty sections into empty lists
    for i, j in config.items():
        if j is None:
            config[i] = {}

    # lowercase first level of entry keys (for backwards compatibility transition to only lowercase
    config = {(i.lower() if isinstance(i, str) else i) : j for i, j in config.items()}

    return config


def move_tree(source, dest):
    """
    Move a tree from source to destination
    """
    source = os.path.abspath(source)
    dest = os.path.abspath(dest)

    os.makedirs(dest, exist_ok=True)

    for ndir, dirs, files in os.walk(source):
        for d in dirs:
            absd = os.path.abspath(ndir + "/" + d)
            os.makedirs(dest + '/' + absd[len(source):], exist_ok=True)

        for f in files:
            absf = os.path.abspath(ndir + "/" + f)
            os.rename(absf, dest + '/' + absf[len(source):])
    rmtree(source)


def rmtree(
        path: Union[str, Path], ignore_errors: bool = False, onerror: Callable = None
) -> None:
    """
    Mimicks shutil.rmtree, but add support for deleting read-only files

    >>> import tempfile
    >>> with tempfile.TemporaryDirectory() as tdir:
    ...     os.makedirs(Path(tdir, "tmp"))
    ...     with Path(tdir, "tmp", "f1").open("w") as f:
    ...         _ = f.write("tmp")
    ...     os.chmod(Path(tdir, "tmp", "f1"), stat.S_IREAD|stat.S_IRGRP|stat.S_IROTH)
    ...     try:
    ...         shutil.rmtree(Path(tdir, "tmp"))
    ...     except Exception as e:
    ...         print(e) # doctest: +ELLIPSIS
    ...     rmtree(Path(tdir, "tmp"))
    [WinError 5] Access is denied: '...f1'

    """

    def _onerror(_func: Callable, _path: Union[str, Path], _exc_info) -> None:
        # Is the error an access error ?
        try:
            os.chmod(_path, os.stat.S_IWUSR)
            _func(_path)
        except Exception as e:
            if ignore_errors:
                pass
            elif onerror is not None:
                onerror(_func, _path, sys.exc_info())
            else:
                raise

    return shutil.rmtree(path, False, _onerror)



def rmtree_exist_ok(dirname):
    """
    Rmtree without exist_ok error
    """
    if os.path.isdir(dirname):
        rmtree(dirname)


def rmpath(pathname):
    """
    Like rmtree, but file/tree agnostic
    """
    rmtree_exist_ok(pathname)
    try:
        os.remove(pathname)
    except FileNotFoundError:
        pass


def cppath(srce, dest):
    """
    File/tree agnostic copy
    """
    os.makedirs(_Path(dest).dirname(), exist_ok=True)
    if _Path(srce).isdir():
        shutil.copytree(srce, dest)
    else:
        shutil.copy(srce, dest)


def unnest_dir(dirname):
    r"""
    de-nesting single direcotry paths:
        From:
        (destdir)--(nestdir)--(dira)
                           \__(dirb)
        To:
        (destdir)--(dira)
                \__(dirb)
    """

    if len(os.listdir(dirname)) == 1:
        deepdir = dirname + '/' + os.listdir(dirname)[0]
        if os.path.isdir(dirname):
            move_tree(deepdir, dirname)
            return True

    return False


def extract_file(archive, destdir, force=True):
    print(f'Extract {archive} to {destdir}')

    if force:
        rmtree_exist_ok(destdir)

    subprocess.call([
        app_paths.sevenz_bin,
        "x",
        "-y",
        f"-o{_Path(destdir).abspath()}",
        _Path(archive).abspath()
    ])


def flatextract_file(archive, destdir, force=True):
    r'''
    Make sure it didn't extract to a single directory,
    by de-nesting single direcotry paths:
        From:
        (destdir)--(nestdir)--(dira)
                           \__(dirb)
        To:
        (destdir)--(dira)
                \__(dirb)
    '''
    extract_file(archive, destdir, force)
    unnest_dir(destdir)


def download(dlurl, dest):
    dest = Path(dest)
    print(f'Download {dlurl} to {dest}')

    tdir_base = Path(tempfile.gettempdir(), "app-builder-downloads")
    os.makedirs(tdir_base, exist_ok=True)
    os.makedirs(dest.parent, exist_ok=True)

    with tempfile.TemporaryDirectory(dir=tdir_base) as tdir:
        tmploc = Path(tdir, dest.name)

        if subprocess.call([app_paths.ps_bin, '-Command', 'gcm Invoke-WebRequest'],
                           stdout=subprocess.DEVNULL,
                           stderr=subprocess.DEVNULL) == 0:

            # New Powershell method is available
            subprocess.call([
                app_paths.ps_bin,
                "-Command",
                f"Invoke-WebRequest '{dlurl}' -OutFile '{tmploc}'"
            ])

        else:
            # Only old Powershell method is available
            subprocess.call([
                app_paths.ps_bin,
                "-Command",
                f"(New-Object Net.WebClient).DownloadFile('{dlurl}', '{tmploc}')"
            ])

        if dest.exists():
            os.remove(dest)

        # Only move after successful download
        shutil.move(tmploc, dest)


def islistlike(x):
    try:
        "" + x
        return False

    except:
        pass

    try:
        for i in x:
            return True
    except:
        return False


def slugify(url):
    return url.replace('/', "-").replace(':', "").replace("?", "-")


def get_program(download_page,
                prefix='',
                outdir='',
                link_tester=lambda x: x.startswith('http'),
                link_chooser=lambda lst: lst[0],
                extract_tester=lambda: True,
                extractor=lambda x, y: flatextract_file(x, y)
                ):
    # ************************************************
    # Get download url
    # ************************************************
    url = download_page
    dump = app_paths.temp_dir.joinpath(slugify(url))

    # maybe we already have this information
    if dump.is_file():
        dllinks = [prefix + i for i in dump.open(errors='ignore').read().split('"') if link_tester(i)]
        if not dllinks:
            download(url, dump)
    else:
        download(url, dump)

    dllinks = [prefix + i for i in dump.open(errors='ignore').read().split('"') if link_tester(i)]
    dlurl = link_chooser(dllinks)

    filename = (dlurl if dlurl[-1] != '/' else dlurl[:-1]).split('/')[-1].split("?")[0]

    # ************************************************
    # Download program
    # ************************************************
    prevdl = True
    if filename not in os.listdir(app_paths.temp_dir):
        prevdl = False
        download(dlurl, app_paths.temp_dir.joinpath(filename))
    else:
        print(f'All good, file {filename} already downloaded')

    # ************************************************
    # Extract the file
    # ************************************************
    # os.makedirs(outdir, exist_ok=True)
    if not prevdl or not extract_tester():
        extractor(app_paths.temp_dir.joinpath(filename).resolve(), _Path(outdir).abspath())


def get_pandoc():
    get_program(
        "https://github.com/jgm/pandoc/releases/",
        "https://github.com/",
        app_paths.app_dir.joinpath('bin', 'pandoc'),
        link_tester=lambda x: '/pandoc-' in x and x.endswith('86_64.zip'),
        extract_tester=lambda: app_paths.app_dir.joinpath('bin', 'pandoc', "pandoc.exe").is_file(),
    )


def get_python(version):

    if app_paths.python_bin.exists() and prs.test_version_of_python_exe_using_subprocess(app_paths.python_bin, version):
        return

    rmtree_exist_ok(app_paths.py_dir)
    url = prs.get_winpython_version_link(version)
    filename = Path(url).name
    dlpath = app_paths.temp_dir.joinpath(filename)
    if not dlpath.exists():
        download(url, dlpath)

    with tempfile.TemporaryDirectory() as tdir:
        extract_file(dlpath, tdir)
        pydir = next(Path(tdir).glob("*/python-*"))
        shutil.move(pydir, app_paths.py_dir)



def get_julia():
    # Escape automatic installation
    if not app_paths.app_dir.joinpath('bin', 'julia', 'app-builder-dont-overwrite-julia.txt').is_file():

        get_program(
            "https://julialang.org/downloads",
            "",
            app_paths.app_dir.joinpath('bin', 'julia', 'julia'),
            link_tester=lambda x: 'bin/winnt/x64/' in x and x.endswith('-win64.zip'),
            extract_tester=lambda: (app_paths.app_dir.joinpath('bin', 'julia', 'julia', 'bin', 'julia.exe').is_file())
        )

        # Add our personalised launcher wrapper to the mix
        shutil.copy2(app_paths.asset_dir.joinpath("launcher-julia.exe"), app_paths.julia_bin)

        julia_env = app_paths.app_dir.joinpath('bin', 'julia', "activate-julia-environment.cmd")

        open(julia_env, "w").write(textwrap.dedent(r"""
            @echo off
            
            :: Set portable specific julia paths
            if "%julia-activated%" neq "1" (
            
                set "JULIA_DEPOT_PATH=%~dp0localdepot"
                set "PYTHON=%~dp0..\python\python.exe"
                set "PATH=%~dp0julia\bin;%~dp0..\python;%PATH%"
            
                set "julia-activated=1"
            )
            
            :: Get the previous run path of Julia
            if exist "%JULIA_DEPOT_PATH%\lastpath.txt" (
                set /p lastpath=<"%JULIA_DEPOT_PATH%\lastpath.txt"
            )
            
            :: Test if PyCall wants a recompilation
            if "%lastpath%" neq "%JULIA_DEPOT_PATH%" (
            
                REM Remove all Conda and PyCall related files
                powershell -Command "Remove-Item -LiteralPath '%JULIA_DEPOT_PATH%\conda'         -Force -Recurse" > nul 2>&1
                powershell -Command "Remove-Item -LiteralPath '%JULIA_DEPOT_PATH%\prefs'         -Force -Recurse" > nul 2>&1
                powershell -Command "Remove-Item -LiteralPath '%JULIA_DEPOT_PATH%\compiled'      -Force -Recurse" > nul 2>&1
                powershell -Command "Remove-Item -LiteralPath '%JULIA_DEPOT_PATH%\scratchspaces' -Force -Recurse" > nul 2>&1
            
                for /f "delims=" %%a in ('dir /b /ad "%JULIA_DEPOT_PATH%\packages\PyCall\*"') do (
                    powershell -Command "Remove-Item -LiteralPath '%JULIA_DEPOT_PATH%\packages\PyCall\%%a\deps\deps.jl' -Force" > nul 2>&1
                )
                for /f "delims=" %%a in ('dir /b /ad "%JULIA_DEPOT_PATH%\packages\Conda\*"') do (
                    powershell -Command "Remove-Item -LiteralPath '%JULIA_DEPOT_PATH%\packages\Conda\%%a\deps\deps.jl' -Force" > nul 2>&1
                )
            
                if exist "%JULIA_DEPOT_PATH%\packages\PyCall" (
                    call "%~dp0julia\bin\julia.exe" -e "using Pkg; Pkg.build(\"PyCall\");"
                )
            )
            
            :: Write new path (only if we are error free)
            if "%lastpath%" neq "%JULIA_DEPOT_PATH%" if "%errorlevel%" equ "0" (
                echo %JULIA_DEPOT_PATH%>"%JULIA_DEPOT_PATH%\lastpath.txt"
            )
            """))

        startup = app_paths.app_dir.joinpath('bin', 'julia', 'localdepot', 'config', 'startup.jl')
        os.makedirs(startup.parent, exist_ok=True)

        startup.open("w").write(textwrap.dedent(r"""        
            ENV["JULIA_PKG_SERVER"] = ""
            
            # Force installation of packages
            for _ in true
                function lazy_add(pkgsym)
                if !(isdir(joinpath(@__DIR__, "..", "packages", String(pkgsym))))
                    @eval using Pkg
                    Pkg.add(String(pkgsym))
                end
            end
            
            lazy_add(:Revise)
            lazy_add(:OhMyREPL)
            end
            
            # Force installation and inclusion of packages at REPL
            Base.atreplinit() do _
                function add_and_use(pkgsym)
                    try
                        @eval using $pkgsym
                        return true
                    catch e
                        @eval using Pkg
                        Pkg.add(String(pkgsym))
                        @eval using $pkgsym
                    end
                end
                
                add_and_use(:Revise)
                add_and_use(:OhMyREPL)
            end
            """))


def juliainstall_dependencies(libdict: dict):

    envs = app_paths.julia_dir.joinpath("localdepot", "environments")

    for path in envs.glob('v*.*/Project.toml'):
        reqs = toml.load(path)
        nested_update(reqs, libdict)
        with path.open("w") as f:
            toml.dump(reqs, f)

    subprocess.call([app_paths.julia_bin, "-e", "using Pkg; Pkg.resolve(); Pkg.instantiate()"])


def pipinstall(libname):
    subprocess.call([app_paths.python_bin, "-E", "-m", "pip", 'install', libname, '--no-warn-script-location'])


def pipinstall_requirements(liblist):
    reqfile = tempfile.mktemp(suffix=".txt")
    open(reqfile, "w").write(
        "\n".join(liblist)
    )
    subprocess.call([app_paths.python_bin, "-E", "-m", "pip", 'install', '-r', reqfile, '--no-warn-script-location'])
    os.unlink(reqfile)


def is_pip(pname):
    try:
        pipanswer = subprocess.check_output([app_paths.py_dir.joinpath(r'scripts\pip'), 'show', pname]).decode('utf-8')
    except:
        return False

    if 'WARNING: Package(s) not found:' in pipanswer:
        return False

    return True


def get_r(version):

    if app_paths.r_bin.exists() and prs.test_version_of_r_exe_using_subprocess(app_paths.r_bin, version):
        return

    rmtree_exist_ok(app_paths.r_dir)
    url = prs.get_r_version_link(version)
    filename = Path(url).name
    dlpath = app_paths.temp_dir.joinpath(filename)
    if not dlpath.exists():
        download(url, dlpath)

    subprocess.call([dlpath, "/SUPPRESSMSGBOXES", "/SP-", '/VERYSILENT', f'/DIR={app_paths.r_dir}', '/COMPONENTS=main,x64', "/NOICONS"])


def get_mintty(icon: Union[_Path, None] = None):
    try:
        gitpaths = [
            i.strip()
            for i in subprocess.check_output("where git").decode("utf-8").split("\n")
            if i.strip() != ""
        ]
    except subprocess.CalledProcessError:
        raise FileNotFoundError("Cannot copy Git's mintty: git.exe not in Window path.")

    gitpath = _Path(gitpaths[0])
    gitbase = gitpath.parent.parent
    if gitbase.name == "mingw64":  # if running from git shell
        gitbase = gitbase.parent

    srcdir = gitbase.joinpath("usr", "bin")

    def intable(txt):
        with suppress(ValueError):
            int(txt)
            return True
        return False

    msysdll = [
        i for i in srcdir.glob("*")
        if (n := i.name).startswith("msys-")
           and n.endswith(".dll")
           and intable(n.split("msys-")[1].split(".")[0])
    ][0]

    mintty_files = [
        msysdll,
        srcdir.joinpath("mintty.exe"),
        srcdir.joinpath("cygwin-console-helper.exe")
    ]

    mintty_path = app_paths.app_dir.joinpath('bin', 'mintty', 'usr', 'bin')
    os.makedirs(mintty_path, exist_ok=True)

    with mintty_path.parent.parent.joinpath("readme.txt").open("w") as fw:
        fw.write("All files are copied from an installation of git-scm.com.\n"
                 r"Note the directory structure of mintty.exe must follow `...\usr\bin\mintty.exe`")

    for i in mintty_files:
        if not (j := mintty_path.joinpath(i.name)).exists():
            shutil.copy2(i, j)

    if icon is not None:
        subprocess.call([
            app_paths.rcedit_bin,
            str(mintty_path.joinpath("mintty.exe")),
            "--set-icon", str(_Path(icon).abspath()),
        ])


def rinstall(libname):
    subprocess.call([
        app_paths.r_bin,
        '-e',
        f"if(! '{libname}' %in% installed.packages()){{ install.packages('{libname}', repos='http://cran.us.r-project.org') }}"])


def mapped_zip(zippath,
               mapping,
               basedir='.',
               copymode=False):
    """
    This ended up being way more complicated that I ever wished it to be.
    """

    zip_out = _Path(zippath).abspath()
    try:
        os.remove(zip_out)
    except FileNotFoundError:
        pass

    tmp_out = _Path(tempfile.mktemp(prefix="zipdump"))
    flist_local = _Path(tempfile.mktemp(prefix="ziplist", suffix=".txt"))

    with open(flist_local, 'w') as f:
        pass

    rmpath(tmp_out)
    os.makedirs(tmp_out, exist_ok=True)

    with _Path(basedir):
        for i, j in mapping:

            # If the mapping is 1:1, add filename to filelist mapping
            if _Path(i).abspath().lower() == _Path(j).abspath().lower():
                with open(flist_local, 'a') as f:
                    f.write(_Path(j).relpath() + '\n')

            # If not 1:1, make a copy of the file
            else:
                # Files are not 1:1 mapping, will have to do copy trick
                i, j = (_Path(i.strip()),
                        tmp_out.joinpath(j.strip()).abspath())

                # Another gotcha...
                # if directory exist, then copy everything within the directory
                try:
                    cppath(i, j)
                except FileExistsError:
                    for ii in os.listdir(i):
                        ii, jj = (i.joinpath(ii),
                                  j.joinpath(ii))
                        cppath(ii, jj)


        # Lastly, zip everything from 1:1 mapping, then from the copied non-1:1 mapping
        # https://stackoverflow.com/a/28474846
        mode = ["-mx0"] if copymode else ["-t7z", "-m0=lzma2:d1024m", "-mx=9", "-aoa", "-mfb=64", "-md=32m", "-ms=on"]

        subprocess.call([app_paths.sevenz_bin, 'a', '-y'] + mode + [zip_out, f"@{flist_local}"])

        with _Path(tmp_out):
            subprocess.call([app_paths.sevenz_bin, 'a', '-y'] + mode + [zip_out, r".\*"])

    rmpath(tmp_out)


def make_launcher(template,
                  dest,
                  icon):
    shutil.copy(template, dest)
    subprocess.call([app_paths.rcedit_bin,
                     dest,
                     "--set-icon", icon
                     ])
