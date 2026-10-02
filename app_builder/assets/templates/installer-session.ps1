function Test-AppBuilderConsole {
    try {
        return -not ([Console]::IsInputRedirected -or [Console]::IsOutputRedirected)
    } catch { return $false }
}

function Get-AppBuilderScriptOptions {
    param($Arguments, [bool]$DefaultWaitOnExit)
    $BypassQuestions = $false
    $NoWait = $false
    foreach ($Arg in @($Arguments)) {
        switch (([string]$Arg).ToLowerInvariant()) {
            '--yes' { $BypassQuestions = $true; $NoWait = $true }
            '--no-wait' { $NoWait = $true }
            default { throw 'Unknown installer argument. Use --yes for unattended installation, or --no-wait to suppress interaction.' }
        }
    }
    return [pscustomobject]@{
        BypassQuestions = $BypassQuestions
        WaitOnExit = $DefaultWaitOnExit
        NoWait = $NoWait
        Interactive = (-not $NoWait) -and (Test-AppBuilderConsole)
        Arguments = @($Arguments)
    }
}

function Confirm-AppBuilderAction {
    param([string]$Prompt, [bool]$BypassQuestions)
    if ($BypassQuestions) { return }
    if (-not $AppBuilderScriptOptions.Interactive) {
        throw 'Confirmation requires an interactive console. Use --yes for unattended installation.'
    }
    $Answer = Read-Host ($Prompt + ' [y/N]')
    if ([string]$Answer -notin @('y', 'yes')) { throw 'Cancelled by user.' }
}

function Request-AppBuilderRetry {
    param([string]$Message)
    if ($null -eq $AppBuilderScriptOptions -or -not $AppBuilderScriptOptions.Interactive) { return $false }
    Write-Warning $Message
    $Answer = Read-Host 'Resolve the problem above. Save work before closing an application. Press Enter to retry, or type cancel'
    return [string]$Answer -eq ''
}

function Wait-AppBuilderBeforeExit {
    param($Options)
    if ($null -eq $Options -or -not $Options.WaitOnExit -or -not $Options.Interactive) { return }
    [void](Read-Host 'Press Enter to close')
}

function Start-AppBuilderInstallerLog {
    if (-not [string]::IsNullOrWhiteSpace($env:APP_BUILDER_INSTALL_LOG)) { return $false }
    try {
        $Directory = Join-Path $env:LOCALAPPDATA 'app-builder-logs'
        New-Item -ItemType Directory -Path $Directory -Force | Out-Null
        $Path = Join-Path $Directory ('installer-' + [guid]::NewGuid().ToString('N') + '.log')
        Start-Transcript -LiteralPath $Path | Out-Null
        $env:APP_BUILDER_INSTALL_LOG = $Path
        return $true
    } catch {
        Write-Warning "Could not start installer log: $($_.Exception.Message)"
        return $false
    }
}

function Stop-AppBuilderInstallerLog {
    param([bool]$Started)
    if (-not $Started) { return }
    if (-not [string]::IsNullOrWhiteSpace($env:APP_BUILDER_INSTALL_LOG)) { Write-Host ('Log: ' + $env:APP_BUILDER_INSTALL_LOG) }
    if ($Started) {
        try { Stop-Transcript | Out-Null } catch { Write-Warning $_.Exception.Message }
        Remove-Item Env:\APP_BUILDER_INSTALL_LOG -ErrorAction SilentlyContinue
    }
}
