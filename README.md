# app-builder

`app-builder` is the 1.x rewrite of the old AutoActuary packaging tool: schema-first, Python-focused, and much less willing to hide build behavior in legacy magic.

## Current direction

- `app_builder.yaml` is the source of truth.
- `app_builder_version` is accepted as metadata but is ignored for now; the CLI always runs the installed/current module.
- The config model lives in code as plain dataclasses and can be loaded without `pydantic`.
- Optional `pydantic` adapters exist for richer schema tooling when that dependency is present.
- The release flow is explicit: build hooks, optional downloaded WinPython, optional Autory-style venv, payload packaging, installer bundle creation, and optional GitHub release upload.

## Commands

```text
app-builder init
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

## Testing

```text
python -m unittest discover -s test -v
mypy --config-file mypy.ini
```
