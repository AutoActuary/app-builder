@echo off
setlocal

set "progname=__name__"
set "installdir=__installdir__"

set "addshortcuts=__addshortcuts__"
set "keepbindir=__keepbindir__"
set "suppressdirchoice=__suppressdirchoice__"
set "menuname=__menuname__"

:: ====== Pause at the end  ======
if "%~1" NEQ "" (goto :continuebat)
    call "%~dp0\%~n0" 1
    pause
    exit /b %errorlevel%
:continuebat

:: ====== Start the install script ======
cls
::__echobanner__

:: ====== Run any user-defined pre-installation scripts ====
for %%d in (. bin src scripts) do for %%x in (bat cmd) do (
    if exist "%~dp0\%%d\pre-install.%%x" call "%~dp0\%%d\pre-install.%%x"
)

:: ====== Setup run-from-server environment  ======

:: For dev-purposes, reset path to minimal OS programs
set "PATH=%systemroot%;%systemroot%\System32;%systemroot%\System32\WindowsPowerShell\v1.0"

:: Then add our stuff to the path
set "PATH=%~dp0bin;%~dp0..\bin;%PATH%"

::try to find 7zip
if exist "%~dp0..\bin\7z.exe" ( set "sevenzbin=%~dp0..\bin\7z.exe" )
if exist "%~dp0bin\7z.exe"    ( set "sevenzbin=%~dp0bin\7z.exe"    )

:: Set the start menu directory
set "menudir=%AppData%\Microsoft\Windows\Start Menu\Programs\%menuname%"


:: ====== Installation directory presets ======
set "dirchoices=[Y/N/D]"
if "%suppressdirchoice%" neq "0" (
    set "dirchoices=[Y/N]"
)


:: ========== Choose Install Dir ===========
:choice
Echo:
Echo   [Y]es: continue
Echo   [N]o: cancel the operation
if "%suppressdirchoice%" equ "0" Echo   [D]irectory: choose my own directory

Echo:
set /P c="Install and overwrite %progname% to %installdir% %dirchoices%? "
if /I "%c%" EQU "Y" goto :exitchoice
if /I "%c%" EQU "N" goto :EOF
if /I "%c%" EQU "D" goto :selectdir
goto :choice
:selectdir

call :BROWSE-FOR-FOLDER installdir
if /I "%installdir%" EQU "Dialog Cancelled" (
    ECHO: 1>&2
    ECHO Dialog box cancelled 1>&2
    goto :EOF
)

if /I "%installdir%" EQU "" (
    ECHO: 1>&2
    ECHO Error, folder selection broke 1>&2
    goto :EOF
)
:exitchoice


:: ====== Find the zipfile to extract ======

:: different location on server and development
set "zipfile=%~dp0%progname%.7z"
if exist "%~dp0%progname%.zip" (
    set "zipfile=%~dp0%progname%.zip"
)
call :FULL-FILE-PATH zipfile "%zipfile%"


:: ====== Remove previous versions  ======

:: Remove program registration
call powershell -nop -exec bypass -c "Remove-Item -Path 'HKCU:\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\%progname%' -Recurse -Force -Confirm:$false" > nul 2>&1

:: Forceful delete method
if exist "%installdir%\bin\python\python.exe" if exist "%installdir%\tools\deploy-scripts\tools\remove-and-kill-directory.py" (
    goto :remove-and-kill-routine
)
    :: else: normal delete method mode
    if exist "%installdir%"  call :DELETE-DIRECTORY "%installdir%"
    if exist "%menudir%"  call :DELETE-DIRECTORY "%menudir%"

goto :install-procedure

:remove-and-kill-routine
echo ^(^) Uninstalling previous version...
call "%installdir%\bin\python\python.exe" "%installdir%\tools\deploy-scripts\tools\remove-and-kill-directory.py" "%menudir%"
call "%installdir%\bin\python\python.exe" "%installdir%\tools\deploy-scripts\tools\remove-and-kill-directory.py" "%installdir%"

:: If the user clicked "Cancel" when Excel is locking a PID, python exits with errorlevel 111
if "%errorlevel%" equ "111" (
    echo Installation cancelled
    goto :EOF
)

:: Wait for 90 seconds to make sure the directory is deleted then forfully continue
set /a counter=0

:not-done-deleted

:: echo without newline
if "%counter%" neq "0" (
    <nul set /p =.
)
if "%counter%" equ "30" (
    echo:
    echo There are some difficulties uninstalling previous version, please be patient
)
if "%counter%" equ "90" (
    echo:
    echo Couldn't uninstall __name__, but we are continuing anyways
)
if exist "%installdir%" if %counter% lss 90 (
    ping 127.0.0.1 -n 2 > nul
    set /a counter+=1
    goto :not-done-deleted
)
if "%counter%" neq "0" (
    echo:
)

:: Silently trying to deleting a final time
if exist "%installdir%" call :DELETE-DIRECTORY "%installdir%" 1>&2
if exist "%menudir%"  call :DELETE-DIRECTORY "%menudir%" 1>&2


:: ====== Extract to setup location  ======
:install-procedure
echo () Installing to %installdir%
echo () This may take a while...


call "%sevenzbin%" -h > nul 2>&1
set "sevenzerr=%errorlevel%"

if "%sevenzerr%" equ "0" call "%sevenzbin%" x -y "-o%installdir%" "%zipfile%" > nul
if "%sevenzerr%" neq "0" call :UNZIP-WITH-EXPLORER "%zipfile%" "%installdir%"
set "extractflag=%errorlevel%"


:: ====== Create Shortcuts and Menu items  ======
if "%addshortcuts%" equ "0" goto :skipaddingshortcuts

