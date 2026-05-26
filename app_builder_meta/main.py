from __future__ import annotations

import sys

from .dispatch import dispatch


def main(argv: list[str] | None = None) -> int:
    return dispatch(sys.argv[1:] if argv is None else argv)
