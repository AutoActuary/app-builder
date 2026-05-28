from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from tempfile import TemporaryDirectory
from zipfile import ZIP_STORED, ZipFile

from .exewrap import (
    stamp_exe_icon,
    stamp_exe_wrap_config,
    vendored_console_launcher_bytes,
)

_INSTALLED_MANIFEST_NAME = "app-builder-manifest.json"
_POWERSHELL_HERE_STRING_END = "'@"
_INSTALL_CMD_NAME = "install.cmd"
_INSTALL_PS1_NAME = "bin/install.ps1"
_UNINSTALL_CMD_NAME = "bin/uninstall.cmd"
_UNINSTALL_PS1_NAME = "bin/uninstall.ps1"


def _json_for_embedded_powershell(
    value: object,
    *,
    indent: int | None = None,
    compact: bool = False,
) -> str:
    if compact:
        payload = json.dumps(value, ensure_ascii=True, separators=(",", ":"))
    else:
        payload = json.dumps(value, ensure_ascii=True, indent=indent)
    return payload.replace("'", "\\u0027")


def create_exewrap_zip_installer(
    output_path: Path,
    *,
    payload_archive: Path,
    manifest_path: Path,
    app_name: str,
    pause_on_exit: bool,
    add_uninstaller: bool,
    icon_path: Path | None = None,
    top_layer_files: Mapping[Path, str] | None = None,
    bootstrap_pre_extract_commands: list[list[str]] | None = None,
    launcher: bytes | None = None,
) -> None:
    if output_path.exists():
        output_path.unlink()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if icon_path is not None:
        launcher = stamp_exe_icon(
            launcher if launcher is not None else vendored_console_launcher_bytes(),
            icon_path,
        )
    output_path.write_bytes(
        stamp_exe_wrap_config(
            _render_bootstrap_config(bootstrap_pre_extract_commands),
            launcher=launcher,
            include_end_marker=True,
        )
    )

    with TemporaryDirectory() as temp_dir_str:
        temp_dir = Path(temp_dir_str)
        install_cmd = temp_dir / _INSTALL_CMD_NAME
        install_ps1 = temp_dir / _INSTALL_PS1_NAME
        uninstall_cmd = temp_dir / _UNINSTALL_CMD_NAME
        uninstall_ps1 = temp_dir / _UNINSTALL_PS1_NAME
        install_ps1.parent.mkdir(parents=True, exist_ok=True)
        manifest_json = _read_manifest_json_for_embedding(manifest_path)
        install_cmd.write_text(
            _render_install_cmd_wrapper(),
            encoding="utf-8",
        )
        install_ps1.write_text(
            _render_install_powershell_script(
                manifest_json=manifest_json,
                uninstall_enabled=add_uninstaller,
                pause_on_exit=pause_on_exit,
            ),
            encoding="utf-8",
        )
        if add_uninstaller:
            uninstall_cmd.write_text(
                _render_uninstall_cmd_wrapper(),
                encoding="utf-8",
            )
            uninstall_ps1.write_text(
                _render_uninstall_powershell_script(pause_on_exit=pause_on_exit),
                encoding="utf-8",
            )

        with ZipFile(output_path, "a", compression=ZIP_STORED) as zip_file:
            zip_file.write(install_cmd, install_cmd.name)
            zip_file.write(install_ps1, _INSTALL_PS1_NAME)
            if add_uninstaller:
                zip_file.write(uninstall_cmd, _UNINSTALL_CMD_NAME)
                zip_file.write(uninstall_ps1, _UNINSTALL_PS1_NAME)
            for source, archive_name in sorted(
                (top_layer_files or {}).items(), key=lambda item: item[1]
            ):
                zip_file.write(source, archive_name)
            zip_file.write(payload_archive, payload_archive.name)


def _render_bootstrap_config(
    bootstrap_pre_extract_commands: list[list[str]] | None = None,
) -> bytes:
    return json.dumps(
        {
            "command": [
                "powershell.exe",
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-Command",
                "& { "
                + _render_powershell_bootstrap(bootstrap_pre_extract_commands)
                + " }",
            ]
        },
        separators=(",", ":"),
    ).encode("utf-8")


