@echo off
:: ************************************************
:: A file full of reusable bat routines to be called
:: from an external file.
::
:: Usage: functions <functionname> <arg1> <arg2> ...
:: ************************************************


:: Set functionname and shift arguments one bach
::set "__functionname__=%~1"
::shift
call :%*
goto :EOF


::*********************************************************
:: https://stackoverflow.com/a/61552059
:: Parse commandline arguments into sane variables
:: See the following scenario as usage example:
:: >> thisfile.bat -a -b "c:\" -c -foo 5
:: >> CALL :ARG-PARSER %*
:: ARG_a=1
:: ARG_b=c:\
:: ARG_c=1
:: ARG_foo=5
::*********************************************************
:ARG-PARSER <arg1> <arg2> <etc>
    ::Loop until two consecutive empty args
    :__loopargs__
        IF "%~1%~2" EQU "" GOTO :EOF

        set "__arg1__=%~1"
        set "__arg2__=%~2"

        :: Capture assignments: eg. -foo bar baz  -> ARG_FOO=bar ARG_FOO_1=bar ARG_FOO_2=baz
        IF "%__arg1__:~0,1%" EQU "-"  IF "%__arg2__:~0,1%" NEQ "-" IF "%__arg2__%" NEQ "" (
            call :ARG-PARSER-HELPER %1 %2 %3 %4 %5 %6 %7 %8 %9
        )
        :: This is for setting ARG_FOO=1 if no value follows
        IF "%__arg1__:~0,1%" EQU "-" IF "%__arg2__:~0,1%" EQU "-" (
            set "ARG_%__arg1__:~1%=1"
        )
        IF "%__arg1__:~0,1%" EQU "-" IF "%__arg2__%" EQU "" (
            set "ARG_%__arg1__:~1%=1"
        )

        shift
    goto __loopargs__

goto :EOF

:: Helper routine for ARG-PARSER
:ARG-PARSER-HELPER <arg1> <arg2> <etc>
    set "ARG_%__arg1__:~1%=%~2"
    set __cnt__=0
    :__loopsubargs__
        shift
        set "__argn__=%~1"
        if "%__argn__%"      equ "" goto :EOF
        if "%__argn__:~0,1%" equ "-" goto :EOF

        set /a __cnt__=__cnt__+1
        set "ARG_%__arg1__:~1%_%__cnt__%=%__argn__%"
    goto __loopsubargs__
goto :EOF


::*********************************************************
:: Find a file like "Applicaton.yaml" somewhere in an upper directory
:: Cd up up up until the file is found
::*********************************************************
:FIND-PARENT-WITH-FILE <returnvar> <startdir> <filename>
	pushd "%~2"
		:__filesearchloop__
			set "__thisdir__=%cd%"
			if "%__thisdir__%" neq "%__thisdir_prev__%" goto :__continuefilesearch__
			    echo Could not find Application.yaml
			    set "%1=NUL"
			    goto :__filesearchcomplete__
			:__continuefilesearch__

			if exist "%3" (
				set "%1=%cd%"
				goto :__filesearchcomplete__
			)
		    cd ..
		    set "__thisdir_prev__=%thisdir%"
			goto :__filesearchloop__

	:__filesearchcomplete__
	popd

	set __thisdir__=
    set __thisdir_prev__=
goto :EOF


:: ***********************************************
:: Remove trailing slash if exists
:: ***********************************************
:NO-TRAILING-SLASH <return> <input>
    set "__notrailingslash__=%~2"
    IF "%__notrailingslash__:~-1%" == "\" (
        SET "__notrailingslash__=%__notrailingslash__:~0,-1%"
    )
    set "%1=%__notrailingslash__%"
    set __notrailingslash__=
goto :EOF


:: ***********************************************
:: Expand path like c:\bla\fo* to c:\bla\foo
:: Expansion only works for last item!
:: ***********************************************
:EXPAND-ASTERIX <return> <filepath>
    ::basename with asterix expansion
    set "__inputfilepath__=%~2"
    call :NO-TRAILING-SLASH __inputfilepath__ "%__inputfilepath__%"

    set "_basename_="
    for /f "tokens=*" %%F in ('dir /b "%__inputfilepath__%" 2^> nul') do (
        set "_basename_=%%F"
        goto :__endofasterixexp__
    )
    :__endofasterixexp__

    ::concatenate with dirname is basename found (else "")
    if "%_basename_%" NEQ "" (
        set "%~1=%~dp2%_basename_%"
    ) ELSE (
        set "%~1="
    )

    set _basename_=
goto :EOF


:: ***********************************************
:: Return full path to a filepath
::
:: ***********************************************
:FULL-PATH <return> <filepath>
    set "%1=%~dpnx2"
goto :EOF


:: ***********************************************
:: Download a file
:: ***********************************************
:DOWNLOAD-FILE <url> <filelocation>
    call powershell -Command "Invoke-WebRequest '%~1' -OutFile '%~2'"
    exit /b %errorlevel%

