@echo off
:: *************************************************************************************
:: This file download deploy-scripts as a submodule
:: After this it acts as a thin wrapper for tools\deploy-scripts\tools\application-full.bat
::
:: This file is most likely copy-pasted from: deploy-scripts\copy-pasties\application.bat
:: *************************************************************************************

setlocal
set "thisdir=%~dp0"
set "thisfile=%~f0"

:: Should we update the build tools?
if not exist "%~dp0\tools\deploy-scripts\tools\application-full.bat" (
  echo Activating tools\deploy-scripts for the first time!
  call :UPDATE & goto __recoverstart__
  echo:
)

:: Update explicitely called
if /I "%~1" equ "-u" call :UPDATE & goto __recoverstart__
if /I "%~1" equ "--update" call :UPDATE  & goto __recoverstart__

:: This label can be recovered even after this script gets inplaced-mutated
:__recoverstart__
call "%~dp0\tools\deploy-scripts\tools\application-full.bat" %*


goto :EOF

:: *********************************************************************
:: UPDATE: Ensure we have the newest version of deploy-scripts
:: Cannot use anything from the repo, since it's not downloaded yet!
:: *********************************************************************
:UPDATE
    call :TEST-GIT gitflag
    if gitflag equ 0 goto :EOF

    :: ****************************
    :: Get the base git directory
    pushd "%~dp0"
        ::git toplevel
        call :EXEC gitdir err "git rev-parse --show-toplevel"

        ::but what if it is deploy-scripts submodule with basename deploy-scripts
        for /F %%I in ("%gitdir%") do  if "%%~nI" neq "deploy-scripts" (goto :nogitnest)
        pushd "%gitdir%\.."
            call :EXEC gitdir err "git rev-parse --show-toplevel"
        popd
        :nogitnest

        :: turn into correct slashes
        call :FULL-PATH gitdir "%gitdir%"
    popd

    if %err% neq 0 (
        echo "This is not a git repo and cannot have a git submodule"
        goto :EOF
    )

    ::Go to tools directory
    mkdir "%gitdir%\tools" > nul 2>&1
    pushd "%gitdir%\tools"

    ::Test if "deploy-scripts" is locked in a non-repo state and blocking us
    if not exist "deploy-scripts\.git\objects" (
        git submodule deinit  > nul 2>&1
        git rm -r deploy-scripts > nul 2>&1
        git rm --cached deploy-scripts > nul 2>&1
        call :DELETE-DIRECTORY deploy-scripts > nul 2>&1
    )

    :: try for both ssh and http
    set gitsources=git@github.com:AutoActuary/deploy-scripts.git;https://github.com/AutoActuary/deploy-scripts.git
    for %%a in ("%gitsources:;=" "%") do (

        ::Be pretty damn sure that the submodule exists (before launching dangerous git commands)
        if exist "deploy-scripts\.git\objects" goto :deploy-success
        git clone %%a deploy-scripts
        if exist "deploy-scripts\.git\objects" goto :deploy-success

    )
    goto :deploy-fail


    :deploy-success
        pushd "%gitdir%\tools\deploy-scripts"

        call :SNEAK-PEAK-YAML-DEPENDANCY toolsversion "%gitdir%\Application.yaml" deploy-scripts
        if "%toolsversion%" equ "" set "toolsversion=master"

        ::Forcefully go the the branch we need
        echo () Update to version %toolsversion% of deploy-scripts

        git reset --hard > nul 2>&1
        git clean -qdfx > nul 2>&1
        FOR /F "tokens=* USEBACKQ" %%I IN (`where git`) do call "%%I\..\..\bin\sh.exe" -c "for i in `git branch -a | grep remote | grep -v HEAD | grep -v master`; do git branch --track ${i#remotes/origin/} $i; done"  > nul 2>&1
        git fetch --all > nul 2>&1
        git fetch --tags --force > nul 2>&1
        git pull origin %toolsversion% > nul 2>&1
        git checkout --force %toolsversion% > nul 2>&1
        git reset --hard

        ::Enforce windows line endings
        git config --local core.autocrlf true

        ::Replace current file with newest version (guard against mutation via __recoverplaceholder__)
        echo Replace current application.bat file
        copy "copy-pasties\application.bat" "%gitdir%\application.bat" >nul 2>&1 & goto :__recoverplaceholder__
        :__recoverplaceholder__

        ::Do we need Python (we can call application-full.bat now)
        call :SNEAK-PEAK-YAML-DEPENDANCY needspython "%thisdir%\Application.yaml" python
        if "%needspython%" neq "" (
            call "%~dp0\tools\deploy-scripts\tools\application-full.bat" --get-python
            call "%~dp0\bin\python\python.exe" -m pip install -q -r "%~dp0\tools\deploy-scripts\requirements.txt"
        )

        ::We don't need a portable python, but we still require the dependencies
        if "%needspython%" equ "" (
            call python -m pip install -q -r "%~dp0\tools\deploy-scripts\requirements.txt"
        )

        popd
        goto :EOF

    :deploy-fail
        echo "Couldn't initiate git submodule"
