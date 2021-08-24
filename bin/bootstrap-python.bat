@echo off

:: This script can be used as a bootstrap step to ensure that Python
:: is downloaded and in the correct dependency location.
:: dependencies: functions.bat

SETLOCAL

:: For dev-purposes, reset path to minimal OS programs to ensure it works on other systems
set "PATH=%systemroot%;%systemroot%\System32;%systemroot%\System32\WindowsPowerShell\v1.0"

:: search these relative paths for the "functions.bat" file
set searchpaths=.;includes;..\includes;tools\deploy-scripts\includes;..\tools\deploy-scripts\includes
for %%a in ("%searchpaths:;=" "%") do (
    if exist "%~dp0%%~a\functions.bat" set "func=%~dp0%%~a\functions.bat"
)

call "%func%" ARG-PARSER %*
if "%ARG_TEMP%" EQU "" set "ARG_TEMP=%TEMP%\bootstrap-python-%random%%random%%random%"

if "%ARG_H%" EQU "1"    goto :helpmenu
if "%ARG_HELP%" EQU "1" goto :helpmenu
if "%ARG_DEST%" EQU ""  goto :errmenu
goto :skiphelpmenu
:errmenu
    echo Error:
    echo   %~n0 %*
:helpmenu
    echo Usage:
    echo   %~n0 [options]
    echo Options:
    echo   -h, -help             Print these options
    echo   -dest ^<folder^>        Path to extract Python
    echo   -temp ^<folder^>        Optional path to dump temporary files
    echo   -requirements ^<file^>  Optional path to pip requirements.txt file
    echo   -version ^<version^>    Optional python version (e.g. 3.9)
    goto :EOF
:skiphelpmenu


if exist "%ARG_DEST%\python.exe" (
    echo ^(^) Previous Python exists: %ARG_DEST%\Scripts\pip.exe
    goto :installdependancies
)

mkdir "%ARG_TEMP%\package-downloads"  >nul 2>&1

:downloadpythonroutine
:: Get Python download links from https://github.com/winpython/winpython/releases
call "%func%" GET-DL-URL pythonurl "https://github.com/winpython/winpython/releases" "/winpython/winpython/releases/download/.*/Winpython64-%ARG_version%.*dot.exe"
set "pythonurl=https://github.com%pythonurl%"

echo () Got Python link as %pythonurl%

call "%func%" GET-URL-FILENAME archivename "%pythonurl%"
set "archivename=%archivename:/=_%"
set "archivename=%ARG_TEMP%\package-downloads\%archivename%"

echo () Download to "%archivename%"
if exist "%archivename%" (
    echo ^(^) Download previously downloaded to "%archivename%"
    goto :dontdownload
)
call "%func%" DOWNLOAD-FILE "%pythonurl%" "%archivename%"

:dontdownload

call "%archivename%" -o"%ARG_DEST%" -y

set "cd_save=%CD%"
cd /d "%ARG_DEST%"
for /f "delims=" %%a in ('dir /b /ad WPy*') do cd /d "%%a"
for /f "delims=" %%a in ('dir /b /ad python-*') do cd /d "%%a"

if exist "python.exe" if exist "Lib" if exist "include" if exist "..\Spyder.exe" (
    powershell -Command "Get-ChildItem '.' | move-item -Destination './../..'"
)
cd ..
set "winpydir=%CD%"
if exist "..\python.exe" if exist "..\Lib" if exist "..\include" (
    cd ..
    powershell -Command "Remove-Item -Recurse -Force '%winpydir%'"
)

cd /d "%cd_save%"

:installdependancies

:: Download pip
call "%func%" DOWNLOAD-FILE "https://bootstrap.pypa.io/get-pip.py" "%ARG_TEMP%\package-downloads\get-pip.py"
call "%ARG_DEST%\python.exe" "%ARG_TEMP%\package-downloads\get-pip.py"

:: Pywin32 broken by latest pip, this is a workaround fix
call "%ARG_DEST%\python.exe" -m pip install pywin32

:: Install minimum libraries neccessary for the rest of the python parts
if "%ARG_REQUIREMENTS%" NEQ "" (
  call "%ARG_DEST%\python.exe" -m pip install -r "%ARG_REQUIREMENTS%"
)

rmdir "%ARG_TEMP%" /S /Q
