# app-builder

`app-builder` is the 1.x rewrite of the old AutoActuary packaging tool. It is a schema-first, Windows-focused builder for Python apps and mixed projects that want explicit build hooks instead of legacy hidden behavior.

## What It Does

- Reads `app_builder.yaml` as the project contract.
- Materializes project-owned Python with NuGet and Poetry when configured.
- Runs explicit build hooks before and after dependency, dist, and GitHub release steps.
- Collects payload files with include, exclude, and remap rules.
- Builds a payload archive as either ZIP or 7z.
- Builds an ExeWrap installer `.exe` with a stored ZIP outer layer.
- Installs the payload, handles recognized upgrades, creates Start Menu shortcuts, and writes an installed uninstaller.
- Publishes local artifacts to GitHub Releases through GitHub CLI (`gh.exe`) when requested.

The 1.x line is intentionally Python-focused. First-class `bin/...` runtime/tool features from 0.x are retired except for Python. Non-Python tools still fit through explicit hooks such as `[cmd.exe, /D, /C, ...]`, `[powershell.exe, ...]`, or a project-owned executable.

## Quick Start

Install app-builder while developing:

```text
python -m pip install -e .
```

Create starter config inside a git repository:

```text
app-builder init
```

Edit `app_builder.yaml`, then build a local installer:

```text
app-builder release --version 0.1.0
```

Publish the same artifacts to GitHub Releases:

```text
app-builder release-gh --version 0.1.0 --draft
```

If `--version` is omitted, app-builder uses git-based version detection and falls back to `0.0.0-dev`.

## Commands

```text
app-builder --help
app-builder init [--force]
app-builder python
app-builder deps
app-builder release [--version <version>]
app-builder release-gh [--version <version>] [--draft | --no-draft]
app-builder 0.x <legacy-command>
```

- `--help` and `init` work even when no project config exists.
- `python` materializes only the configured bundled Python runtime.
- `deps` materializes configured Python environments without building release artifacts.
- `release` writes the payload archive, installer executable, and manifest JSON to `installer.dist`.
- `release-gh` builds the same local artifact set, then uses `gh.exe` to create or update a GitHub Release.
- `0.x` explicitly enters the legacy compatibility bridge when it is installed. A legacy `application.yaml` is not auto-dispatched.

## Config

`app_builder.yaml` is strict. Unknown keys are rejected, legacy `application.yaml` shapes are rejected, and hook commands must be argv lists.

The generated template comes from the same schema metadata as [docs/configuration.md](docs/configuration.md):

```text
app-builder init
```

That creates:

- `app_builder.yaml`
- `application-templates/icon.ico`
- `application-templates/program.cmd`

## Config Interpolation

String values support `${...}` interpolation before schema validation. Supported namespaces are:

- `${ENV.NAME}`
- `${GIT.DESCRIBE}`
- `${GIT.COMMIT}`
- `${GIT.SHORT_COMMIT}`
- `${GIT.BRANCH}`
- `${GIT.TAG}`
- `${GIT.IS_DIRTY}`
- `${APP.VERSION}`
- `${CONFIG.path.to.value}`

Interpolation is string-only. Missing values, circular `CONFIG.*` references, and references to lists or mappings fail loudly.

```yaml
app_builder_version: current
installer:
  name: "MyApp ${APP.VERSION}"
  install_directory: '${ENV.LOCALAPPDATA}\Acme\${CONFIG.installer.name}'
  paths:
    include:
      - "build/${APP.VERSION}"
    remap:
      - [README.md, "docs/${CONFIG.installer.name}.md"]
```

Keep `app_builder_version` literal. The dispatcher reads it from plain YAML before the full interpolation layer is loaded.

## Python Runtime

Python dependencies live in `pyproject.toml` and are resolved by Poetry.

- `python_bundled` materializes NuGet Python under `bin/python` by default.
- `python_venv` creates a Poetry dev venv under `venv` by default.
- If `python_bundled` is disabled but `python_venv` is enabled, app-builder creates a self-contained NuGet-backed venv.
- Automatic `.py` hook dispatch uses only project-owned Python from `python_bundled` or `python_venv`. It does not assume system Python exists.