def _render_powershell_bootstrap(
    bootstrap_pre_extract_commands: list[list[str]] | None = None,
) -> str:
    bootstrap_hooks = _render_bootstrap_hooks_powershell(
        bootstrap_pre_extract_commands or []
    )
    return (
        "$ErrorActionPreference = 'Stop'; "
        "$InstallerArgsJson = '@{args_as_json}'; "
        "[string[]]$InstallerArgs = $InstallerArgsJson | ConvertFrom-Json; "
        "$exitCode = 0; "
        "$extractDir = Join-Path $env:TEMP "
        "('app-builder-' + [guid]::NewGuid().ToString('N')); "
        "try { "
        f"{bootstrap_hooks} "
        "New-Item -ItemType Directory -Path $extractDir | Out-Null; "
        "tar.exe -xf '@{exe_path}' -C $extractDir; "
        "if ($LASTEXITCODE -ne 0) { "
        "$exitCode = $LASTEXITCODE; "
        'throw "tar.exe failed with exit code $exitCode" '
        "}; "
        "& (Join-Path $extractDir 'bin\\install.ps1') @InstallerArgs; "
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


def _render_bootstrap_hooks_powershell(commands: list[list[str]]) -> str:
    commands_json = _json_for_embedded_powershell(commands, compact=True)
    return (
        f"$BootstrapCommandsJson = '{commands_json}'; "
        "$BootstrapCommands = $BootstrapCommandsJson | ConvertFrom-Json; "
        "function Invoke-AppBuilderBootstrapCommand { "
        "param($Command); "
        "if ($null -eq $Command) { return }; "
        "$Argv = @(); "
        "foreach ($Item in @($Command)) { $Argv += [string]$Item }; "
        "if ($Argv.Count -eq 0) { return }; "
        "$Program = $Argv[0]; "
        "$Arguments = @(); "
        "if ($Argv.Count -gt 1) { "
        "$Arguments = $Argv[1..($Argv.Count - 1)] "
        "}; "
        "$global:LASTEXITCODE = 0; "
        "& $Program @Arguments; "
        "if (-not $?) { "
        "throw \"Bootstrap hook command failed: $($Argv -join ' ')\" "
        "}; "
        "if ($LASTEXITCODE -ne 0) { "
        "throw \"Bootstrap hook command failed with exit code ${LASTEXITCODE}: $($Argv -join ' ')\" "
        "} "
        "}; "
        "foreach ($RawCommand in @($BootstrapCommands)) { "
        "Invoke-AppBuilderBootstrapCommand $RawCommand "
        "};"
    )


def _read_manifest_json_for_embedding(manifest_path: Path) -> str:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest_json = _json_for_embedded_powershell(manifest, indent=2)
    if _contains_powershell_here_string_terminator(manifest_json):
        raise ValueError(
            f"{manifest_path} cannot be embedded in the installer script because "
            "it contains a PowerShell here-string terminator."
        )
    return manifest_json


def _contains_powershell_here_string_terminator(value: str) -> bool:
    normalized = value.replace("\r\n", "\n").replace("\r", "\n")
    return any(line == _POWERSHELL_HERE_STRING_END for line in normalized.split("\n"))


def _render_install_cmd_wrapper() -> str:
    return (
        "@echo off\n"
        'powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass '
        '-File "%~dp0bin\\install.ps1" %*\n'
        "exit /b %ERRORLEVEL%\n"
    )


def _render_uninstall_cmd_wrapper() -> str:
    return (
        "@echo off\n"
        'powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass '
        '-File "%~dp0uninstall.ps1" %*\n'
        "exit /b %ERRORLEVEL%\n"
    )


def _embedded_manifest_assignment(manifest_json: str) -> str:
    if _contains_powershell_here_string_terminator(manifest_json):
        raise ValueError(
            "Manifest JSON cannot be embedded because it contains a PowerShell "
            "here-string terminator."
        )
    return f"\n$EmbeddedManifestJson = @'\n{manifest_json}\n'@\n"


def _default_wait_assignment(pause_on_exit: bool) -> str:
    value = "$true" if pause_on_exit else "$false"
    return f"$AppBuilderDefaultWaitOnExit = {value}\n"


def _render_install_powershell_script(
    *,
    manifest_json: str,
    uninstall_enabled: bool,
    pause_on_exit: bool,
) -> str:
    return _render_install_powershell(
        manifest_json=manifest_json,
        uninstall_enabled=uninstall_enabled,
        pause_on_exit=pause_on_exit,
    )


def _render_uninstall_powershell_script(*, pause_on_exit: bool) -> str:
    return _render_uninstall_powershell(pause_on_exit=pause_on_exit)


def _render_install_powershell(
    *,
    manifest_json: str,
    uninstall_enabled: bool,
    pause_on_exit: bool,
) -> str:
    uninstall_copy_block = ""
    uninstall_shortcut_block = ""
    if uninstall_enabled:
        uninstall_copy_block = (
            "$InstalledBinDir = Join-Path $InstallDir 'bin'\n"
            "New-Item -ItemType Directory -Path $InstalledBinDir -Force | Out-Null\n"
            "Copy-Item -LiteralPath (Join-Path $ScriptRoot 'uninstall.cmd') "
            "-Destination (Join-Path $InstalledBinDir 'uninstall.cmd') -Force\n"
            "Copy-Item -LiteralPath (Join-Path $ScriptRoot 'uninstall.ps1') "
            "-Destination (Join-Path $InstalledBinDir 'uninstall.ps1') -Force\n"
        )
        uninstall_shortcut_block = (
            "$UninstallCommand = Join-Path $InstallDir 'bin\\uninstall.cmd'\n"
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
        + _default_wait_assignment(pause_on_exit)
        + """
$AppBuilderScriptOptions = Get-AppBuilderScriptOptions -Arguments @($args) -DefaultWaitOnExit $AppBuilderDefaultWaitOnExit
$AppBuilderExitCode = 0
try {
$ScriptRoot = $PSScriptRoot
$InstallerRoot = Split-Path -Parent $ScriptRoot
$Manifest = Read-AppBuilderManifestJson $EmbeddedManifestJson
$InstallDir = Resolve-AppBuilderPath ([string]$Manifest.install_directory) $null
$PayloadPath = Join-Path $InstallerRoot ([string]$Manifest.payload_archive)
$StagingDir = Join-Path $env:TEMP ('app-builder-install-' + [guid]::NewGuid().ToString('N'))
$BackupDir = $null
$StartMenuBackupDir = $null
$StartMenuTouched = $false
$MovedStaging = $false
$ExistingInstallKind = $null
$StartMenuDir = Get-AppBuilderStartMenuDirectory $Manifest

Write-Host ('Ready to install {0} {1} to {2}' -f $Manifest.name, $Manifest.version, $InstallDir)
Confirm-AppBuilderAction ('Continue installing {0}?' -f $Manifest.name) $AppBuilderScriptOptions.BypassQuestions
Write-Host ('Installing {0} {1}' -f $Manifest.name, $Manifest.version)
Set-AppBuilderEnvironment $Manifest $InstallDir $StartMenuDir

try {
    if (-not (Test-Path -LiteralPath $PayloadPath)) {
        throw "Payload archive not found: $PayloadPath"
    }
    New-Item -ItemType Directory -Path $StagingDir | Out-Null
    Expand-AppBuilderPayloadArchive $PayloadPath $StagingDir $InstallerRoot

    Invoke-AppBuilderHookList $Manifest.install_hooks.pre_install $StagingDir

    $InstallParent = Split-Path -Parent $InstallDir
    if ($InstallParent) {
        New-Item -ItemType Directory -Path $InstallParent -Force | Out-Null
    }
    if (Test-Path -LiteralPath $InstallDir) {
        $ExistingInstallKind = Get-AppBuilderExistingInstallKind $Manifest $InstallDir $StartMenuDir $InstalledManifestName
        if ($ExistingInstallKind -eq 'current') {
            $ExistingManifestPath = Join-Path $InstallDir $InstalledManifestName
            $ExistingManifest = Read-AppBuilderManifestFile $ExistingManifestPath
            Invoke-AppBuilderCurrentPreUninstall $ExistingManifest $InstallDir
            $BackupDir = Join-Path $InstallParent ((Split-Path -Leaf $InstallDir) + '.app-builder-backup-' + [guid]::NewGuid().ToString('N'))
            Move-AppBuilderDirectory $InstallDir $BackupDir 'existing install directory'
        } elseif ($ExistingInstallKind -eq 'legacy') {
            Invoke-AppBuilderLegacyPreUninstall $Manifest $InstallDir
            Remove-AppBuilderLegacyInstall $Manifest $InstallDir $StartMenuDir
        } else {
            throw "Internal error: unknown install target kind $ExistingInstallKind"
        }
    }
    Move-AppBuilderDirectory $StagingDir $InstallDir 'new staging directory'
    $MovedStaging = $true

    Set-Content -LiteralPath (Join-Path $InstallDir $InstalledManifestName) -Value $EmbeddedManifestJson -Encoding UTF8
"""
        + uninstall_copy_block
        + """
    $StartMenuBackupDir = Backup-AppBuilderStartMenuDirectory $StartMenuDir
    $StartMenuTouched = $true
    New-AppBuilderStartMenuShortcuts $Manifest $InstallDir $StartMenuDir
"""
        + uninstall_shortcut_block
        + """
    Invoke-AppBuilderHookList $Manifest.install_hooks.post_install $InstallDir

    Remove-AppBuilderBackupDirectory $BackupDir 'previous install backup'
    Remove-AppBuilderBackupDirectory $StartMenuBackupDir 'previous Start Menu backup'
    Write-Host ('Installed to {0}' -f $InstallDir)
} catch {
    if ($MovedStaging -and (Test-Path -LiteralPath $InstallDir)) {
        Remove-Item -LiteralPath $InstallDir -Recurse -Force -ErrorAction SilentlyContinue
    }
    if ($StartMenuTouched -and (Test-Path -LiteralPath $StartMenuDir)) {
        Remove-Item -LiteralPath $StartMenuDir -Recurse -Force -ErrorAction SilentlyContinue
    }
    if ($StartMenuBackupDir -and (Test-Path -LiteralPath $StartMenuBackupDir)) {
        Restore-AppBuilderDirectory $StartMenuBackupDir $StartMenuDir 'previous Start Menu directory'
    }
    if (($ExistingInstallKind -eq 'current') -and $BackupDir -and (Test-Path -LiteralPath $BackupDir)) {
        Restore-AppBuilderDirectory $BackupDir $InstallDir 'previous install directory'
    }
    throw
} finally {
    if ((-not $MovedStaging) -and (Test-Path -LiteralPath $StagingDir)) {
        Remove-Item -LiteralPath $StagingDir -Recurse -Force -ErrorAction SilentlyContinue
    }
}
} catch {
    $AppBuilderExitCode = 1
    Write-Error $_ -ErrorAction Continue
} finally {
    Wait-AppBuilderBeforeExit $AppBuilderScriptOptions
}
exit $AppBuilderExitCode
"""
    )


def _render_uninstall_powershell(*, pause_on_exit: bool) -> str:
    return (
        _powershell_common_functions()
        + f"$InstalledManifestName = '{_INSTALLED_MANIFEST_NAME}'\n"
        + _default_wait_assignment(pause_on_exit)
        + """
$AppBuilderScriptOptions = Get-AppBuilderScriptOptions -Arguments @($args) -DefaultWaitOnExit $AppBuilderDefaultWaitOnExit
$AppBuilderExitCode = 0
try {
$ScriptRoot = $PSScriptRoot
$InstallDir = Split-Path -Parent $ScriptRoot
$ManifestPath = Join-Path $InstallDir $InstalledManifestName
$Manifest = Read-AppBuilderManifestFile $ManifestPath
$StartMenuDir = Get-AppBuilderStartMenuDirectory $Manifest
$PostUninstallDir = Join-Path $env:TEMP ('app-builder-post-uninstall-' + [guid]::NewGuid().ToString('N'))
$StartedCleanup = $false

Write-Host ('Ready to uninstall {0} from {1}' -f $Manifest.name, $InstallDir)
Confirm-AppBuilderAction ('Continue uninstalling {0}?' -f $Manifest.name) $AppBuilderScriptOptions.BypassQuestions
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
} catch {
    $AppBuilderExitCode = 1
    Write-Error $_ -ErrorAction Continue
} finally {
    Wait-AppBuilderBeforeExit $AppBuilderScriptOptions
}
exit $AppBuilderExitCode
"""
    )


def _powershell_common_functions() -> str:
    return r"""Set-StrictMode -Version 3.0
$ErrorActionPreference = 'Stop'

function Get-AppBuilderScriptOptions {
    param($Arguments, [bool]$DefaultWaitOnExit)
    $Argv = @()
    foreach ($Item in @($Arguments)) {
        $Argv += [string]$Item
    }
    $BypassQuestions = $false
    $NoWait = $false
    foreach ($Arg in $Argv) {
        $Normalized = $Arg.ToLowerInvariant()
        if (@('--yes', '-yes', '-y', '/y', '--non-interactive', '-noninteractive', '--no-prompt', '-noprompt').Contains($Normalized)) {
            $BypassQuestions = $true
        }
        if (@('--no-wait', '-no-wait', '-nowait').Contains($Normalized)) {
            $NoWait = $true
        }
    }
    if ($BypassQuestions) {
        $NoWait = $true
    }
    return [pscustomobject]@{
        BypassQuestions = $BypassQuestions
        WaitOnExit = $DefaultWaitOnExit
        NoWait = $NoWait
        Arguments = $Argv
    }
}

function Confirm-AppBuilderAction {
    param([string]$Prompt, [bool]$BypassQuestions)
    if ($BypassQuestions) {
        return
    }
    $Answer = Read-Host ($Prompt + ' [y/N]')
    if ($null -eq $Answer) {
        $Answer = ''
    }
    if (-not @('y', 'yes').Contains(([string]$Answer).ToLowerInvariant())) {
        throw 'Cancelled by user.'
    }
}

function Wait-AppBuilderBeforeExit {
    param($Options)
    if ($null -eq $Options) {
        return
    }
    if ((-not [bool]$Options.WaitOnExit) -or [bool]$Options.NoWait) {
        return
    }
    Write-Host 'Press Enter to close now, or wait 30 seconds. Use --yes or --no-wait to skip this wait.'
    $Deadline = [DateTime]::UtcNow.AddSeconds(30)
    while ([DateTime]::UtcNow -lt $Deadline) {
        if ([Console]::KeyAvailable) {
            $Key = [Console]::ReadKey($true)
            if ($Key.Key -eq [ConsoleKey]::Enter) {
                return
            }
            continue
        }
        Start-Sleep -Milliseconds 100
    }
}

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

function Expand-AppBuilderPayloadArchive {
    param(
        [string]$PayloadPath,
        [string]$Destination,
        [string]$ScriptRoot
    )
    $Extension = [System.IO.Path]::GetExtension($PayloadPath).ToLowerInvariant()
    if ($Extension -eq '.zip') {
        tar.exe -xf $PayloadPath -C $Destination
        if ($LASTEXITCODE -ne 0) {
            throw "tar.exe failed to extract payload with exit code $LASTEXITCODE"
        }
        return
    }
    if ($Extension -eq '.7z') {
        $SevenZip = Join-Path $ScriptRoot 'bin\7z.exe'
        if (-not (Test-Path -LiteralPath $SevenZip -PathType Leaf)) {
            throw "Bundled 7z.exe is missing from installer top layer: $SevenZip"
        }
        $SevenZipOutput = & $SevenZip x -y -bd "-o$Destination" $PayloadPath 2>&1
        if ($LASTEXITCODE -ne 0) {
            foreach ($Line in @($SevenZipOutput)) {
                Write-Host $Line
            }
            throw "7z.exe failed to extract payload with exit code $LASTEXITCODE"
        }
        return
    }
    throw "Unsupported payload archive extension: $Extension"
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

function Backup-AppBuilderStartMenuDirectory {
    param([string]$StartMenuDir)
    if (-not (Test-Path -LiteralPath $StartMenuDir)) {
        return $null
    }
    $Parent = Split-Path -Parent $StartMenuDir
    if ([string]::IsNullOrWhiteSpace($Parent)) {
        return $null
    }
    New-Item -ItemType Directory -Path $Parent -Force | Out-Null
    $BackupDir = Join-Path $Parent ((Split-Path -Leaf $StartMenuDir) + '.app-builder-backup-' + [guid]::NewGuid().ToString('N'))
    Move-AppBuilderDirectory $StartMenuDir $BackupDir 'Start Menu directory'
    return $BackupDir
}

function Move-AppBuilderDirectory {
    param([string]$Source, [string]$Destination, [string]$Description)
    try {
        Move-Item -LiteralPath $Source -Destination $Destination -ErrorAction Stop
    } catch {
        throw "Failed to move ${Description} from '${Source}' to '${Destination}'. The existing install was not replaced. Close running app files and try again. $($_.Exception.Message)"
    }
}

function Restore-AppBuilderDirectory {
    param([string]$Source, [string]$Destination, [string]$Description)
    try {
        Move-Item -LiteralPath $Source -Destination $Destination -ErrorAction Stop
    } catch {
        Write-Warning "Failed to restore ${Description} from '${Source}' to '${Destination}'. Manual recovery may be required. $($_.Exception.Message)"
    }
}

function Remove-AppBuilderBackupDirectory {
    param(
        [AllowNull()][string]$Directory,
        [string]$Description
    )
    if ([string]::IsNullOrWhiteSpace($Directory)) {
        return
    }
    if (-not (Test-Path -LiteralPath $Directory)) {
        return
    }
    try {
        Remove-AppBuilderInstallDirectory $Directory
    } catch {
        Write-Warning "Installed successfully, but failed to remove ${Description} at '${Directory}'. You can remove it manually. $($_.Exception.Message)"
    }
}

function Get-AppBuilderObjectProperty {
    param($Object, [string]$Name)
    if ($null -eq $Object) {
        return $null
    }
    $Property = $Object.PSObject.Properties[$Name]
    if ($null -eq $Property) {
        return $null
    }
    return $Property.Value
}

function Read-AppBuilderManifestFile {
    param([string]$ManifestPath)
    try {
        $Json = Get-Content -LiteralPath $ManifestPath -Raw -ErrorAction Stop
        return Read-AppBuilderManifestJson $Json
    } catch {
        throw "Existing app-builder manifest is corrupt or unreadable: $ManifestPath. Refusing to replace install directory. $($_.Exception.Message)"
    }
}

function Assert-AppBuilderManifestIdentity {
    param($CurrentManifest, $ExistingManifest, [string]$InstallDir)
    $CurrentName = [string](Get-AppBuilderObjectProperty $CurrentManifest 'name')
    $ExistingName = [string](Get-AppBuilderObjectProperty $ExistingManifest 'name')
    if ([string]::IsNullOrWhiteSpace($ExistingName) -or -not $ExistingName.Equals($CurrentName, [System.StringComparison]::OrdinalIgnoreCase)) {
        throw "Install directory already contains a different app-builder app at ${InstallDir}: expected '$CurrentName', found '$ExistingName'. Refusing to overwrite."
    }
}

function Get-AppBuilderUninstallNames {
    param($Manifest)
    $Names = New-Object System.Collections.Generic.List[string]
    $RawName = [string](Get-AppBuilderObjectProperty $Manifest 'name')
    if (-not [string]::IsNullOrWhiteSpace($RawName)) {
        $Names.Add($RawName)
        $SafeName = Get-SafeShortcutName $RawName
        if (-not $SafeName.Equals($RawName, [System.StringComparison]::OrdinalIgnoreCase)) {
            $Names.Add($SafeName)
        }
    }
    return ,($Names | Select-Object -Unique)
}

function Get-AppBuilderLegacyUninstallEntrypoint {
    param($Manifest, [string]$InstallDir)
    foreach ($Name in (Get-AppBuilderUninstallNames $Manifest)) {
        foreach ($Extension in @('.bat', '.cmd')) {
            $Candidate = Join-Path $InstallDir (Join-Path 'bin' ('Uninstall ' + $Name + $Extension))
            if (Test-Path -LiteralPath $Candidate -PathType Leaf) {
                return [System.IO.Path]::GetFullPath($Candidate)
            }
        }
    }
    return $null
}

function Test-AppBuilderLegacyDirectoryShape {
    param([string]$InstallDir)
    if (-not (Test-Path -LiteralPath (Join-Path $InstallDir 'bin') -PathType Container)) {
        return $false
    }
    foreach ($DirectoryName in @('scripts', 'src', 'py', 'cli')) {
        if (Test-Path -LiteralPath (Join-Path $InstallDir $DirectoryName) -PathType Container) {
            return $true
        }
    }
    return $false
}

function Test-AppBuilderLegacyUninstallRegistration {
    param($Manifest, [string]$InstallDir, [string]$StartMenuDir)
    foreach ($Name in (Get-AppBuilderUninstallNames $Manifest)) {
        $ShortcutName = 'Uninstall ' + $Name + '.lnk'
        $InstallShortcut = Join-Path $InstallDir $ShortcutName
        $StartMenuShortcut = Join-Path $StartMenuDir $ShortcutName
        if ((Test-Path -LiteralPath $InstallShortcut -PathType Leaf) -or (Test-Path -LiteralPath $StartMenuShortcut -PathType Leaf)) {
            return $true
        }
    }
    return $false
}

function Test-AppBuilderLegacyInstall {
    param($Manifest, [string]$InstallDir, [string]$StartMenuDir)
    if (-not (Test-AppBuilderLegacyDirectoryShape $InstallDir)) {
        return $false
    }
    if ([string]::IsNullOrWhiteSpace((Get-AppBuilderLegacyUninstallEntrypoint $Manifest $InstallDir))) {
        return $false
    }
    return Test-AppBuilderLegacyUninstallRegistration $Manifest $InstallDir $StartMenuDir
}

function Get-AppBuilderExistingInstallKind {
    param($Manifest, [string]$InstallDir, [string]$StartMenuDir, [string]$InstalledManifestName)
    $ExistingManifestPath = Join-Path $InstallDir $InstalledManifestName
    if (Test-Path -LiteralPath $ExistingManifestPath -PathType Leaf) {
        $ExistingManifest = Read-AppBuilderManifestFile $ExistingManifestPath
        Assert-AppBuilderManifestIdentity $Manifest $ExistingManifest $InstallDir
        return 'current'
    }
    if (Test-AppBuilderLegacyInstall $Manifest $InstallDir $StartMenuDir) {
        return 'legacy'
    }
    $Name = [string](Get-AppBuilderObjectProperty $Manifest 'name')
    throw "Install directory already exists but is not a recognized app-builder install for '$Name': $InstallDir. Refusing to overwrite. app-builder does not use payload files such as version.txt, python-version.txt, or gitinformation.json as install markers."
}

function Invoke-AppBuilderCurrentPreUninstall {
    param($ExistingManifest, [string]$InstallDir)
    $InstallHooks = Get-AppBuilderObjectProperty $ExistingManifest 'install_hooks'
    $PreUninstall = Get-AppBuilderObjectProperty $InstallHooks 'pre_uninstall'
    Invoke-AppBuilderHookList $PreUninstall $InstallDir
}

function Invoke-AppBuilderLegacyPreUninstall {
    param($Manifest, [string]$InstallDir)
    Write-Host ('Running legacy pre-uninstall hooks for {0}' -f $Manifest.name)
    foreach ($DirectoryName in @('.', 'bin', 'src', 'scripts')) {
        if ($DirectoryName -eq '.') {
            $HookDirectory = $InstallDir
        } else {
            $HookDirectory = Join-Path $InstallDir $DirectoryName
        }
        foreach ($Extension in @('.bat', '.cmd')) {
            $HookPath = Join-Path $HookDirectory ('pre-uninstall' + $Extension)
            if (Test-Path -LiteralPath $HookPath -PathType Leaf) {
                $global:LASTEXITCODE = 0
                & $HookPath
                if ($LASTEXITCODE -ne 0) {
                    throw "Legacy pre-uninstall hook failed with exit code ${LASTEXITCODE}: $HookPath"
                }
            }
        }
    }
}

function Remove-AppBuilderLegacyInstall {
    param($Manifest, [string]$InstallDir, [string]$StartMenuDir)
    $Name = [string](Get-AppBuilderObjectProperty $Manifest 'name')
    Write-Host ('Removing legacy app-builder install for {0}' -f $Name)
    if (-not [string]::IsNullOrWhiteSpace($Name)) {
        Remove-Item -LiteralPath ('HKCU:\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\' + $Name) -Recurse -Force -ErrorAction SilentlyContinue
    }
    if (Test-Path -LiteralPath $StartMenuDir) {
        Remove-AppBuilderInstallDirectory $StartMenuDir
    }
    Remove-AppBuilderInstallDirectory $InstallDir
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
    try {
        if (-not [string]::IsNullOrWhiteSpace($env:SystemRoot)) {
            Set-Location $env:SystemRoot
        }
    } catch {
    }
    if ($Succeeded -and (Test-Path -LiteralPath ([string]$Payload.post_uninstall_directory))) {
        Remove-Item -LiteralPath ([string]$Payload.post_uninstall_directory) -Recurse -Force -ErrorAction SilentlyContinue
    }
}
'@.Replace('__APP_BUILDER_PAYLOAD__', $PayloadBase64)
    $EncodedCommand = [Convert]::ToBase64String([Text.Encoding]::Unicode.GetBytes($CleanupScript))
    Start-Process -FilePath 'powershell.exe' -ArgumentList @('-NoLogo', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-EncodedCommand', $EncodedCommand) -WindowStyle Hidden
}
"""
