@echo off

:: *************************************************************************************
:: This file contains the full tools needed to run application.bat in your main repository
:: This file itself is just a logical wrapper/interface to some of the tools in it's home
:: directory, as well as some of the deployment tools locates in scripts. Hopefully one
:: day this repository will become a bit more coherent, but until then, this will do as
:: a commandline application.
:: *************************************************************************************
setlocal

:: Import function.bat
set searchpaths=.;includes;..\includes
for %%a in ("%searchpaths:;=" "%") do (
    if exist "%~dp0%%~a\functions.bat" set func="%~dp0%%~a\functions.bat"
)

set "thisdir=%~dp0"
set "thisfile=%~f0"


:: Print help (if required)
if "%~1" EQU "-h" goto :helpmenu
if "%~1" EQU "--help" goto :helpmenu


:: Collect the commandline arguments
call %func% ARG-PARSER %*


:: Do a sanity check on all the commandline parameters
set "validargs=h;-help;u;-update;l;-local-release;g;-github-release;p;-get-python;d;-get-dependencies;b;-branch-excel;i;-create-inputs-installer;-update-inputs-tables;-extract-inputs-tables"
set isvalidargs=0
for %%a in ("%validargs:;=" "%") do call set isvalidargs=%%isvalidargs%%%%ARG_%%~a%%
if "%isvalidargs%" equ "0" (
    echo Invalid commandline arguments, see usage...
    goto :helpmenu
)


goto :donehelpmenu
:helpmenu
    echo Usage: %~n0 [Options]
    echo Options:
    echo   -h, --help             Print these options
    echo   -u, --update           Ensure an up-to-date repository in tools/deploy-scripts
    echo   -p, --get-python       Download and extract python to bin/python
    echo   -d, --get-dependencies Ensure all the dependencies are set up properly
    echo   -b, --branch-excel ^<file^> ^<branch^>
    echo   -l, --local-release [--build-script ^<script^> [args...]]
    echo   -g, --github-release [--build-script ^<script^> [args...]]
    echo   -i, --create-inputs-installer       Create inputs version control installer
    echo   --update-inputs-tables [Options]    Run sub script and pass options
    echo   --extract-inputs-tables [Options]   Run sub script and pass options
    goto :EOF
:donehelpmenu


:: Get the base of the current repo
call %func% GIT-PROJECT-DIR gitdir "%thisdir%"
if "%gitdir%" equ "" (
    echo "Error: your main directory must be a git repository!"
    goto :EOF
)


:: Add local python to first entry of path (to create preference)
set "PATH=%gitdir%\bin\python;%PATH%"


:: Download local python
if "%ARG_P%"               equ "1" call :GET-PYTHON
if "%ARG_-GET-PYTHON%"     equ "1" call :GET-PYTHON


:: Ensure Application.yaml file is present
if not exist "%gitdir%\Application.yaml" (
    echo Error: please create an Application.yaml file!
    echo Use the template in deploy-scripts\copy-pasties\Application.yaml
    goto :EOF
)


:: If Python is listed as a local dependancy, make sure its downloaded
call %func% SNEAK-PEAK-YAML-DEPENDANCY needspython "%gitdir%\Application.yaml" python
if "%needspython%" neq "" if not exist "%gitdir%\bin\python\python.exe" call :GET-PYTHON
set "PATH=%gitdir%\bin\python;%PATH%"


:: If Python is still not found, throw an error
call python --version >nul 2>&1
if "%errorlevel%" neq "0" (
    echo "Error: Python not found, please install python to use this functionality!"
    goto :EOF
)


:: First the scripts that are just plainly shadowed
if "%ARG_-update-inputs-tables%"  equ "" goto :skip-update-inputs-tables
    call %func% SHIFT-ARGS shiftedargs %*
    call python "%thisdir%\..\tools\update-inputs-tables.py" %shiftedargs%  & goto :EOF
:skip-update-inputs-tables


if "%ARG_-extract-inputs-tables%" equ "" goto :skip-extract-inputs-tables
    call %func% SHIFT-ARGS shiftedargs %*
    call python "%thisdir%\..\tools\extract-inputs-tables.py" %shiftedargs% & goto :EOF
:skip-extract-inputs-tables


:: Jump to the menu option implementations
if "%ARG_D%%ARG_-get-dependencies%"        neq "" call python "%thisdir%\..\deployment-and-release-scripts\create-dependencies.py"
if "%ARG_L%%ARG_-local-release%"           neq "" call python "%thisdir%\..\deployment-and-release-scripts\create-releases.py" %*
if "%ARG_G%%ARG_-github-release%"          neq "" call python "%thisdir%\..\deployment-and-release-scripts\create-github-release.py" %*
if "%ARG_I%%ARG_-create-inputs-installer%" neq "" call python "%thisdir%\..\tools\create-inputs-installer.py" --path "%gitdir%"


:: Branch from excel has mutating behaviour
if "%ARG_b%"               neq "" call :BRANCH-EXCEL "%ARG_b_1%" "%ARG_b_2%"
if "%ARG_-branch-excel%"   neq "" call :BRANCH-EXCEL "%ARG_-branch-excel_1%" "%ARG_-branch-excel_2%"


goto :EOF

:GET-PYTHON
    call "%thisdir%\..\tools\bootstrap-python.bat" -temp "%gitdir%\tools\temp" -dest "%gitdir%\bin\python" -requirements "%thisdir%\..\requirements.txt" -version 3.8
    call "%gitdir%\bin\python\python.exe" -m pip install -r "%thisdir%\..\requirements.txt"
goto :EOF


:BRANCH-EXCEL <xlfile> <branch>
    if "%~2" EQU "" echo "ERROR: please provide a branch name!" & goto :EOF

    :: backup %gitdir%\application.bat it might get mutated
    set "appfile=%gitdir%\application.bat"
    set "savefile=%appfile%.backup%random%%random%%random%%random%%random%%random%"
    copy "%appfile%" "%savefile%" /Y >nul 2>&1

    :: reverting and branching, but backup application.bat to continue working...
    call python "%thisdir%\branch-from-workbook.py" --repo "%gitdir%" --xlfile "%~1" --branch "%~2" & copy "%savefile%" "%appfile%" /Y
    del "%savefile%" /f /q

goto :EOF
