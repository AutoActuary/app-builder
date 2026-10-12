function Get-AppBuilderDirectoryMoveFailure {
    param([Exception]$Exception)
    # PowerShell wraps static .NET calls in MethodInvocationException.
    while ($null -ne $Exception.InnerException) { $Exception = $Exception.InnerException }
    $NativeError = $null
    if (($Exception.HResult -band 0xFFFF0000) -eq 0x80070000) {
        $NativeError = $Exception.HResult -band 0xFFFF
    }
    $Diagnostics = '{0}, HRESULT 0x{1:X8}' -f $Exception.GetType().FullName, $Exception.HResult
    if ($null -ne $NativeError) { $Diagnostics += ", Native error $NativeError" }
    return [pscustomobject]@{
        Exception = $Exception
        Retryable = $NativeError -in @(5, 32)
        Diagnostics = $Diagnostics
    }
}

function Move-AppBuilderDirectoryWithRetry {
    param([string]$Source, [string]$Destination, [string]$Description)
    # Seven attempts, with at most 3.5 seconds of automatic waiting per move.
    $RetryDelays = @(100, 200, 400, 800, 1000, 1000)
    for ($Attempt = 0; $Attempt -le $RetryDelays.Count; $Attempt++) {
        try {
            # Directory.Move refuses occupied destinations rather than merging trees.
            [IO.Directory]::Move($Source, $Destination)
            return
        } catch {
            $Failure = Get-AppBuilderDirectoryMoveFailure $_.Exception
            if ($Failure.Retryable -and $Attempt -lt $RetryDelays.Count) {
                Write-Warning "Retrying directory move for ${Description} after attempt $($Attempt + 1): $($Failure.Diagnostics). $($Failure.Exception.Message)"
                Start-Sleep -Milliseconds $RetryDelays[$Attempt]
                continue
            }
            $Message = "Cannot move ${Description} from '${Source}' to '${Destination}' after $($Attempt + 1) attempts. $($Failure.Diagnostics). $($Failure.Exception.Message)"
            throw [IO.IOException]::new($Message, $Failure.Exception)
        }
    }
}

function Test-AppBuilderDirectoryMove {
    param([string]$Directory)
    if (-not (Test-Path -LiteralPath $Directory)) { return $null }
    if ((Get-Item -LiteralPath $Directory -Force).Attributes -band [IO.FileAttributes]::ReparsePoint) {
        throw "Refusing to replace a directory that is a link: $Directory"
    }
    $MovedDirectory = $Directory + '_moved' + [guid]::NewGuid().ToString('N').Substring(0, 8)
    $Moved = $false
    $Restored = $false
    try {
        Move-AppBuilderDirectory $Directory $MovedDirectory 'existing directory'
        $Moved = $true
    } finally {
        if ($Moved) {
            try {
                Move-AppBuilderDirectoryWithRetry $MovedDirectory $Directory 'previous directory name'
                $Restored = $true
            } catch {
                $Failure = Get-AppBuilderDirectoryMoveFailure $_.Exception
                if (-not $Failure.Retryable) { throw }
                Write-Warning $_.Exception.Message
            }
        }
    }
    if (-not $Restored) {
        if (-not (Test-Path -LiteralPath $MovedDirectory -PathType Container) -or
            ((Get-Item -LiteralPath $MovedDirectory -Force).Attributes -band [IO.FileAttributes]::ReparsePoint)) {
            throw "Cannot continue: recovery directory is missing or is a link at '$MovedDirectory'."
        }
        Write-Warning "Could not move the directory back. Continuing with the old files preserved at '$MovedDirectory'."
        return $MovedDirectory
    }
    return $null
}

function Remove-AppBuilderTree {
    param([string]$Path)
    $Item = Get-Item -LiteralPath $Path -Force -ErrorAction Stop
    $Failures = @()
    if ($Item.PSIsContainer -and -not ($Item.Attributes -band [IO.FileAttributes]::ReparsePoint)) {
        foreach ($Child in @(Get-ChildItem -LiteralPath $Path -Force -ErrorAction Stop)) {
            try { Remove-AppBuilderTree $Child.FullName } catch { $Failures += $_.Exception.Message }
        }
    }
    try {
        if ($Item.PSIsContainer) {
            if (-not ($Item.Attributes -band [IO.FileAttributes]::ReparsePoint)) {
                $Item.Attributes = $Item.Attributes -band (-bnot [IO.FileAttributes]::ReadOnly)
            }
            # Never follow a child junction or recursively delete its target.
            [IO.Directory]::Delete($Path, $false)
        } else {
            Remove-Item -LiteralPath $Path -Force -ErrorAction Stop
        }
    } catch { $Failures += $_.Exception.Message }
    if ($Failures.Count) { throw ($Failures -join "`n") }
}

function Test-AppBuilderCommandTargets {
    param([string]$Command, [string]$Directory)
    foreach ($Token in [regex]::Matches($Command, '"[^"\r\n]*"|[^\s"]+')) {
        $Path = [Environment]::ExpandEnvironmentVariables($Token.Value.Trim('"'))
        if (-not [IO.Path]::IsPathRooted($Path)) { continue }
        try { if (Test-AppBuilderPathIsSameOrChild $Path $Directory) { return $true } } catch { }
    }
    return $false
}
