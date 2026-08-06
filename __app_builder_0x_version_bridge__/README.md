# app-builder 0.x version bridge

This source package exists only because released app-builder 0.x launchers install
the requested Git ref's root `requirements.txt` before dispatching to that ref.

Installation adds a guarded `.pth` activator to the legacy version venv. It exposes
the sibling checked-out 1.x repository only when Python is running from the exact
legacy `versions/<ref>/venv` layout. In every other Python environment it is inert.
