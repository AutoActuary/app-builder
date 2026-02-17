import shutil
import subprocess
from pathlib import Path
from typing import Any, List, Sequence


def sh_lines(command: str | Sequence[str], **kwargs: Any) -> List[str]:
    lst = (
        subprocess.check_output(command, shell=isinstance(command, str), **kwargs)
        .decode("utf-8")
        .strip()
        .split("\n")
    )
    return [] if lst == [""] else [i.strip() for i in lst]


def sh_quiet(command: str | Sequence[str]) -> int:
    return subprocess.call(
        command,
        shell=isinstance(command, str),
        stderr=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
    )


def copy(src: str | Path, dst: str | Path) -> str | Path:
    if Path(src).is_file():
        return shutil.copy2(src, dst)
    else:
        return shutil.copytree(src, dst, dirs_exist_ok=True)
