# app-builder

`app-builder` is the 1.x rewrite of the old AutoActuary packaging tool: schema-first, Python-focused, and much less willing to hide build behavior in legacy magic.

## Current direction

- `app_builder.yaml` is the source of truth.
- `app_builder_version` is read by a tiny meta CLI before the full app-builder package is imported. Missing, blank, or `current` runs the installed 1.x module; explicit 1.x refs are resolved through the managed version cache.
- Legacy 0.x usage is explicit: run `app-builder 0.x <command>`. A legacy `application.yaml` produces repair instructions instead of silently dispatching old code.
- The config model lives in code as plain dataclasses and can be loaded without `pydantic`.
- Optional `pydantic` adapters exist for richer schema tooling when that dependency is present.
- The release flow is explicit: build hooks, optional NuGet-sourced Python, optional Autory-style venv, payload packaging, ExeWrap-backed installer exe creation, and optional GitHub release upload.
- Python dependencies are declared in `pyproject.toml` and resolved by Poetry; `app_builder.yaml` no longer carries pip requirement lists.
- `python_venv` can stand alone: when `python_bundled` is disabled, app-builder materializes a self-contained NuGet Python under `venv/python` and ExeWrap-backed `venv/Scripts/python.exe` shims.
- Automatic `.py` hook dispatch uses only project-owned Python from `python_bundled` or `python_venv`; app-builder does not assume system Python exists on the developer or user machine. Use an explicit argv such as `[python, script.py]` only when that assumption is intentional.
- Release builds now emit a first-layer ExeWrap installer `.exe` with a stored ZIP payload appended after the ExeWrap config end marker. The vendored launcher carries an `asInvoker` manifest so Windows does not apply filename-based installer elevation heuristics. The bootstrap command uses PowerShell to extract itself with `tar.exe` into a random temp directory, run `install.cmd`, and clean up in `finally`; the generated installer then installs the payload into the configured install directory and writes an uninstall path when enabled.
- `installer.icon` is the single icon field: app-builder embeds it into generated ExeWrap `.exe` files and also uses it as the default Start Menu shortcut icon.
- First-class `bin/...` runtime/tool features are retired except for Python. Use explicit hooks for project-specific tools or setup outside the Python runtime path.
- `release-gh` uses GitHub CLI (`gh.exe`) for GitHub Releases. app-builder searches PATH, `where.exe` results, and common GitHub CLI install locations; if it still cannot find `gh.exe`, install it with `winget install --id GitHub.cli` and authenticate with `gh auth login`.
- Config string values support `${...}` interpolation before schema validation. Supported namespaces are `ENV.*`, `GIT.*`, `APP.VERSION`, and `CONFIG.*`; interpolation is string-only and fails loudly for missing values, circular `CONFIG.*` references, or references to lists and mappings.

## Commands

Install the module in editable form while developing:

```text
python -m pip install -e .
```

```text
app-builder init
app-builder python
app-builder deps
app-builder release [--version <version>]
app-builder release-gh [--version <version>] [--draft]
app-builder 0.x <legacy-command>
```

## Template

Run `app-builder init` inside a git repository to generate:

- `app_builder.yaml`
- `application-templates/icon.ico`
- `application-templates/program.cmd`

The generated YAML file is intentionally heavily commented and is meant to double as real config, template, and documentation base.
It is rendered from the same dataclass metadata as the [configuration reference](docs/configuration.md), and the packaged YAML snapshot is tested for drift.

## Config interpolation

Use `${...}` inside YAML strings when config should be derived from the environment, git, the active release version, or another config string:

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

Available values are `ENV.NAME`, `GIT.DESCRIBE`, `GIT.COMMIT`, `GIT.SHORT_COMMIT`, `GIT.BRANCH`, `GIT.TAG`, `GIT.IS_DIRTY`, `APP.VERSION`, and `CONFIG.path.to.value`.

`APP.VERSION` follows the release command's `--version` when supplied, otherwise it uses app-builder's git-based version detection. `CONFIG.*` resolves recursively, but the final target must be a string. Keep `app_builder_version` literal because the version dispatcher reads it from plain YAML before the full interpolation layer is loaded. For Windows paths, single-quoted YAML strings keep backslashes literal; double-quoted YAML strings need `\\`.

## Testing

```text
python -m unittest discover -s test -v
mypy --config-file mypy.ini
```
