from __future__ import annotations

import json
from pathlib import Path
from tempfile import TemporaryDirectory
from zipfile import ZIP_STORED, ZipFile

from .exewrap import stamp_exe_wrap_config

_INSTALLED_MANIFEST_NAME = "app-builder-manifest.json"


def create_exewrap_zip_installer(
    output_path: Path,
    *,
    payload_archive: Path,
    manifest_path: Path,
    app_name: str,
    pause_on_exit: bool,
    add_uninstaller: bool,
    launcher: bytes | None = None,
) -> None:
    if output_path.exists():
        output_path.unlink()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_bytes(
        stamp_exe_wrap_config(
            _render_bootstrap_config(),
            launcher=launcher,
            include_end_marker=True,
        )
    )

    with TemporaryDirectory() as temp_dir_str:
        temp_dir = Path(temp_dir_str)
        install_cmd = temp_dir / "install.cmd"
        install_ps1 = temp_dir / "install.ps1"
        uninstall_cmd = temp_dir / "uninstall.cmd"
        uninstall_ps1 = temp_dir / "uninstall.ps1"
        install_cmd.write_text(
            _render_install_command(pause_on_exit),
            encoding="utf-8",
        )
        install_ps1.write_text(
            _render_install_powershell(
                manifest_name=manifest_path.name,
                uninstall_enabled=add_uninstaller,
            ),
            encoding="utf-8",
        )
        if add_uninstaller:
            uninstall_cmd.write_text(
                _render_uninstall_command(pause_on_exit),
                encoding="utf-8",
            )
            uninstall_ps1.write_text(
                _render_uninstall_powershell(manifest_name=manifest_path.name),
                encoding="utf-8",
            )

        with ZipFile(output_path, "a", compression=ZIP_STORED) as zip_file:
            zip_file.write(payload_archive, payload_archive.name)
            zip_file.write(manifest_path, manifest_path.name)
            zip_file.write(install_cmd, install_cmd.name)
            zip_file.write(install_ps1, install_ps1.name)
            if add_uninstaller:
                zip_file.write(uninstall_cmd, uninstall_cmd.name)
                zip_file.write(uninstall_ps1, uninstall_ps1.name)


def _render_bootstrap_config() -> bytes:
    return json.dumps(
        {
            "command": [
                "powershell.exe",
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-Command",
                _render_powershell_bootstrap(),
            ]
        },
        separators=(",", ":"),
    ).encode("utf-8")


def _render_powershell_bootstrap() -> str:
    return (
        "$ErrorActionPreference = 'Stop'; "
        "$exitCode = 0; "
        "$extractDir = Join-Path $env:TEMP "
        "('app-builder-' + [guid]::NewGuid().ToString('N')); "
        "try { "
        "New-Item -ItemType Directory -Path $extractDir | Out-Null; "
        "tar.exe -xf '@{exe_path}' -C $extractDir; "
        "if ($LASTEXITCODE -ne 0) { "
        "$exitCode = $LASTEXITCODE; "
        'throw "tar.exe failed with exit code $exitCode" '
        "}; "
        "& (Join-Path $extractDir 'install.cmd'); "
        "$exitCode = $LASTEXITCODE "
        "} catch { "
        "if ($exitCode -eq 0) { $exitCode = 1 }; "
        "Write-Error $_ -ErrorAction Continue "
        "} finally { "
        "if (Test-Path -LiteralPath $extractDir) { "
        "Remove-Item -LiteralPath $extractDir -Recurse -Force "
        "-ErrorAction SilentlyContinue "
        "} "
        "}; "
        "exit $exitCode"
    )


def _render_install_command(pause_on_exit: bool) -> str:
    pause_block = 'if not "%exit_code%"=="0" pause\n' if pause_on_exit else ""
    return (
        "@echo off\n"
        "setlocal\n"
        'powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0install.ps1"\n'
        'set "exit_code=%ERRORLEVEL%"\n'
        f"{pause_block}"
        "exit /b %exit_code%\n"
    )


def _render_uninstall_command(pause_on_exit: bool) -> str:
    pause_block = 'if not "%exit_code%"=="0" pause\n' if pause_on_exit else ""
    return (
        "@echo off\n"
        "setlocal\n"
        'set "script_dir=%~dp0"\n'
        'cd /d "%TEMP%"\n'
        'powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%script_dir%uninstall.ps1"\n'
        'set "exit_code=%ERRORLEVEL%"\n'
        f"{pause_block}"
        "exit /b %exit_code%\n"
    )


