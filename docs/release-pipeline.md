# Release Pipeline

This document describes the 1.x release path that starts from
`app_builder.yaml` and ends with local artifacts or a GitHub release.

## Config Loading

`app_builder.yaml` is parsed as YAML, then string interpolation runs before the
dataclass schema is validated. Supported interpolation namespaces are:

- `${ENV.NAME}` for process environment variables.
- `${GIT.DESCRIBE}`, `${GIT.COMMIT}`, `${GIT.SHORT_COMMIT}`,
  `${GIT.BRANCH}`, `${GIT.TAG}`, and `${GIT.IS_DIRTY}` for repository state.
- `${APP.VERSION}` for the release version selected by `--version` or git
  version detection.
- `${CONFIG.path.to.value}` for another resolved string value in the same
  config.

Interpolation is string-only. References to lists or mappings fail loudly, as
do missing values and circular `CONFIG.*` references. `app_builder_version`
stays literal because the command dispatcher reads it before importing the full
1.x application code.

## Payload Build

The build command runs dependency stages and build hooks, collects configured
files, applies `installer.paths.remap`, adds generated files such as
`version.txt`, and writes the inner payload archive.

`installer.payload_format` controls that inner archive:

- `zip` is the default and writes `<name>-<version>.zip` with Python's
  `ZipFile`.
- `7z` writes `<name>-<version>.7z` with the vendored 7-Zip runtime.

The 7z writer uses the same careful shape as old app-builder where it matters:
remapped files are staged under their target archive names, files that 7z cannot
read directly because of Windows locking are copied to temp first, and normal
7-Zip banner/progress/success output is suppressed while failures remain
readable.

## Installer Build

The installer is an ExeWrap console launcher with an appended stored ZIP. The
outer ZIP is intentionally stored, not compressed, so Windows can still treat
the installer as a ZIP if a user manually renames it to `.zip`.

The outer layer always contains:

- `install.cmd`
- `uninstall.cmd` when `installer.add_uninstaller` is true
- the inner payload archive

When `installer.payload_format: 7z` is selected, the outer layer also contains:

- `bin/7z.exe`
- `bin/7z.dll`

The generated installer extracts the outer layer to a random temp directory via
ExeWrap and PowerShell. It extracts ZIP payloads with Windows `tar.exe` and 7z
payloads with the bundled `bin\7z.exe`, so the target machine does not need
7-Zip installed.

## Icons

`installer.icon` is the single icon setting. It is used as the default Start
Menu shortcut icon when a shortcut does not specify its own icon, and it is also
embedded into generated ExeWrap executables.

For app-builder's dogfood build, the same icon is embedded into the generated
payload `app-builder.exe`.

## Release Artifacts

A local release produces:

- the inner payload archive, `.zip` or `.7z`
- the installer executable, `<name>-<version>-installer.exe`
- the manifest JSON

`release-gh` uploads those same artifacts through GitHub CLI (`gh.exe`). It does
not need special handling for 7z payloads; the payload archive path in
`ReleaseResult` points at whichever format the build produced.
