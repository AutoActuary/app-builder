# app-builder

`app-builder` packages Windows-first applications from `app_builder.yaml`. It prepares configured Python runtimes, runs explicit hooks, builds a payload archive, creates an installer, writes an uninstaller, and can publish the resulting artifacts with GitHub CLI.

Full user help is available in [docs/app-builder-help.html](docs/app-builder-help.html). `app-builder --help` prints a link to that same file.

## Quick Start

Install app-builder while developing:

```text
python -m pip install -e .
```

Create starter config inside a git repository:

```text
app-builder init
```

Edit `app_builder.yaml`. A Python project must declare dependencies in
`pyproject.toml` and run `app-builder lock` before its first build. A project
that does not ship Python should set both `python_bundled` and `python_venv` to
`null`.

Then build a local installer:

```text
app-builder release --version 0.1.0
```

Build and publish the configured release files to GitHub Releases:

```text
app-builder release-gh --version 0.1.0 --draft
```

Local releases also create a SHA-256 checksum file and generated release notes.
Named `outputs` can collect hook-generated files under `installer.dist`, and
`publications.github.outputs` selects exactly which built-in and named outputs
are uploaded.
They print timed build stages immediately and keep a detailed diagnostic log
under the configured dist directory's `build-logs` folder.
Before GitHub publication, app-builder requires a clean Git worktree outside
the configured dist directory, validates the artifact set and checksums, verifies
version and tag identity, checks `gh auth status`, and targets the exact audited
HEAD commit.

## Commands

```text
app-builder --help
app-builder --version
app-builder init [--force]
app-builder python
app-builder deps
app-builder lock
app-builder versions list
app-builder versions remove <ref>
app-builder release [--version <version>] [--verbose]
app-builder release-gh [--version <version>] [--draft | --no-draft] [--verbose]
app-builder 0.x <legacy-command>
```

## Documentation

- [docs/app-builder-help.html](docs/app-builder-help.html): practical user guide.
- [docs/configuration.md](docs/configuration.md): generated config reference.
- [docs/release-pipeline.md](docs/release-pipeline.md): detailed release lifecycle and installer behavior.
- [app_builder/assets/app_builder_template.yaml](app_builder/assets/app_builder_template.yaml): the config template used by `app-builder init`.

README is intentionally short. The release pipeline document exists separately because it is the lifecycle reference; it answers "what happens during a build/install/release?" without making the front page carry every implementation detail.

## Config Notes

`app_builder.yaml` is strict: unknown keys are rejected, old `application.yaml` shapes are rejected, and hooks are argv lists.

Normal builds verify an existing `poetry.lock` and install locked registry
artifacts by SHA-256. They never rewrite the lock. Run `app-builder lock`
deliberately when dependencies change. Complete Windows Python runtimes come
from Python.org and are verified against its published SHA-256. Stable versions
use exact `major.minor.patch` pins; prereleases also accept selectors such as
`3.15.0-beta`. Mutable Poetry `file` and `directory` dependencies are rejected
for releases; use a hashed index artifact or a Git source pinned to a full
resolved commit.

Use `%LOCALAPPDATA%`, `%APPDATA%`, or `%USERPROFILE%` as the root for install
paths that must resolve on the end user's machine. Other variable-root install
paths are rejected by release preflight:

```yaml
installer:
  name: "MyApp ${APP.VERSION}"
  install_directory: '%LOCALAPPDATA%\Acme\${CONFIG.installer.name}'
```

`${ENV.*}` is build-time interpolation. Use it only when you intentionally want the builder or CI environment baked into the config.

Configured Python environments are created inside the project but are not added
to the payload implicitly. Include `python_bundled.path`, normally `bin/python`,
under `installer.paths.include` when the installed application needs that runtime.
Installer `.py` hooks use those configured payload paths rather than fixed runtime
directory names.

`installer.dist` is excluded from the installed payload by default, including
when a broad include selects it. Named output pickup is cleared before
`post_dist`, and the payload and manifest are sealed once embedded into the
installer.

## Installer Flags

Generated install and uninstall scripts accept two runtime flags:

- `--yes`: bypass confirmation questions and skip the final close wait.
- `--no-wait`: skip only the final close wait.

Without those flags, the scripts ask before mutating the target directory. When `installer.wait_on_exit` is true, the console closes after 30 seconds or when the user presses Enter.

## Testing

Run tests against the `test` directory explicitly. A bare `python -m pytest` can wander into bundled compatibility dependencies.

```text
python -m pytest test -q
python -m mypy app_builder app_builder_meta test
```
