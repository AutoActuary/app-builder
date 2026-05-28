$ErrorActionPreference = 'Stop'

function Get-NormalizedPathEntry {
    param([string]$PathEntry)

    if ([string]::IsNullOrWhiteSpace($PathEntry)) {
        return $null
    }

    $CleanEntry = $PathEntry.Trim().Trim('"')
    $ExpandedEntry = [Environment]::ExpandEnvironmentVariables($CleanEntry)
    try {
        return [IO.Path]::GetFullPath($ExpandedEntry).TrimEnd('\')
    } catch {
        return $ExpandedEntry.TrimEnd('\')
    }
}

$InstallDir = [string]$env:app_builder_install_directory
if ([string]::IsNullOrWhiteSpace($InstallDir)) {
    $InstallDir = Split-Path -Parent $PSScriptRoot
}

$InstallDir = [IO.Path]::GetFullPath($InstallDir).TrimEnd('\')
$UserPath = [Environment]::GetEnvironmentVariable('Path', 'User')
$Parts = @($UserPath -split ';' | Where-Object { -not [string]::IsNullOrWhiteSpace($_) })
$KeptParts = @()
$Removed = $false

foreach ($Part in $Parts) {
    $NormalizedPart = Get-NormalizedPathEntry $Part
    if ($NormalizedPart -ieq $InstallDir) {
        $Removed = $true
        continue
    }
    $KeptParts += $Part
}

if ($Removed) {
    [Environment]::SetEnvironmentVariable('Path', ($KeptParts -join ';'), 'User')

    $ProcessParts = @($env:Path -split ';' | Where-Object { -not [string]::IsNullOrWhiteSpace($_) })
    $env:Path = (@($ProcessParts | Where-Object { (Get-NormalizedPathEntry $_) -ine $InstallDir })) -join ';'
    Write-Host "Removed app-builder from user PATH: $InstallDir"
} else {
    Write-Host "app-builder was not on user PATH: $InstallDir"
}