Use an explicit argv such as `[python, script.py]` only when the target machine is expected to provide Python.

## Installer

Release builds emit a first-layer ExeWrap installer `.exe` with a stored ZIP payload appended after the ExeWrap config end marker. The vendored ExeWrap 2.1.0 launcher is patched with an `asInvoker` Windows manifest so installer-like filenames do not trigger unwanted elevation heuristics.

The outer installer layer contains:

```text
install.cmd
bin/install.ps1
bin/uninstall.cmd       # when installer.add_uninstaller is true
bin/uninstall.ps1       # when installer.add_uninstaller is true
bin/7z.exe              # only when installer.payload_format: 7z
bin/7z.dll              # only when installer.payload_format: 7z
<app>-<version>.zip     # or .7z
```

ExeWrap runs a PowerShell bootstrap that:

1. runs `installer.bootstrap_hooks.pre_extract`;
2. extracts the outer layer with Windows `tar.exe` into a random `%TEMP%` directory;
3. decodes ExeWrap `@{args_as_json}` with PowerShell `ConvertFrom-Json`;
4. calls `bin\install.ps1` directly with those arguments;
5. removes the temp extraction directory in `finally`.

Manual fallback is still clean: rename the installer to `.zip`, extract it, and run `install.cmd`.

## Installer Runtime Flags

Generated install and uninstall scripts accept:

- `--yes`, `-yes`, `-y`, `/y`, `--non-interactive`, `-noninteractive`, `--no-prompt`, `-noprompt`
  - bypass confirmation questions and skip the final close wait.
- `--no-wait`, `-no-wait`, `-nowait`
  - skip only the final close wait.

Without bypass flags, the scripts ask before mutating the target directory. When `installer.pause_on_exit` is true, the console closes after 30 seconds or when the user presses Enter. Other keys do not close the window early.

## Payload Formats

`installer.payload_format` selects the inner payload archive:

- `zip` is the default and uses Windows `tar.exe` during installation.
- `7z` uses the vendored 7-Zip runtime, stages remapped files under their final archive names, handles files that Windows locks by copying them to temp first, suppresses routine 7z noise, and includes `bin/7z.exe` plus `bin/7z.dll` in the installer top layer.

The outer ExeWrap layer remains a stored ZIP in both modes.

## Hooks

Hook fields are `list[list[string]]`. Each command is an argv list.

- `installer.bootstrap_hooks.pre_extract` runs inside the ExeWrap PowerShell bootstrap before extraction. It cannot use payload files, installer scripts, or bundled top-layer tools because none have been extracted yet.
- `installer.install_hooks.pre_install` runs before installation.
- `installer.install_hooks.post_install` runs after installation.
- `installer.install_hooks.pre_uninstall` runs while the installed app is still present.
- `installer.install_hooks.post_uninstall` runs after the install directory has been removed. If an entrypoint lives inside the install directory, it must be a self-contained `.cmd`, `.ps1`, or `.exe`; app-builder stages only `argv[0]` to temp before deletion.

Build hooks run around dependency materialization, dist assembly, GitHub upload, and final processing. See [docs/configuration.md](docs/configuration.md) for the full list.

## GitHub Releases

`release-gh` delegates authentication and upload behavior to GitHub CLI. app-builder searches PATH, `where.exe`, and common GitHub CLI install locations. If `gh.exe` is missing:

```text
winget install --id GitHub.cli
gh auth login
```

The uploaded artifact set is exactly:

- the payload archive, `.zip` or `.7z`;
- the installer executable, `<name>-<version>-installer.exe`;
- the manifest JSON.

Existing releases are updated with `gh release upload --clobber`; new releases are created with the version as the tag and title.

## Legacy 0.x

Legacy use is explicit:

```text
app-builder 0.x <legacy-command>
```

A project with only `application.yaml` receives instructions instead of silently running old code. A new `app_builder.yaml` with `app_builder_version: 0.x` is an error.

## Testing

Run tests against the `test` directory explicitly. A bare `python -m pytest` can wander into the bundled 0.x bridge dependencies.

```text
python -m pytest test -q
python -m mypy --config-file mypy.ini
```

The template and configuration docs are snapshot-tested against the schema metadata.
