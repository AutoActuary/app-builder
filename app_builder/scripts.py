from pathlib import Path
from typing import Collection, Generator


def iter_scripts(
    *,
    base_dir: Path,
    sub_dirs: Collection[str | Path],
    extensions: Collection[str],
    names: Collection[str],
) -> Generator[Path, None, None]:
    """
    Find files (e.g. scripts) with given names and extensions in given subdirectories of a base directory,
    and yield their resolved paths.

    Args:
        base_dir: The base directory to search within.
        sub_dirs: The subdirectory names (relative to base_dir) to search in.
        extensions: The file extensions (without the dot) to look for.
        names: The file names (without extension) to look for.

    Yields:
        Resolved paths of found scripts.
    """
    if isinstance(names, str):
        names = [names]

    for sub_dir in sub_dirs:
        for ext in extensions:
            for name in names:
                for script in base_dir.joinpath(sub_dir).glob(f"{name}.{ext}"):
                    yield script.resolve()
