from __future__ import annotations

import json
from pathlib import Path
from tempfile import TemporaryDirectory
from zipfile import ZIP_STORED, ZipFile

from .exewrap import stamp_exe_wrap_config

_INSTALLED_MANIFEST_NAME = "app-builder-manifest.json"
_POWERSHELL_HERE_STRING_END = "'@"


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
        uninstall_cmd = temp_dir / "uninstall.cmd"
        manifest_json = _read_manifest_json_for_embedding(manifest_path)
        install_cmd.write_text(
            _render_install_command(
                manifest_json=manifest_json,
                uninstall_enabled=add_uninstaller,
                pause_on_exit=pause_on_exit,
            ),
            encoding="utf-8",
        )
        if add_uninstaller:
            uninstall_cmd.write_text(
                _render_uninstall_command(
                    manifest_json=manifest_json,
                    pause_on_exit=pause_on_exit,
                ),
                encoding="utf-8",
            )

        with ZipFile(output_path, "a", compression=ZIP_STORED) as zip_file:
            zip_file.write(payload_archive, payload_archive.name)
            zip_file.write(install_cmd, install_cmd.name)
            if add_uninstaller:
                zip_file.write(uninstall_cmd, uninstall_cmd.name)


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


def _read_manifest_json_for_embedding(manifest_path: Path) -> str:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest_json = json.dumps(manifest, indent=2)
    if _contains_powershell_here_string_terminator(manifest_json):
        raise ValueError(
            f"{manifest_path} cannot be embedded in the installer script because "
            "it contains a PowerShell here-string terminator."
        )
    return manifest_json


def _contains_powershell_here_string_terminator(value: str) -> bool:
    normalized = value.replace("\r\n", "\n").replace("\r", "\n")
    return any(line == _POWERSHELL_HERE_STRING_END for line in normalized.split("\n"))


def _render_cmd_powershell_header(pause_on_exit: bool) -> str:
    pause_block = 'if not "%ERRORLEVEL%"=="0" pause\n' if pause_on_exit else ""
    return (
        "<# :\n"
        "@echo off\n"
        'set "_cmd=%~f0"\n'
        'powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -Command "iex (Get-Content -LiteralPath $env:_cmd -Raw)"\n'
        f"{pause_block}"
        "exit /b %ERRORLEVEL%\n"
        "#>\n"
    )


def _embedded_manifest_assignment(manifest_json: str) -> str:
    if _contains_powershell_here_string_terminator(manifest_json):
        raise ValueError(
            "Manifest JSON cannot be embedded because it contains a PowerShell "
            "here-string terminator."
        )
    return f"\n$EmbeddedManifestJson = @'\n{manifest_json}\n'@\n"


def _render_install_command(
    *,
    manifest_json: str,
    uninstall_enabled: bool,
    pause_on_exit: bool,
) -> str:
    return _render_cmd_powershell_header(pause_on_exit) + _render_install_powershell(
        manifest_json=manifest_json,
        uninstall_enabled=uninstall_enabled,
    )


def _render_uninstall_command(*, manifest_json: str, pause_on_exit: bool) -> str:
    return _render_cmd_powershell_header(pause_on_exit) + _render_uninstall_powershell(
        manifest_json=manifest_json
    )


