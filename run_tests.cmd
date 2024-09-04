@echo off

call "%~dp0\bin\python\python.exe" "%~dp0%~n0.py" %*

if /i "%comspec% /c %~0 " equ "%cmdcmdline:"=%" pause
