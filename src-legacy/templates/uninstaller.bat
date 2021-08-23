@echo off
setlocal

set "progname=__name__"
set "installdir=__installdir__"
set "uninstbat=%temp%\%~n0.bat"
set "menuname=__menuname__"
set "menudir=%AppData%\Microsoft\Windows\Start Menu\Programs\%menuname%"


:: ====== Copy this to temp and run from there ======

if "%~1" NEQ "" (goto :continuebat)
    copy "%~f0" "%uninstbat%"
    pushd "%temp%"
    call "%uninstbat%" 1
    exit
:continuebat


:: ====== Start the install script ======
cls
::__echobanner__


:: ====== Do you want to Uninstall ======

:UninstQ
    echo () Warning, this will uninstall %progname% and close all open %progname% programs.
    set /P c="() Do you want to continue [Y/N]? "
    if /I "%c%" EQU "N" (
        echo ^(^) Cancelled
        goto :EOF
    )
    if /I "%c%" NEQ "Y" goto :UninstQ
:exitUninstQ


:: ====== Run any user-defined pre uninstallation scripts ====
for %%d in (. bin src scripts) do for %%x in (bat cmd) do (
    if exist "%installdir%\%%d\pre-uninstall.%%x" call "%installdir%\%%d\pre-uninstall.%%x"
)

:: ====== Save any user-defined post uninstallation scripts to temp ====
for %%d in (. bin src scripts) do for %%x in (bat cmd) do (
    if exist "%installdir%\%%d\post-uninstall.%%x" (
        mkdir "%temp%\uninstall-temp-scripts\%%d" >nul 2>&1
        copy "%installdir%\%%d\post-uninstall.%%x" "%temp%\uninstall-temp-scripts\%%d\post-uninstall.%%x" > nul
    )
)

:: ====== Delete the known locations ======

:: Forceful delete method
if exist "%installdir%\bin\python\python.exe" if exist "%installdir%\tools\deploy-scripts\tools\remove-and-kill-directory.py" (
    call "%installdir%\bin\python\python.exe" "%installdir%\tools\deploy-scripts\tools\remove-and-kill-directory.py" "%menudir%"
    call "%installdir%\bin\python\python.exe" "%installdir%\tools\deploy-scripts\tools\remove-and-kill-directory.py" "%installdir%"

) else (
    REM normal delete method mode
    if exist "%installdir%"  call :DELETE-DIRECTORY "%installdir%"
    if exist "%menudir%"  call :DELETE-DIRECTORY "%menudir%"
)

:: ====== Run any post uninstallation scripts ====
for %%d in (. bin src scripts) do for %%x in (bat cmd) do (
    if exist "%temp%\uninstall-temp-scripts\%%d\post-uninstall.%%x" call "%temp%\uninstall-temp-scripts\%%d\post-uninstall.%%x"
)
if exist "%temp%\uninstall-temp-scripts" (
    call :DELETE-DIRECTORY "%temp%\uninstall-temp-scripts"
)

Echo ^(^) Uninstall completed
pause

:: Delete myself without error https://stackoverflow.com/a/20333575/1490584
(goto) 2>nul & del "%~f0" /f /q


goto :EOF
:: ================================================
:: This is where we store the .bat subroutines
::    =/\                 /\=
::    / \'._   (\_/)   _.'/ \
::   / .''._'--(o.o)--'_.''. \
::  /_.' `\;-,'\___/',-;/` '._\
::             "   "


:: ***********************************************
:: Windows del command is too limited
:: ***********************************************
:DELETE-DIRECTORY <dirname>
    if not exist "%~1" ( goto :EOF )
    powershell -Command "Remove-Item -LiteralPath '%~1' -Force -Recurse"

goto :EOF