goto :EOF


::*********************************************************
:: Test git
::*********************************************************
:TEST-GIT <return>
    call git --version >nul 2>&1
    if "%errorlevel%" neq "0" (
        echo "Git is not installed or added to your path!"
        echo "Get git from https://git-scm.com/downloads"
        set "%1=0"
        goto :EOF
    )

    set "%1=1"
goto :EOF


::*********************************************************
:: Execute a command and return the value
::*********************************************************
:EXEC <returnvar> <returnerror> <command>
    FOR /F "tokens=* USEBACKQ" %%I IN (`%3`) do set "%1=%%I"
    set "%2=%errorlevel%"
goto :EOF


:: ***********************************************
:: Return full path to a filepath
:: ***********************************************
:FULL-PATH <return> <filepath>
    set "%1=%~dpnx2"
goto :EOF


:: ***********************************************
:: Windows del command is too limited
:: ***********************************************
:DELETE-DIRECTORY <dirname>
    if not exist "%~1" ( goto :EOF )
    powershell -Command "Remove-Item -LiteralPath '%~1' -Force -Recurse"

goto :EOF


::*********************************************************
:: A horrible way to sneak peak if a dependency is in
:: Application.yaml "Dependencies:" listing. If the dependency is
:: listed, it returns what is after the ":" of the dependency in the
:: same line, for example "python: 1" it would return 1
::*********************************************************
:SNEAK-PEAK-YAML-DEPENDANCY <returnvar> <yamlfile> <dependancy>
    set __afterdependancyline__=0
    set "__dependancy__=%3"
    set __dependancyvalue__=

    :: have to add empty space to allow delimiter "#" to not get skipped!
    for /F "usebackq tokens=*" %%I in ("%~2") do (
        for /F "tokens=1 delims=#" %%J in (" %%I") do (
            call :__finddependancyflag__ "%%J"
        )
    )
    goto :__donefinddependancyflag__
    :__finddependancyflag__ <i>
        :: Find key:value for possible DEPENDENCIES while also "short-circuit sanitise" quotes
        for /F tokens^=1^,2^ delims^=:^" %%I in ("%~1") do (
            set "__key__=%%I"
            set "__val__=%%J"
        )
        :: flat out remove spaces (yuck)
        set "__key__=%__key__: =%"
        set "__val__=%__val__: =%"

        :: Logic to see if key-value for a dependany is found
        if "%__key__%" equ "" goto :EOF
        if "%__key__%" equ "Dependencies" set "__afterdependancyline__=1"
        if "%__afterdependancyline__%" equ "1" if "%__key__%" equ "%__dependancy__%" (
            if "%__val__%" equ "" set "__dependancyvalue__=1"
            if "%__val__%" neq "" set "__dependancyvalue__=%__val__%"
        )
    goto :EOF
    :__donefinddependancyflag__

    set %1=%__dependancyvalue__%
goto :EOF