call :CREATE-SHORTCUT "%installdir%\bin\Uninstall %progname%.bat" "%installdir%\Uninstall %progname%.lnk" "" "%installdir%\bin\uninstall.ico"
::__githuburl__

mkdir "%menudir%" >nul 2>&1
copy "%installdir%\Uninstall %progname%.lnk" "%menudir%\Uninstall %progname%.lnk" > nul

::__shortcuts__

:skipaddingshortcuts

call :REGISTER-PROGRAM "%progname%" "%installdir%"

:: ====== Should we keep the bin directory  ======
if "%keepbindir%" equ "0" call :DELETE-DIRECTORY "%installdir%\bin"


:: ====== Run any user-defined post installation scripts ====
for %%d in (. bin src scripts) do for %%x in (bat cmd) do (
    if exist "%installdir%\%%d\post-install.%%x" call "%installdir%\%%d\post-install.%%x"
)


:: ====== Did we encounter any errors?  ======
if "%extractflag%" NEQ "0" ( 
    Echo ^(^) Installation failed, contact your administrator 
) ELSE ( 
    Echo ^(^) Installation completed successfully 
)

:: ================================================
:: This is where we store the .bat subroutines
::     /\'._   (\_/)   _.'/\
::    /.''._'--(o.o)--'_.''.\
::   /.' `\;-,'\___/',-;/` '.\
::             "   "          
goto :EOF


:: ***********************************************
:: Get full file path
:: ***********************************************
:FULL-FILE-PATH <outputvarname> <path>
    set "%~1=%~f2"
goto :EOF


:: ***********************************************
:: Unzip using default Windows mechanism 
:: ***********************************************
:UNZIP-WITH-EXPLORER <inputzip> <outputdir>
    mkdir "%~2" >nul 2>&1
    call powershell -nop -exec bypass -c "$sa = New-Object -ComObject Shell.Application; $in = $sa.NameSpace('%~1'); $out = $sa.NameSpace('%~2'); $out.CopyHere($in.Items(), 16)"

goto :EOF


:: ***********************************************
:: Create shortcut
:: ***********************************************
:CREATE-SHORTCUT <src> <dest> <optional arguments> <optional icon>
    setlocal
    del "%~2" /f /q  >nul 2>&1

    ::make up create-shortcut from the various parts
    set "dest=$s=(New-Object -COM WScript.Shell).CreateShortcut('%~2')"
    set "src=$s.TargetPath='%~1'"
    set "args="
    if "%~3" NEQ "" set "args=$s.Arguments='%~3'"
    set "ico="
    if "%~4" NEQ "" set "ico=$s.IconLocation='%~4,0'"
    set "save=$s.Save()"
    
    call powershell -nop -exec bypass -c "%dest%;%src%;%args%;%ico%;%save%"

goto :EOF


:: ***********************************************
:: Register Uninstaller
:: ***********************************************
:REGISTER-PROGRAM <progname> <installdir>
    setlocal

    call powershell -nop -exec bypass -c "Remove-Item -Path 'HKCU:\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\%~1' -Recurse -Force -Confirm:$false" > nul 2>&1
    call powershell -nop -exec bypass -c "New-Item -Path 'HKCU:\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall' -Name '%~1'" > nul 2>&1
    call powershell -nop -exec bypass -c "Get-Item -Path 'HKCU:\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\%~1' | New-ItemProperty -Name DisplayIcon -Value '%~2\bin\icon.ico'" > nul 2>&1
    call powershell -nop -exec bypass -c "Get-Item -Path 'HKCU:\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\%~1' | New-ItemProperty -Name DisplayName -Value '%~1'" > nul 2>&1
    call powershell -nop -exec bypass -c "Get-Item -Path 'HKCU:\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\%~1' | New-ItemProperty -Name InstallLocation -Value '%~2'" > nul 2>&1
    call powershell -nop -exec bypass -c "Get-Item -Path 'HKCU:\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\%~1' | New-ItemProperty -Name UninstallString -Value [char]34+'%~2\bin\Uninstall %~1.bat'+[char]34" > nul 2>&1

goto :EOF

:: ***********************************************
:: Windows del command is too limited
:: ***********************************************
:DELETE-DIRECTORY <dirname>
    if not exist "%~1" ( goto :EOF )
    powershell -nop -exec bypass -c "Remove-Item -LiteralPath '%~1' -Force -Recurse"

goto :EOF


:: ***********************************************
:: Browse for a folder on your system
:: ***********************************************
:BROWSE-FOR-FOLDER <outputvarname>
    ::Run vbs routine to open Folder prompt and return selected Folder
    ::https://stackoverflow.com/a/39593074/1490584
    set %~1=
    set "rname=browsefolder%RANDOM%%RANDOM%%RANDOM%"
    set _vbs_="%temp%\%rname%.vbs"
    set _cmd_="%temp%\%rname%.cmd"
    for %%f in (%_vbs_% %_cmd_%) do if exist %%f del %%f
    for %%g in ("_vbs_ _cmd_") do if defined %%g set %%g=
    (
        echo set shell=WScript.CreateObject("Shell.Application"^)
        echo set f=shell.BrowseForFolder(0,"%~1",0,"%~2"^)
        echo if typename(f^)="Nothing" Then
        echo wscript.echo "set %~1=Dialog Cancelled"
        echo WScript.Quit(1^)
        echo end if
        echo set fs=f.Items(^):set fi=fs.Item(^)
        echo p=fi.Path:wscript.echo "set %~1=" ^& p
    )>%_vbs_%
    cscript //nologo %_vbs_% > %_cmd_%
    for /f "delims=" %%a in (%_cmd_%) do %%a
    for %%f in (%_vbs_% %_cmd_%) do if exist %%f del /f /q %%f
    for %%g in ("_vbs_ _cmd_") do if defined %%g set %%g=

goto :EOF