def _render_install_powershell(
    *,
    manifest_json: str,
    uninstall_enabled: bool,
) -> str:
    uninstall_copy_block = ""
    uninstall_shortcut_block = ""
    if uninstall_enabled:
        uninstall_copy_block = (
            "Copy-Item -LiteralPath (Join-Path $ScriptRoot 'uninstall.cmd') "
            "-Destination (Join-Path $InstallDir 'uninstall.cmd') -Force\n"
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
        + _embedded_manifest_assignment(manifest_json)
        + f"$InstalledManifestName = '{_INSTALLED_MANIFEST_NAME}'\n"
        + """
$ScriptRoot = Split-Path -Parent $env:_cmd
$Manifest = Read-AppBuilderManifestJson $EmbeddedManifestJson
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

    Set-Content -LiteralPath (Join-Path $InstallDir $InstalledManifestName) -Value $EmbeddedManifestJson -Encoding UTF8
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


def _render_uninstall_powershell(*, manifest_json: str) -> str:
    return (
        _powershell_common_functions()
        + _embedded_manifest_assignment(manifest_json)
        + f"$InstalledManifestName = '{_INSTALLED_MANIFEST_NAME}'\n"
        + """
$ScriptRoot = Split-Path -Parent $env:_cmd
$Manifest = Read-AppBuilderManifestJson $EmbeddedManifestJson
$InstallDir = Resolve-AppBuilderPath ([string]$Manifest.install_directory) $null
$StartMenuDir = Get-AppBuilderStartMenuDirectory $Manifest
$PostUninstallDir = Join-Path $env:TEMP ('app-builder-post-uninstall-' + [guid]::NewGuid().ToString('N'))
$StartedCleanup = $false

Write-Host ('Uninstalling {0} from {1}' -f $Manifest.name, $InstallDir)
Set-AppBuilderEnvironment $Manifest $InstallDir $StartMenuDir

try {
    $PostUninstallCommands = Copy-AppBuilderPostUninstallEntrypoints $Manifest.install_hooks.post_uninstall $InstallDir $PostUninstallDir
    Invoke-AppBuilderHookList $Manifest.install_hooks.pre_uninstall $InstallDir
    if (Test-Path -LiteralPath $StartMenuDir) {
        Remove-Item -LiteralPath $StartMenuDir -Recurse -Force
    }

    Set-Location $env:TEMP
    Start-AppBuilderPostUninstallCleanup $InstallDir $PostUninstallCommands $PostUninstallDir
    $StartedCleanup = $true
} finally {
    if ((-not $StartedCleanup) -and (Test-Path -LiteralPath $PostUninstallDir)) {
        Remove-Item -LiteralPath $PostUninstallDir -Recurse -Force -ErrorAction SilentlyContinue
    }
}
Write-Host 'Uninstall cleanup started.'
"""
    )


def _powershell_common_functions() -> str:
    return r"""Set-StrictMode -Version 3.0
$ErrorActionPreference = 'Stop'

function Read-AppBuilderManifestJson {
    param([string]$Json)
    if ([string]::IsNullOrWhiteSpace($Json)) {
        throw "Manifest JSON is empty."
    }
    return $Json | ConvertFrom-Json
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
        (Join-Path $WorkingDirectory 'bin\python\python\python.exe')
    )
    foreach ($Candidate in $Candidates) {
        if (Test-Path -LiteralPath $Candidate) {
            return $Candidate
        }
    }
    throw "Cannot run Python hook from a .py entrypoint because app-builder could not find project-owned Python in venv\Scripts\python.exe or bin\python\python\python.exe. Use an explicit command such as ['python', 'script.py'] if the target machine is expected to provide Python."
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

function Test-AppBuilderPathInside {
    param([string]$Path, [string]$Directory)
    $FullPath = [System.IO.Path]::GetFullPath($Path).TrimEnd('\')
    $FullDirectory = [System.IO.Path]::GetFullPath($Directory).TrimEnd('\')
    return $FullPath.Equals($FullDirectory, [System.StringComparison]::OrdinalIgnoreCase) -or $FullPath.StartsWith($FullDirectory + '\', [System.StringComparison]::OrdinalIgnoreCase)
}

function Copy-AppBuilderPostUninstallEntrypoints {
    param($Commands, [string]$InstallDir, [string]$DestinationDir)
    $PreparedCommands = @()
    if ($null -eq $Commands) {
        return ,$PreparedCommands
    }
    $AllowedExtensions = @('.cmd', '.ps1', '.exe')
    $Index = 0
    foreach ($Command in @($Commands)) {
        if ($null -eq $Command) {
            continue
        }
        $Argv = @()
        foreach ($Item in @($Command)) {
            $Argv += [string]$Item
        }
        if ($Argv.Count -eq 0) {
            continue
        }
        $OriginalProgram = $Argv[0]
        $Program = Resolve-HookProgram $OriginalProgram $InstallDir
        if (Test-Path -LiteralPath $Program) {
            $ProgramPath = [System.IO.Path]::GetFullPath($Program)
            if (Test-AppBuilderPathInside $ProgramPath $InstallDir) {
                $Extension = [System.IO.Path]::GetExtension($ProgramPath).ToLowerInvariant()
                if (-not $AllowedExtensions.Contains($Extension)) {
                    throw "post_uninstall entrypoints inside the install directory must be self-contained .cmd, .ps1, or .exe files: $OriginalProgram"
                }
                New-Item -ItemType Directory -Path $DestinationDir -Force | Out-Null
                $SafeName = ('{0:D3}-{1}' -f $Index, (Split-Path -Leaf $ProgramPath))
                $StagedProgram = Join-Path $DestinationDir $SafeName
                Copy-Item -LiteralPath $ProgramPath -Destination $StagedProgram -Force
                $Argv[0] = $StagedProgram
            } else {
                $Argv[0] = $ProgramPath
            }
        } elseif ($OriginalProgram.Contains('\') -or $OriginalProgram.Contains('/') -or [System.IO.Path]::IsPathRooted([Environment]::ExpandEnvironmentVariables($OriginalProgram))) {
            throw "post_uninstall entrypoint must exist before the install directory is removed: $OriginalProgram"
        }
        $PreparedCommands += ,$Argv
        $Index += 1
    }
    return ,$PreparedCommands
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

function Remove-AppBuilderInstallDirectory {
    param([string]$Directory)
    if (-not (Test-Path -LiteralPath $Directory)) {
        return
    }
    $LastError = $null
    for ($Attempt = 0; $Attempt -lt 20; $Attempt += 1) {
        try {
            Remove-Item -LiteralPath $Directory -Recurse -Force -ErrorAction Stop
        } catch {
            $LastError = $_
        }
        if (-not (Test-Path -LiteralPath $Directory)) {
            return
        }
        Start-Sleep -Milliseconds 500
    }
    if ($LastError) {
        throw "Failed to remove install directory ${Directory}: $LastError"
    }
    throw "Failed to remove install directory ${Directory}."
}

function Start-AppBuilderPostUninstallCleanup {
    param([string]$InstallDir, $Commands, [string]$PostUninstallDir)
    $Payload = [ordered]@{
        install_directory = $InstallDir
        post_uninstall_directory = $PostUninstallDir
        commands = @($Commands)
        environment = [ordered]@{
            app_builder_name = $env:app_builder_name
            app_builder_version = $env:app_builder_version
            app_builder_install_directory = $env:app_builder_install_directory
            app_builder_project_root = $env:app_builder_project_root
            app_builder_start_menu = $env:app_builder_start_menu
        }
    }
    $PayloadJson = $Payload | ConvertTo-Json -Depth 20 -Compress
    $PayloadBase64 = [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes($PayloadJson))
    $CleanupScript = @'
$ErrorActionPreference = 'Stop'

function Remove-DirectoryWithRetry {
    param([string]$Directory)
    if (-not (Test-Path -LiteralPath $Directory)) {
        return
    }
    $LastError = $null
    for ($Attempt = 0; $Attempt -lt 40; $Attempt += 1) {
        try {
            Remove-Item -LiteralPath $Directory -Recurse -Force -ErrorAction Stop
        } catch {
            $LastError = $_
        }
        if (-not (Test-Path -LiteralPath $Directory)) {
            return
        }
        Start-Sleep -Milliseconds 500
    }
    if ($LastError) {
        throw "Failed to remove install directory ${Directory}: $LastError"
    }
    throw "Failed to remove install directory ${Directory}."
}

function Invoke-PostUninstallHook {
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
    $Program = $Argv[0]
    $Arguments = @()
    if ($Argv.Count -gt 1) {
        $Arguments = $Argv[1..($Argv.Count - 1)]
    }
    $Extension = [System.IO.Path]::GetExtension($Program).ToLowerInvariant()
    $global:LASTEXITCODE = 0
    if ((Test-Path -LiteralPath $Program) -and $Extension -eq '.ps1') {
        & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $Program @Arguments
    } elseif ((Test-Path -LiteralPath $Program) -and $Extension -eq '.py') {
        throw "post_uninstall .py entrypoints are not auto-dispatched to system Python. Use a self-contained .cmd, .ps1, or .exe entrypoint, or call an explicit Python executable in the hook argv."
    } else {
        & $Program @Arguments
    }
    if ($LASTEXITCODE -ne 0) {
        throw "post_uninstall command failed with exit code ${LASTEXITCODE}: $($Argv -join ' ')"
    }
}

$PayloadJson = [Text.Encoding]::UTF8.GetString([Convert]::FromBase64String('__APP_BUILDER_PAYLOAD__'))
$Payload = $PayloadJson | ConvertFrom-Json
foreach ($Property in $Payload.environment.PSObject.Properties) {
    [Environment]::SetEnvironmentVariable($Property.Name, [string]$Property.Value, 'Process')
}
$Succeeded = $false
try {
    Set-Location $env:TEMP
    Start-Sleep -Milliseconds 500
    Remove-DirectoryWithRetry ([string]$Payload.install_directory)
    foreach ($Command in @($Payload.commands)) {
        Invoke-PostUninstallHook $Command ([string]$Payload.post_uninstall_directory)
    }
    $Succeeded = $true
} catch {
    if (-not [string]::IsNullOrWhiteSpace([string]$Payload.post_uninstall_directory)) {
        New-Item -ItemType Directory -Path ([string]$Payload.post_uninstall_directory) -Force | Out-Null
        Set-Content -LiteralPath (Join-Path ([string]$Payload.post_uninstall_directory) 'error.txt') -Value ([string]$_) -Encoding UTF8
    }
    throw
} finally {
    if ($Succeeded -and (Test-Path -LiteralPath ([string]$Payload.post_uninstall_directory))) {
        Remove-Item -LiteralPath ([string]$Payload.post_uninstall_directory) -Recurse -Force -ErrorAction SilentlyContinue
    }
}
'@.Replace('__APP_BUILDER_PAYLOAD__', $PayloadBase64)
    $EncodedCommand = [Convert]::ToBase64String([Text.Encoding]::Unicode.GetBytes($CleanupScript))
    Start-Process -FilePath 'powershell.exe' -ArgumentList @('-NoLogo', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-EncodedCommand', $EncodedCommand) -WindowStyle Hidden
}
"""
