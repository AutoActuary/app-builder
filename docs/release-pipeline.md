# Release Pipeline

This is the current 1.x release path from `app_builder.yaml` to local artifacts or GitHub Releases.

## 1. Command Entry

```text
app-builder release [--version <version>]
app-builder release-gh [--version <version>] [--draft | --no-draft]
```

`release` creates local artifacts. `release-gh` runs the same local build first, then uploads the resulting artifact set with GitHub CLI (`gh.exe`).

When `--version` is omitted, app-builder uses git-based version detection and falls back to `0.0.0-dev`.

## 2. Config Loading

`app_builder.yaml` is parsed as YAML, then string interpolation runs before dataclass schema validation.

Supported interpolation variables:

- `${ENV.NAME}`
- `${GIT.DESCRIBE}`
- `${GIT.COMMIT}`
- `${GIT.SHORT_COMMIT}`
- `${GIT.BRANCH}`
- `${GIT.TAG}`
- `${GIT.IS_DIRTY}`
- `${APP.VERSION}`
- `${CONFIG.path.to.value}`

Interpolation is string-only. References to lists or mappings fail loudly, as do missing values and circular `CONFIG.*` references. `app_builder_version` stays literal because the command dispatcher reads it from plain YAML before importing the full 1.x application code.

## 3. Dependency And Build Hooks

The release path runs dependency stages before file collection:

- `pre_process`
- `pre_python_bundled`
- `post_python_bundled`
- `pre_python_venv`
- `post_python_venv`
- `pre_dist`

Python dependencies come from `pyproject.toml` and Poetry. If a hook command starts with an existing `.py` file, app-builder runs it with the Python runtime configured for the project, preferring `python_venv` and then `python_bundled`. A hook such as `[scripts/build.py]` does not need `python.exe` on PATH. A hook such as `[python, scripts/build.py]` intentionally uses whatever `python` the machine provides.

`pre_dist` is the last hook that can generate files for the payload through normal include/remap rules.

## 4. Payload Build

app-builder collects project-relative files with:

- `installer.paths.include`
- `installer.paths.exclude`
- `installer.paths.remap`

Remap entries are source and destination pairs. Archive destinations are validated so a remap cannot write outside the staged payload root.

Generated payload metadata includes `version.txt`. That file is not an install identity marker; current installer identity comes from the embedded manifest.

`installer.payload_format` controls the inner archive:

- `zip` writes `<slug>-<version>.zip`.
- `7z` writes `<slug>-<version>.7z`.

The 7z writer keeps the useful 0.x behaviors without reviving the old tool folder model: remapped files are staged under their target archive names, files that 7z cannot read directly because of Windows locks are copied to temp first, and routine 7-Zip banner/progress/success output is suppressed while failures remain readable.

## 5. Manifest Build

The release manifest is written next to the artifacts and embedded into the installer scripts. It contains:

- app name and version;
- configured install directory;
- payload archive name;
- uninstaller flag;
- Start Menu entries;
- install and uninstall hook argv lists;
- included payload file records.

The installed uninstaller reads the manifest for metadata and hooks. It does not use the manifest as authority for the deletion root.

## 6. Installer Build

The installer is a self-extracting executable with an appended stored ZIP. The outer ZIP is stored, not compressed, so Windows can still read it as a ZIP if a user renames the installer to `.zip`.

The outer layer layout is:

```text
install.cmd
bin/install.ps1
bin/uninstall.cmd       # when installer.add_uninstaller is true
bin/uninstall.ps1       # when installer.add_uninstaller is true
bin/7z.exe              # only when installer.payload_format: 7z
bin/7z.dll              # only when installer.payload_format: 7z
<slug>-<version>.zip    # or .7z
```

`install.cmd` is a manual helper for users who rename or extract the installer ZIP by hand. The normal executable path runs the PowerShell installer directly and forwards all command-line arguments.

## 7. Installer Bootstrap