def _render_install_powershell(
    *,
    manifest_name: str,
    uninstall_enabled: bool,
) -> str:
    uninstall_copy_block = ""
    uninstall_shortcut_block = ""
    if uninstall_enabled:
        uninstall_copy_block = (
            "Copy-Item -LiteralPath (Join-Path $ScriptRoot 'uninstall.cmd') "
            "-Destination (Join-Path $InstallDir 'uninstall.cmd') -Force\n"
            "Copy-Item -LiteralPath (Join-Path $ScriptRoot 'uninstall.ps1') "
            "-Destination (Join-Path $InstallDir 'uninstall.ps1') -Force\n"
        )
        uninstall_shortcut_block = (
            "$UninstallCommand = Join-Path $InstallDir 'uninstall.cmd'\n"
            "if (Test-Path -LiteralPath $UninstallCommand) {\n"
            "    $UninstallShortcutName = "
            "(Get-SafeShortcutName ('Uninstall ' + [string]$Manifest.name)) + '.lnk'\n"
            "    New-AppBuilderShortcut "
            "-ShortcutPath (Join-Path $StartMenuDir $UninstallShortcutName) "
            "-TargetPath $UninstallCommand -WorkingDirectory $InstallDir -IconPath $null\n"
            "}\n"
        )
    return (
        _powershell_common_functions()
        + f"\n$ManifestName = '{manifest_name}'\n"
        + f"$InstalledManifestName = '{_INSTALLED_MANIFEST_NAME}'\n"
        + """
$ScriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$ManifestPath = Join-Path $ScriptRoot $ManifestName
$Manifest = Read-AppBuilderManifest $ManifestPath
$InstallDir = Resolve-AppBuilderPath ([string]$Manifest.install_directory) $null
$PayloadPath = Join-Path $ScriptRoot ([string]$Manifest.payload_archive)
$StagingDir = Join-Path $env:TEMP ('app-builder-install-' + [guid]::NewGuid().ToString('N'))
$BackupDir = $null
$MovedStaging = $false
$StartMenuDir = Get-AppBuilderStartMenuDirectory $Manifest

Write-Host ('Installing {0} {1}' -f $Manifest.name, $Manifest.version)
Set-AppBuilderEnvironment $Manifest $InstallDir $StartMenuDir

try {
    if (-not (Test-Path -LiteralPath $PayloadPath)) {
        throw "Payload archive not found: $PayloadPath"
    }
    New-Item -ItemType Directory -Path $StagingDir | Out-Null
    tar.exe -xf $PayloadPath -C $StagingDir
    if ($LASTEXITCODE -ne 0) {
        throw "tar.exe failed to extract payload with exit code $LASTEXITCODE"
    }

    Invoke-AppBuilderHookList $Manifest.install_hooks.pre_install $StagingDir

    $InstallParent = Split-Path -Parent $InstallDir
    if ($InstallParent) {
        New-Item -ItemType Directory -Path $InstallParent -Force | Out-Null
    }
    if (Test-Path -LiteralPath $InstallDir) {
        $BackupDir = Join-Path $InstallParent ((Split-Path -Leaf $InstallDir) + '.app-builder-backup-' + [guid]::NewGuid().ToString('N'))
        Move-Item -LiteralPath $InstallDir -Destination $BackupDir
    }
    Move-Item -LiteralPath $StagingDir -Destination $InstallDir
    $MovedStaging = $true

    Copy-Item -LiteralPath $ManifestPath -Destination (Join-Path $InstallDir $InstalledManifestName) -Force
"""
        + uninstall_copy_block
        + """
    New-AppBuilderStartMenuShortcuts $Manifest $InstallDir $StartMenuDir
"""
        + uninstall_shortcut_block
        + """
    Invoke-AppBuilderHookList $Manifest.install_hooks.post_install $InstallDir

    if ($BackupDir -and (Test-Path -LiteralPath $BackupDir)) {
        Remove-Item -LiteralPath $BackupDir -Recurse -Force
    }
    Write-Host ('Installed to {0}' -f $InstallDir)
} catch {
    if ($MovedStaging -and (Test-Path -LiteralPath $InstallDir)) {
        Remove-Item -LiteralPath $InstallDir -Recurse -Force -ErrorAction SilentlyContinue
    }
    if ($BackupDir -and (Test-Path -LiteralPath $BackupDir)) {
        Move-Item -LiteralPath $BackupDir -Destination $InstallDir -ErrorAction SilentlyContinue
    }
    throw
} finally {
    if ((-not $MovedStaging) -and (Test-Path -LiteralPath $StagingDir)) {
        Remove-Item -LiteralPath $StagingDir -Recurse -Force -ErrorAction SilentlyContinue
    }
}
"""
    )


