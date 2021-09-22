<# :
    @echo off
    set "_cmd=%~f0"
    set "_ps1=%temp%\%~n0-%random%%random%%random%.ps1"
    copy /b /y "%_cmd%" "%_ps1%" >nul
    powershell -nologo -nop -exec bypass "%_ps1%" %*
    del /f "%_ps1%"
    goto :EOF
#>


Function Get-Tcc () {
    # Make sure we have access to tcc.exe
    $tempFolderPath = Join-Path $Env:Temp "tcc-temp-path"
    
    if (Test-Path -Path "$tempFolderPath/tcc/tcc.exe" -PathType Leaf) {
        # we already have tcc
    } else {
        # We have to download tcc
        New-Item -Type Directory -Force -Path $tempFolderPath | Out-Null
        Invoke-WebRequest "http://download.savannah.gnu.org/releases/tinycc/tcc-0.9.27-win64-bin.zip" -OutFile "$tempFolderPath\tcc-0.9.27-win64-bin.zip"
        Expand-Archive -Path "$tempFolderPath\tcc-0.9.27-win64-bin.zip" -DestinationPath "$tempFolderPath"
    }

    Return "$tempFolderPath/tcc/tcc.exe"
}


Function Get-RcEdit () {
    if (Test-Path -Path "$Env:Temp/rcedit.exe" -PathType Leaf) {
        # already have julia ico
    } else {
        Invoke-WebRequest "https://github.com/electron/rcedit/releases/download/v1.1.1/rcedit-x64.exe" -OutFile "$Env:Temp/rcedit.exe"
    }

    return "$Env:Temp/rcedit.exe"
}


Function Get-Julia-Icon () {
    if (Test-Path -Path "$Env:Temp/julia.ico" -PathType Leaf) {
        # already have julia ico
    } else {
        Invoke-WebRequest "https://raw.githubusercontent.com/JuliaLang/julia/master/contrib/windows/julia.ico" -OutFile "$Env:Temp/julia.ico"
    }

    return "$Env:Temp/julia.ico"
}


$thisdir = Split-Path $Env:_cmd
Set-Location -Path $thisdir

$tcc = Get-Tcc
$rcedit = Get-RcEdit
$jlico = Get-Julia-Icon

& $tcc -D_UNICODE -DNOSHELL launcher.c -luser32 -lkernel32 -mwindows -o launcher-noshell.exe
& $tcc -D_UNICODE  launcher.c -luser32 -lkernel32 -o launcher.exe
& $tcc -D_UNICODE  launcher-julia.c -luser32 -lkernel32 -o launcher-julia.exe
& $rcedit launcher-julia.exe --set-icon $jlico