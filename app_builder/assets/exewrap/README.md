# Vendored ExeWrap launcher

This directory contains the 64-bit ExeWrap 2.1.0 console launcher used to
create the outer app-builder installer executable.

app-builder vendors this launcher directly because it is small enough to keep
in the repository, keeps installer builds offline-friendly, and avoids a
runtime asset download step for the first-layer installer bootstrap.

This vendored version is required for `@{args_as_json}`, which lets
app-builder pass installer arguments through the PowerShell bootstrap as JSON
instead of relying on PowerShell `-Command` tail parsing. The installer
bootstrap decodes that JSON with `ConvertFrom-Json` and splats the resulting
strings into `bin\install.ps1`.

## Manifest note

`ExeWrap-console-x64.exe` is intentionally patched with an embedded Windows
application manifest that requests `asInvoker`.

This matters because Windows applies installer-elevation heuristics to
executables with names such as `setup.exe`, `install.exe`, and
`*-installer.exe` when they do not declare an execution level. app-builder
generates installer files with names like `my-app-v1.0.0-installer.exe`, so an
unpatched launcher can trigger an unwanted UAC prompt before ExeWrap starts.

The explicit `asInvoker` manifest tells Windows to run the installer with the
current user's privileges unless the user launches it elevated themselves.

## Replacement checklist

If this binary is replaced:

1. Confirm the replacement is the intended 64-bit console ExeWrap launcher.
2. Embed or preserve the `asInvoker` application manifest.
3. Update `EXE_WRAP_CONSOLE_X64_SHA256` in `app_builder/exewrap.py`.
4. Run the ExeWrap launcher tests, including the manifest and `args_as_json`
   checks.
5. Build and run a real `*-installer.exe` once on Windows to confirm it does
   not trigger an unexpected UAC prompt.