goto :EOF


:: ***********************************************
:: Remove all non-filename characters from a valid url
:: ***********************************************
:SLUGIFY-URL <returnvar> <theurl>
    set "_urlslugified_=%~2"
    set "_urlslugified_=%_urlslugified_:/=-%"
    set "_urlslugified_=%_urlslugified_::=-%"
    set "_urlslugified_=%_urlslugified_:?=-%"
    set "%~1=%_urlslugified_%"

    set _urlslugified_=
goto :EOF


:: ***********************************************
:: Get a download link from a download page by matching
:: a regex and using the first match.
::
:: Example:
:: call :GET-DL-URL linkvar "https://julialang.org/downloads/" "https.*bin/winnt/x64/.*win64.exe"
:: echo %linkvar%
::
:: ***********************************************
:GET-DL-URL <%~1 outputvarname> <%~2 download page url> <%~3 regex string>

    call :SLUGIFY-URL _urlslug_ "%~2"

    set "_htmlfile_=%temp%\%_urlslug_%"
    set "_linksfile_=%temp%\%_urlslug_%-links.txt"

    :: Download the download-page html
    call :DOWNLOAD-FILE "%~2" "%_htmlfile_%"

    if %errorlevel% NEQ 0 goto EOF-DEAD

    :: Split file on '"' quotes so that valid urls will land on a seperate line
    powershell -Command "(gc '%_htmlfile_%') -replace '""', [System.Environment]::Newline  | Out-File '%_htmlfile_%--split' -encoding utf8"

    ::Find the lines of all the valid Regex download links
    findstr /i /r /c:"%~3" "%_htmlfile_%--split" > "%_linksfile_%"


    ::Save first occurance to head by reading the file with powershell and taking the first line
    for /f "usebackq delims=" %%a in (`powershell -Command "(Get-Content '%_linksfile_%')[0]"`) do (set "head=%%a")

    ::Clean up our temp files
    ::del /f /q "%_htmlfile_%--split"
    ::del /f /q "%_htmlfile_%"
    ::del /f /q "%_linksfile_%"

    ::Save the result to the outputvariable
    set "%~1=%head%"

    if "%_linksfile_%" EQU "" (
        echo Could not find regex
        goto :EOF-DEAD
    )

    set _htmlfile_=
    set _linksfile_=
goto :EOF


:: ***********************************************
:: Given a download link, what is the name of that file
:: (last thing after last "/")
:: ***********************************************
:GET-URL-FILENAME <outputvarname> <url>

    :: Loop through each "/" separation and set %~1
    :: https://stackoverflow.com/a/37631935/1490584

    set "_List_=%~2"
    set _ItemCount_=0

    :_NextItem_
        if "%_List_%" == "" goto :_exitnextitem_

        set /A _ItemCount_+=1
        for /F "tokens=1* delims=/" %%a in ("%_List_%") do (
            :: echo Item %_ItemCount_% is: %%a
            set "_List_=%%b"
            set "_out_=%%a"
        )
        goto _NextItem_
    :_exitnextitem_

    ::remove non filename characters
    call :SLUGIFY-URL "%~1" "%_out_%"

    set _List_=
    set _itemcount_=
    set _out_=
goto :EOF


:: ***********************************************
:: Extract an archive file using 7zip
:: ***********************************************
:EXTRACT-ARCHIVE <7zipexe> <srce> <dest>
    ::Try to make a clean slate for extractor
    call :DELETE-DIRECTORY "%~3" >nul 2>&1
    mkdir "%~3" 2>NUL

    ::Extract to output directory
    call "%~1" x -y "-o%~3" "%~2"

goto :EOF


:: ***********************************************
:: Extract Python installer to final location
:: dark.exe is required for the extraction
:: ***********************************************
:EXTRACT-PYTHON <darkexe> <srce> <dest>
    ::Don't affect surrounding scope
    setlocal

    set "__pytemp__=%TEMP%\pythontempextract"

    ::del /f /q /s "%__pytemp__%" >nul 2>&1
    call :DELETE-DIRECTORY "%__pytemp__%"

    call :DELETE-DIRECTORY "%~3" >nul 2>&1
    mkdir "%~3" 2>NUL

    "%~1" "%~2" -x "%__pytemp__%"

    ::Loop through msi files and extract the neccessary ones
    FOR %%I in ("%__pytemp__%\AttachedContainer\*.msi") DO call :__msiextractpython__ "%%I" "%~3"
    goto :__guardmsiextractpython__
        :__msiextractpython__ <srce> <dest>
            setlocal
            ::filer out unneeded msi installs
            if /i "%~n1" EQU "test" goto :EOF
            if /i "%~n1" EQU "doc" goto :EOF
            if /i "%~n1" EQU "dev" goto :EOF
            if /i "%~n1" EQU "launcher" goto :EOF
            if /i "%~n1" EQU "test" goto :EOF
            if /i "%~n1" EQU "ucrt" goto :EOF
            if /i "%~n1" EQU "path" goto :EOF
            if /i "%~n1" EQU "pip" goto :EOF

            msiexec /a "%~1" /qb TARGETDIR="%~2"
        goto :EOF
    :__guardmsiextractpython__

    FOR %%I in ("%~2\*.msi") DO del /q /s "%%I"
    call :DELETE-DIRECTORY "%__pytemp__%"

    set __pytemp__=
