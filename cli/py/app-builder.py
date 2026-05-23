from __future__ import annotations

import sys
from pathlib import Path

repo_root = Path(__file__).resolve().parents[2]
if (repo_root / "app_builder").is_dir():
    sys.path.insert(0, str(repo_root))

from app_builder.main import main

if __name__ == "__main__":
    main.main(prog_name="app-builder")
