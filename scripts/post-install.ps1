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

$AlreadyThere = $false
foreach ($Part in $Parts) {
    $NormalizedPart = Get-NormalizedPathEntry $Part
    if ($NormalizedPart -ieq $InstallDir) {
        $AlreadyThere = $true
        break
    }
}

if (-not $AlreadyThere) {
    $NewPath = (@($InstallDir) + $Parts) -join ';'
    [Environment]::SetEnvironmentVariable('Path', $NewPath, 'User')

    $ProcessParts = @($env:Path -split ';' | Where-Object { -not [string]::IsNullOrWhiteSpace($_) })
    $env:Path = (@($InstallDir) + $ProcessParts) -join ';'
    Write-Host "Added app-builder to user PATH: $InstallDir"
} else {
    Write-Host "app-builder is already on user PATH: $InstallDir"
}