goto :EOF



:: ***********************************************
:: Windows del command is too limited
:: ***********************************************
:DELETE-DIRECTORY <dirname>
    if not exist "%~1" ( goto :EOF )
    powershell -Command "Remove-Item -LiteralPath '%~1' -Force -Recurse"

goto :EOF


::*********************************************************
:: Execute a command and return the value
::*********************************************************
:EXEC <returnvar> <returnerror> <command>
    set "errorlevel=0"
    FOR /F "tokens=* USEBACKQ" %%I IN (`%3`) do set "%1=%%I"
    set "%2=%errorlevel%"
goto :EOF


::*********************************************************
:: Test git
::*********************************************************
:TEST-GIT <return>
    call git --version >nul 2>&1
    if %errorlevel% neq 0 (
        echo "Git is not installed or added to your path!"
        echo "Get git from https://git-scm.com/downloads"
        set "%1=0"
        goto :EOF
    )

    set "%1=1"
goto :EOF


::*********************************************************
:: Test the project's git directory
::*********************************************************
:GIT-PROJECT-DIR <return> <startpath>
    set %1=

    call :TEST-GIT __gitflag__
    if __gitflag__ equ 0 (
        goto :EOF
    )

    :: ****************************
    :: Get the base git directory
    pushd "%~2"
        ::git toplevel
        call :EXEC __gitdir__ __err__ "git rev-parse --show-toplevel"

        ::but what if it is deploy-scripts submodule with basename deploy-scripts
        for /F %%I in ("%__gitdir__%") do  if "%%~nI" neq "deploy-scripts" (goto :__nogitnest__)
        pushd "%__gitdir__%\.."
            call :EXEC __gitdir__ __err__ "git rev-parse --show-toplevel"
        popd
        :__nogitnest__

        :: turn into correct slashes
        call :FULL-PATH __gitdir__ "%__gitdir__%"
    popd

    if __err__ neq 1 (
        set "%1=%__gitdir__%"
    )
goto :EOF


::*********************************************************
:: Choose a file from the file selection menu
::*********************************************************
:CHOOSE-FILE <return>
    rem preparation command
    set _pwshcmd_=powershell -noprofile -command "&{[System.Reflection.Assembly]::LoadWithPartialName('System.windows.forms') | Out-Null;$OpenFileDialog = New-Object System.Windows.Forms.OpenFileDialog; $OpenFileDialog.ShowDialog()|out-null; $OpenFileDialog.FileName}"
    rem exec commands powershell and get result in FileName variable
    for /f "delims=" %%I in ('%_pwshcmd_%') do set "_FileName_=%%I"

    set "%~1=%_FileName_%"
goto :EOF


::*********************************************************
:: Split a file into its dir, name, and ext
::*********************************************************
:DIR-NAME-EXT <returndir> <returnname> <returnext> <inputfile>
    set "%~1=%~dp4"
    set "%~2=%~n4"
    set "%~3=%~x4"
goto :EOF


::*********************************************************
:: Get the local date
::*********************************************************
:LOCAL-DATE <return>
    :: adapted from http://stackoverflow.com/a/10945887/1810071
    for /f "skip=1" %%x in ('wmic os get localdatetime') do if not defined MyDate set MyDate=%%x
    for /f %%x in ('wmic path win32_localtime get /format:list ^| findstr "="') do set %%x
    set fmonth=00%Month%
    set fday=00%Day%
    set _today_=%Year%-%fmonth:~-2%-%fday:~-2%
    set "%~1=%_today_%"
goto :EOF


::*********************************************************
:: Get the local time
::*********************************************************
:LOCAL-TIME
    set "_tmp_=%time: =0%"
    set "_tmp_=%_tmp_:,=%"
    set "_tmp_=%_tmp_::=%"
    set "%1=%_tmp_%"
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


::*********************************************************
:: Test if the parameters of a function is as expected
::*********************************************************
:TEST-OUTCOME <expected> <actual> <testname>
    if "%~1" EQU "%~2" goto :EOF

    echo "*********************************************"
    if "%~3" NEQ "" echo For test %~3
    echo Expected: %1
    echo Got     : %2
    echo:

goto :EOF



::*********************************************************
:: Shift arguments to the right
::*********************************************************
:SHIFT-ARGS <return> <argstoshift...>
    set __returnname__=%1
    shift
    shift
    set __args__=%1
    :__parse__
        shift
        set __first__=%1
        if not defined __first__ goto :__endparse__
        set __args__=%__args__% %__first__%
    goto :__parse__
    :__endparse__

    set %__returnname__%=%__args__%
goto :EOF
