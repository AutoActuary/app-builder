# app-builder

`app-builder` is the 1.x rewrite of the old AutoActuary packaging tool: schema-first, Python-focused, and much less willing to hide build behavior in legacy magic.

## Current direction

- `app_builder.yaml` is the source of truth.
- `app_builder_version` is accepted as metadata but is ignored for now; the CLI always runs the installed/current module.
- The config model lives in code as plain dataclasses and can be loaded without `pydantic`.
- Optional `pydantic` adapters exist for richer schema tooling when that dependency is present.
- The release flow is explicit: build hooks, optional NuGet-sourced Python, optional Autory-style venv, payload packaging, ExeWrap-backed installer exe creation, and optional GitHub release upload.
- Python dependencies are declared in `pyproject.toml` and resolved by Poetry; `app_builder.yaml` no longer carries pip requirement lists.
- `python_venv` can stand alone: when `python_bundled` is disabled, app-builder materializes a self-contained NuGet Python under `venv/python` and ExeWrap-backed `venv/Scripts/python.exe` shims.
- Release builds now emit a first-layer ExeWrap installer `.exe` with a stored ZIP payload appended after the ExeWrap config end marker. The bootstrap command uses PowerShell to extract itself with `tar.exe` into a random temp directory, run `install.cmd`, and clean up in `finally`.

## Commands

```text
app-builder init
app-builder python
app-builder deps
app-builder release [--version <version>]
app-builder release-gh [--version <version>] [--draft]
```

## Template

Run `app-builder init` inside a git repository to generate:

- `app_builder.yaml`
- `application-templates/asciibanner.txt`
- `application-templates/icon.ico`
- `application-templates/program.cmd`

The generated YAML file is intentionally heavily commented and is meant to double as real config, template, and documentation base.
It is rendered from the same dataclass metadata as the [configuration reference](docs/configuration.md), and the packaged YAML snapshot is tested for drift.

## Testing

```text
python -m unittest discover -s test -v
mypy --config-file mypy.ini
```
