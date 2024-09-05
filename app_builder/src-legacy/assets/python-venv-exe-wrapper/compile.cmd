<# :
    @echo off
    set "_cmd=%~f0"
    set "_ps1=%temp%\%~n0-%random%%random%%random%.ps1"
    copy /b /y "%_cmd%" "%_ps1%" >nul
    powershell -nologo -nop -exec bypass "%_ps1%" %*
    del /f "%_ps1%"
    if /i "%comspec% /c ``%~0` `" equ "%cmdcmdline:"=`%" (
        explorer "%temp%\python-venv-exe-wrapper"
        pause
    )
    goto :EOF
#>

# Make sure we have access to tcc.exe
$tempFolderPath = Join-Path $Env:Temp "tcc-latent-path"
if (Test-Path -Path "$tempFolderPath/tcc/tcc.exe" -PathType Leaf) {
    # we already have tcc
} else {
    # We have to download tcc
    New-Item -Type Directory -Force -Path $tempFolderPath | Out-Null
    Invoke-WebRequest "http://download.savannah.gnu.org/releases/tinycc/tcc-0.9.27-win64-bin.zip" -OutFile "$tempFolderPath\tcc-0.9.27-win64-bin.zip"
    Expand-Archive -Path "$tempFolderPath\tcc-0.9.27-win64-bin.zip" -DestinationPath "$tempFolderPath"
}


# Make sure we have access to rcedit
$rceditFolderPath = Join-Path $Env:Temp "rcedit-latent-path"
$rceditExePath = Join-Path $rceditFolderPath "rcedit-x64.exe"

if (Test-Path -Path $rceditExePath) {
    # rcedit is already downloaded
} else {
    # We have to download rcedit
    New-Item -Type Directory -Force -Path $rceditFolderPath | Out-Null
    Invoke-WebRequest "https://github.com/electron/rcedit/releases/download/v2.0.0/rcedit-x64.exe" -OutFile $rceditExePath
}


$tempBuild = Join-Path $Env:Temp "python-venv-exe-wrapper"
Remove-Item -Recurse -Force $tempBuild -ErrorAction Ignore
New-Item -Type Directory -Force -Path $tempBuild | Out-Null

$thisdir = Split-Path $Env:_cmd
& "$tempFolderPath/tcc/tcc.exe" -D_UNICODE "$thisdir/python-venv-exe-wrapper.c" -luser32 -lkernel32 -o "$tempBuild/python-venv-exe-wrapper.exe"
# Add icon

$ico_path = Join-Path $thisdir "python.ico"
& "$rceditExePath" "$tempBuild/python-venv-exe-wrapper.exe" --set-icon "$ico_path"


Write-Host ""
Write-Host "Compiled output: $tempBuild/python-venv-exe-wrapper.exe"
