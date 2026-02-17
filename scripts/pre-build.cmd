1<2# : ^
r'''
@"%~dp0python\python.exe" "%~f0" %* & goto :eof
'''

from pathlib import Path
import shutil

print("Remove __pycache__")
appdir = Path(__file__).resolve().parent.parent
for i in appdir.rglob("*"):
    if i.name == "__pycache__" and i.is_dir():
        shutil.rmtree(i, ignore_errors=True)