def _render_uninstall_powershell(*, manifest_name: str) -> str:
    return (
        _powershell_common_functions()
        + f"\n$ManifestName = '{manifest_name}'\n"
        + f"$InstalledManifestName = '{_INSTALLED_MANIFEST_NAME}'\n"
        + """
$ScriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$InstalledManifestPath = Join-Path $ScriptRoot $InstalledManifestName
$TopLayerManifestPath = Join-Path $ScriptRoot $ManifestName
if (Test-Path -LiteralPath $InstalledManifestPath) {
    $ManifestPath = $InstalledManifestPath
} else {
    $ManifestPath = $TopLayerManifestPath
}
$Manifest = Read-AppBuilderManifest $ManifestPath
$InstallDir = Resolve-AppBuilderPath ([string]$Manifest.install_directory) $null
$StartMenuDir = Get-AppBuilderStartMenuDirectory $Manifest

Write-Host ('Uninstalling {0} from {1}' -f $Manifest.name, $InstallDir)
Set-AppBuilderEnvironment $Manifest $InstallDir $StartMenuDir

Invoke-AppBuilderHookList $Manifest.install_hooks.pre_uninstall $InstallDir
if (Test-Path -LiteralPath $StartMenuDir) {
    Remove-Item -LiteralPath $StartMenuDir -Recurse -Force
}
Invoke-AppBuilderHookList $Manifest.install_hooks.post_uninstall $InstallDir

Set-Location $env:TEMP
if (Test-Path -LiteralPath $InstallDir) {
    Start-AppBuilderDirectoryCleanup $InstallDir
}
Write-Host 'Uninstalled.'
"""
    )


