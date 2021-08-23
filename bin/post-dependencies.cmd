1<2# : ^
r'''
    @echo off
    "%~dp0python\python.exe" "%~f0" %*
    if /i "%comspec% /c ``%~0` `" equ "%cmdcmdline:"=`%" pause
    goto :eof
'''

from pathlib import Path
import urllib
from urllib.request import urlopen
import sys
from json import loads
import tempfile
import subprocess

thisdir = Path(__file__).resolve().parent
gitexe = thisdir.joinpath("git", "bin", "git.exe")

if not gitexe.is_file():
    
    giturl = None

    d = loads(urlopen('https://api.github.com/repos/git-for-windows/git/releases/latest').read().decode("utf-8"))
    for s in d['assets']:
        if 'browser_download_url' in s:
            url = s['browser_download_url']
            if url.endswith('.7z.exe') and "64-bit" in url:
                giturl = url

    with tempfile.TemporaryDirectory() as tmp:
        dlpath = Path(tmp).joinpath(Path(giturl).name)
        print(f"Downloading git from '{giturl}'")
        urllib.request.urlretrieve(url, dlpath)
        subprocess.call([thisdir.joinpath('..', 'src-legacy', 'bin', '7z.exe'), "x", str(dlpath), f'-o{thisdir.joinpath("git")}', '-y'], stdout=subprocess.DEVNULL)

