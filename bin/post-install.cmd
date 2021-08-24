<# :
    @echo off
    set "_cmd=%~f0"
    powershell -nologo -nop -exec bypass "iex (Get-Content '%_cmd%' -Raw)"
    goto :EOF
#>

function Add-ToUserPath {
    param (
        [Parameter(Mandatory=$true)]
        [ValidateNotNullOrEmpty()]
        [string] 
        $dir
    )

    $dir = [io.path]::GetFullPath($dir)
    $path = [Environment]::GetEnvironmentVariable("PATH", [System.EnvironmentVariableTarget]::User)
    if (!(";$path;".Contains(";$dir;"))) {
        [Environment]::SetEnvironmentVariable("PATH", "$dir;$path", [EnvironmentVariableTarget]::User)
        return
    }
    Write-Host  "$dir is already in PATH"
}

Add-ToUserPath "$env:_cmd/../../cli"