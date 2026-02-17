import json
import re
import subprocess
from pathlib import Path

import requests
from bs4 import BeautifulSoup


def pattern_match_version(pattern: str, version: str) -> bool:
    version_no_prerelease = re.compile(r"\d+(\.\d+)*$")

    if version_no_prerelease.match(version):
        return version.startswith(pattern)
    return False


def get_winpython_version_link(version: str | None) -> str | None:
    """
    >>> get_winpython_version_link("3.8.2")
    'https://github.com/winpython/winpython/releases/download/2.3.20200319/Winpython64-3.8.2.0dot.exe'

    >>> get_winpython_version_link(None) # doctest: +ELLIPSIS
    'https://github.com/winpython/winpython/releases/download/.../WinPython...exe'
    """

    if version is None:
        version = ""

    page = 1
    while True:
        url = f"https://api.github.com/repos/winpython/winpython/releases?page={page}&per_page=100"
        response = json.loads(requests.get(url).text)
        if not response:  # Break the loop if no data is returned
            break

        for release in response:
            for asset in release["assets"]:
                n = asset["name"].lower()
                if n.endswith("dot.exe"):
                    asset_version = n.replace("winpython64-", "").replace("dot.exe", "")
                    if pattern_match_version(version, asset_version):
                        result = asset["browser_download_url"]
                        assert isinstance(result, str)
                        return result

        page += 1

    return None


def test_version_of_python_exe_using_subprocess(
    path_to_python_exe: str | Path,
    pattern: str | None,
) -> bool:
    """
    #>>> test_version_of_python_exe_using_subprocess("python", "3.8")
    #True
    """
    if pattern is None:
        pattern = ""

    version_exe = (
        subprocess.check_output([path_to_python_exe, "-V"], stderr=subprocess.STDOUT)
        .decode("utf-8")
        .split()[1]
    )

    return pattern_match_version(pattern, version_exe)


def get_r_version_link(version: str | None) -> str:
    """
    >>> get_r_version_link("3.6.3")
    'https://cran-archive.r-project.org/bin/windows/base/old/3.6.3/R-3.6.3-win.exe'
    """
    if version is None:
        version = ""

    version_match = re.compile(r"\d+(\.\d+)*$")
    r_archive_url = "https://cran.r-project.org/bin/windows/base/old"

    response = requests.get(r_archive_url)
    soup = BeautifulSoup(response.text, "html.parser")

    links = soup.find_all("a")
    links = [link.get("href") for link in links]

    # get the links that match the version pattern
    links = [link for link in links if pattern_match_version(version, Path(link).name)]
    links = [f"{r_archive_url}/{i}" if not i.startswith("http") else i for i in links]
    link = links[0]

    # get the html page for link and get the exe download link
    response = requests.get(link)
    soup = BeautifulSoup(response.text, "html.parser")
    links = soup.find_all("a")
    links = [link.get("href") for link in links]
    links = [l if l.startswith("http") else f"{link}/{Path(l).name}" for l in links]
    links = [link for link in links if link.endswith(".exe")]

    result = links[0]
    assert isinstance(result, str)
    return result


def test_version_of_r_exe_using_subprocess(
    path_to_r_exe: str | Path, pattern: str | None
) -> bool:
    """
    #>>> test_version_of_r_exe_using_subprocess("C:/Users/simon/devel/all-life-vif/bin/r/bin/x64/R.exe", "4.2")
    #True
    """
    if pattern is None:
        pattern = ""

    version_exe = (
        subprocess.check_output([path_to_r_exe, "--version"], stderr=subprocess.STDOUT)
        .decode("utf-8")
        .split("version")[1]
        .strip()
        .split()[0]
    )
    return pattern_match_version(pattern, version_exe)
