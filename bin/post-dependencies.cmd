@echo off
if not exist "%~dp0\python\python.exe" call "%~dp0\bootstrap-python.bat" -dest "%~dp0\python"
call "%~dp0\python\python.exe" -m pip install -r "%~dp0..\requirements.txt" --no-warn-script-location

