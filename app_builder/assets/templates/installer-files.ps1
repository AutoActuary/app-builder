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
            for ($Attempt = 0; $Attempt -lt 3; $Attempt++) {
                try {
                    [IO.Directory]::Move($MovedDirectory, $Directory)
                    $Restored = $true
                    break
                } catch {
                    if ($Attempt -lt 2) { Start-Sleep -Milliseconds 150 }
                }
            }
        }
    }
    if (-not $Restored) {
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
