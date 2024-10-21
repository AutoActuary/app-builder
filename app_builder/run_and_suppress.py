import subprocess
import re
from typing import List
import sys


def run_and_suppress(
    command, line_suppress_regex: List[re.Pattern], check=True, **kwargs
):
    """Executes a python command with real-time output streaming and raises exceptions if check=True.

    Args:
        command (list): The Python command to execute as a list.
        check (bool): If True, raises CalledProcessError on failure.
        kwargs: Additional arguments for subprocess.Popen.

    Raises:
        subprocess.CalledProcessError: If check is True and the command fails.

    """
    # Ensure default arguments for subprocess.Popen
    kwargs.setdefault("stdout", subprocess.PIPE)
    kwargs.setdefault("stderr", subprocess.STDOUT)

    # Start the subprocess
    process = subprocess.Popen(command, **kwargs)

    # Stream the output in real time
    nothing_line_re = re.compile(r"^(\s*\r)|(\s*\n)|()$")
    first_output = [True]
    nothing_lines = []
    buffer = []

    def write_buffer():
        line = (b"".join(buffer)).decode("utf-8")
        buffer.clear()

        for re_suppress in line_suppress_regex:
            if re.match(re_suppress, line):
                return

        if re.match(nothing_line_re, line):
            nothing_lines.append(line)
        else:
            if first_output[0]:
                nothing_lines.clear()

            sys.stdout.write("".join([*nothing_lines[-1:], line]))
            nothing_lines.clear()
            first_output[0] = False

    for char in iter(lambda: process.stdout.read(1), b""):
        buffer.append(char)
        if char in (b"\n", b"\r"):
            write_buffer()

    write_buffer()
    if not first_output[0] and nothing_lines:
        print()

    # Wait for the process to complete
    returncode = process.wait()

    # If check is True and the return code is non-zero, raise an exception
    if check and returncode != 0:
        raise subprocess.CalledProcessError(returncode, command)


_suppress_re_list_7z = [
    re.compile(r"^7-Zip .* Copyright \(c\) 1999.* Igor Pavlov \: .*$"),
    re.compile(r"^Open archive\: .*$"),
    re.compile(r"^\-\-.*$"),
    re.compile(r"^Path \= .*$"),
    re.compile(r"^Type \= .*$"),
    re.compile(r"^Physical Size \= .*$"),
    re.compile(r"^Headers Size \= .*$"),
    re.compile(r"^Method \= .*$"),
    re.compile(r"^Solid \= .*$"),
    re.compile(r"^Blocks \= .*$"),
    re.compile(r"^Scanning the drive:.*$"),
    re.compile(r"^.* files*, .* bytes.*$"),
    re.compile(r"^Updating archive\: .*$"),
    re.compile(r"^Creating archive\: .*$"),
    re.compile(r"^Add new data to archive\: .*$"),
    re.compile(r"^ .*M Scan .*$"),
    re.compile(r"^Files read from disk\: .*$"),
    re.compile(r"^Archive size\: .*$"),
    re.compile(r"^Everything is Ok.*$"),
    re.compile(r"^  0\%.*$"),
    re.compile(r"^Extract .*$"),
    re.compile(r"^Scanning the drive for archives\:.*$"),
    re.compile(r"^Extracting archive\:.*$"),
    re.compile(r"^Offset\s+=\s+\d+$"),
    re.compile(r"^Folders\:\s+\d+"),
    re.compile(r"^Files\:\s+\d+"),
    re.compile(r"^Size\:\s+\d+"),
    re.compile(r"^Compressed\:\s+\d+"),
]


def run_and_suppress_7z(command, **kwargs):
    return run_and_suppress(command, _suppress_re_list_7z, **kwargs)


_suppress_re_list_pip = [
    re.compile(r"^Looking in indexes\: .*$"),
    re.compile(r"^Requirement already satisfied\: .*$"),
    re.compile(r"^Collecting .*$"),
    re.compile(r"^\s*Using cached .*$"),
    re.compile(r"^Installing collected packages\:.*"),
    re.compile(r"^\s*Attempting uninstall\:.*"),
    re.compile(r"^\s*Found existing installation\:.*"),
    re.compile(r"^\s*Uninstalling .*"),
    re.compile(r"^\s*Successfully uninstalled.*"),
    re.compile(r"^Successfully installed.*"),
    re.compile(r"^Installing collected packages\:.*"),
]


def run_and_suppress_pip(command, **kwargs):
    return run_and_suppress(command, _suppress_re_list_pip, **kwargs)
