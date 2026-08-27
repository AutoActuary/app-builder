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

function Get-PathWithEntryFirst {
    param(
        [string]$CurrentPath,
        [string]$Entry
    )

    $Parts = @($CurrentPath -split ';' | Where-Object { -not [string]::IsNullOrWhiteSpace($_) })
    $KeptParts = @($Parts | Where-Object { (Get-NormalizedPathEntry $_) -ine $Entry })
    return (@($Entry) + $KeptParts) -join ';'
}

$InstallDir = [string]$env:app_builder_install_directory
if ([string]::IsNullOrWhiteSpace($InstallDir)) {
    $InstallDir = Split-Path -Parent $PSScriptRoot
}

$InstallDir = [IO.Path]::GetFullPath($InstallDir).TrimEnd('\')
$UserPath = [Environment]::GetEnvironmentVariable('Path', 'User')
$NewPath = Get-PathWithEntryFirst -CurrentPath $UserPath -Entry $InstallDir
[Environment]::SetEnvironmentVariable('Path', $NewPath, 'User')

$env:Path = Get-PathWithEntryFirst -CurrentPath $env:Path -Entry $InstallDir
Write-Host "Placed app-builder first on user PATH: $InstallDir"