def _powershell_common_functions() -> str:
    return r"""Set-StrictMode -Version 3.0
$ErrorActionPreference = 'Stop'

function Read-AppBuilderManifest {
    param([string]$Path)
    if (-not (Test-Path -LiteralPath $Path)) {
        throw "Manifest not found: $Path"
    }
    return Get-Content -Raw -LiteralPath $Path | ConvertFrom-Json
}

function Resolve-AppBuilderPath {
    param(
        [string]$Path,
        [AllowNull()][string]$BaseDirectory
    )
    $Expanded = [Environment]::ExpandEnvironmentVariables($Path)
    if ([System.IO.Path]::IsPathRooted($Expanded)) {
        return [System.IO.Path]::GetFullPath($Expanded)
    }
    if ([string]::IsNullOrWhiteSpace($BaseDirectory)) {
        return [System.IO.Path]::GetFullPath($Expanded)
    }
    return [System.IO.Path]::GetFullPath((Join-Path $BaseDirectory $Expanded))
}

function Get-SafeShortcutName {
    param([string]$Name)
    $SafeName = $Name
    foreach ($InvalidChar in [System.IO.Path]::GetInvalidFileNameChars()) {
        $SafeName = $SafeName.Replace([string]$InvalidChar, '_')
    }
    if ([string]::IsNullOrWhiteSpace($SafeName)) {
        return 'Shortcut'
    }
    return $SafeName
}

function Get-AppBuilderStartMenuDirectory {
    param($Manifest)
    $Programs = Join-Path $env:APPDATA 'Microsoft\Windows\Start Menu\Programs'
    return Join-Path $Programs (Get-SafeShortcutName ([string]$Manifest.name))
}

function Set-AppBuilderEnvironment {
    param($Manifest, [string]$InstallDir, [string]$StartMenuDir)
    $env:app_builder_name = [string]$Manifest.name
    $env:app_builder_version = [string]$Manifest.version
    $env:app_builder_install_directory = $InstallDir
    $env:app_builder_project_root = $InstallDir
    $env:app_builder_start_menu = $StartMenuDir
}

function Resolve-HookProgram {
    param([string]$Program, [string]$WorkingDirectory)
    $Expanded = [Environment]::ExpandEnvironmentVariables($Program)
    if ([System.IO.Path]::IsPathRooted($Expanded)) {
        return [System.IO.Path]::GetFullPath($Expanded)
    }
    $Candidate = Join-Path $WorkingDirectory $Expanded
    if (Test-Path -LiteralPath $Candidate) {
        return [System.IO.Path]::GetFullPath($Candidate)
    }
    return $Expanded
}

function Select-HookPython {
    param([string]$WorkingDirectory)
    $Candidates = @(
        (Join-Path $WorkingDirectory 'venv\Scripts\python.exe'),
        (Join-Path $WorkingDirectory 'bin\python\python\python.exe'),
        'python.exe'
    )
    foreach ($Candidate in $Candidates) {
        if (Test-Path -LiteralPath $Candidate) {
            return $Candidate
        }
    }
    return 'python.exe'
}

function Invoke-AppBuilderHook {
    param($Command, [string]$WorkingDirectory)
    if ($null -eq $Command) {
        return
    }
    $Argv = @()
    foreach ($Item in @($Command)) {
        $Argv += [string]$Item
    }
    if ($Argv.Count -eq 0) {
        return
    }
    $Program = Resolve-HookProgram $Argv[0] $WorkingDirectory
    $Arguments = @()
    if ($Argv.Count -gt 1) {
        $Arguments = $Argv[1..($Argv.Count - 1)]
    }
    $Extension = [System.IO.Path]::GetExtension($Program).ToLowerInvariant()
    $global:LASTEXITCODE = 0
    if ((Test-Path -LiteralPath $Program) -and $Extension -eq '.ps1') {
        & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $Program @Arguments
    } elseif ((Test-Path -LiteralPath $Program) -and $Extension -eq '.py') {
        & (Select-HookPython $WorkingDirectory) $Program @Arguments
    } else {
        & $Program @Arguments
    }
    if ($LASTEXITCODE -ne 0) {
        throw "Hook command failed with exit code ${LASTEXITCODE}: $($Argv -join ' ')"
    }
}

function Invoke-AppBuilderHookList {
    param($Commands, [string]$WorkingDirectory)
    if ($null -eq $Commands) {
        return
    }
    foreach ($Command in @($Commands)) {
        Invoke-AppBuilderHook $Command $WorkingDirectory
    }
}

function New-AppBuilderShortcut {
    param(
        [string]$ShortcutPath,
        [string]$TargetPath,
        [string]$WorkingDirectory,
        [AllowNull()][string]$IconPath
    )
    $ShortcutParent = Split-Path -Parent $ShortcutPath
    New-Item -ItemType Directory -Path $ShortcutParent -Force | Out-Null
    $Shell = New-Object -ComObject WScript.Shell
    $Shortcut = $Shell.CreateShortcut($ShortcutPath)
    $Shortcut.TargetPath = $TargetPath
    $Shortcut.WorkingDirectory = $WorkingDirectory
    if ($IconPath -and (Test-Path -LiteralPath $IconPath)) {
        $Shortcut.IconLocation = $IconPath
    }
    $Shortcut.Save()
}

function New-AppBuilderStartMenuShortcuts {
    param($Manifest, [string]$InstallDir, [string]$StartMenuDir)
    if ($null -eq $Manifest.start_menu) {
        return
    }
    foreach ($Item in @($Manifest.start_menu)) {
        $DisplayName = [string]$Item.display_name
        if ([string]::IsNullOrWhiteSpace($DisplayName)) {
            $DisplayName = [string]$Manifest.name
        }
        $ShortcutPath = Join-Path $StartMenuDir ((Get-SafeShortcutName $DisplayName) + '.lnk')
        $TargetPath = Resolve-AppBuilderPath ([string]$Item.target) $InstallDir
        $IconPath = $null
        if ($Item.icon) {
            $IconPath = Resolve-AppBuilderPath ([string]$Item.icon) $InstallDir
        }
        New-AppBuilderShortcut -ShortcutPath $ShortcutPath -TargetPath $TargetPath -WorkingDirectory $InstallDir -IconPath $IconPath
    }
}

function Start-AppBuilderDirectoryCleanup {
    param([string]$Directory)
    if (-not (Test-Path -LiteralPath $Directory)) {
        return
    }
    if ($Directory.Contains('"')) {
        throw "Cannot clean up a path containing a double quote: $Directory"
    }
    $CleanupDir = Join-Path $env:TEMP ('app-builder-cleanup-' + [guid]::NewGuid().ToString('N'))
    New-Item -ItemType Directory -Path $CleanupDir -Force | Out-Null
    $CleanupScript = Join-Path $CleanupDir 'cleanup.cmd'
    $Lines = @(
        '@echo off',
        'ping 127.0.0.1 -n 2 >nul',
        ('rmdir /s /q "' + $Directory + '"'),
        ('rmdir /s /q "' + $CleanupDir + '"')
    )
    Set-Content -LiteralPath $CleanupScript -Value $Lines -Encoding ASCII
    Start-Process -FilePath 'cmd.exe' -ArgumentList @('/D', '/C', "`"$CleanupScript`"") -WindowStyle Hidden
}
"""