The generated bootstrap:

1. runs `installer.bootstrap_hooks.pre_extract`;
2. creates a random temp extraction directory under `%TEMP%`;
3. extracts the outer layer with `tar.exe -xf '<installer.exe>' -C <temp>`;
4. runs the PowerShell installer script and forwards all command-line arguments;
5. removes the temp extraction directory.

## 8. Bootstrap Hooks

`installer.bootstrap_hooks.pre_extract` commands run before the outer installer layer is extracted. They are useful for banners, early checks, or other machine-level work that does not need app files.

These hooks are structured argv lists, not raw PowerShell strings. app-builder runs the argv as given. If a project explicitly runs `cmd.exe /C`, then cmd's own parsing rules apply because the project asked for a shell.

Because this hook runs before extraction, it cannot use the app payload, `install.cmd`, `bin/install.ps1`, bundled 7z tools, or staged app files.

## 9. Installation Runtime

`bin/install.ps1` performs the actual install:

- confirms the action unless a bypass flag is supplied;
- extracts the inner ZIP with `tar.exe` or the inner 7z with bundled `bin\7z.exe`;
- recognizes current app-builder installs for the same app;
- recognizes selected legacy app-builder install shapes for upgrade;
- refuses unknown directories and different app-builder apps by default;
- runs `pre_install`;
- replaces the app directory with rollback support for recognized current installs;
- writes the installed manifest;
- copies `bin\uninstall.cmd` and `bin\uninstall.ps1` into the installed app's own `bin` directory when enabled;
- creates Start Menu shortcuts;
- runs `post_install`;
- waits before closing when configured.

Installer runtime flags:

- `--yes`
  - bypass questions and the final close wait.
- `--no-wait`
  - skip only the final close wait.

When `installer.pause_on_exit` is true and no bypass flag is supplied, the console closes after 30 seconds or when the user presses Enter. Other keys are ignored.

## 10. Uninstall Runtime

The installed Start Menu uninstall shortcut points to:

```text
<install-root>\bin\uninstall.cmd
```

That cmd file launches:

```text
<install-root>\bin\uninstall.ps1
```

The PowerShell uninstaller infers the install root from its own location:

```powershell
$InstallDir = Split-Path -Parent $PSScriptRoot
```

This is deliberate. Moving an installed app directory should move its uninstall authority with it, and a manifest path mismatch must not delete a different directory.

Uninstall flow:

- confirm the action unless a bypass flag is supplied;
- run `pre_uninstall` while the app directory is still present;
- remove Start Menu entries;
- stage allowed `post_uninstall` entrypoints to temp;
- remove the install directory;
- run `post_uninstall` from the temp staging directory;
- preserve temp diagnostics if post-uninstall cleanup fails.

If a `post_uninstall` entrypoint points inside the install directory, it must be a self-contained `.cmd`, `.ps1`, or `.exe`. app-builder stages only `argv[0]` to temp before removal.

## 11. Icons

`installer.icon` is the single icon setting. app-builder uses it for generated executables and as the default Start Menu shortcut icon when a shortcut does not specify its own icon.

For app-builder's dogfood build, the same icon is embedded into the generated payload `app-builder.exe`.

## 12. Release Artifacts

A local release produces:

- the inner payload archive, `.zip` or `.7z`;
- the installer executable, `<slug>-<version>-installer.exe`;
- the manifest JSON, `<slug>-<version>-manifest.json`.

`release-gh` uploads exactly those same artifacts through GitHub CLI. If the release tag already exists, app-builder uploads assets with `--clobber`. If the tag does not exist, app-builder creates it with the version as tag and title.

GitHub CLI requirements:

```text
winget install --id GitHub.cli
gh auth login
```

app-builder searches PATH, `where.exe`, Program Files, LocalAppData, WinGet, Chocolatey, Scoop, and package-local candidates before reporting that `gh.exe` is missing.
