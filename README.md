# app-builder

`app-builder` packages Windows-first applications from `app_builder.yaml`. It prepares configured Python runtimes, runs explicit hooks, builds a payload archive, creates an installer, writes an uninstaller, and can publish the resulting artifacts with GitHub CLI.

Full user help is available in [app-builder-help.html](app_builder/assets/app-builder-help.html). The same link is printed at the top of `app-builder --help`.

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

## Documentation

- [app-builder-help.html](app_builder/assets/app-builder-help.html): practical user guide.
- [docs/configuration.md](docs/configuration.md): generated config reference.
- [docs/release-pipeline.md](docs/release-pipeline.md): detailed release lifecycle and installer behavior.
- [app_builder/assets/app_builder_template.yaml](app_builder/assets/app_builder_template.yaml): the config template used by `app-builder init`.

README is intentionally short. The release pipeline document exists separately because it is the lifecycle reference; it answers “what happens during a build/install/release?” without making the front page carry every implementation detail.

## Config Notes

`app_builder.yaml` is strict: unknown keys are rejected, old `application.yaml` shapes are rejected, and hooks are argv lists.

Use `%localappdata%`, `%appdata%`, and other percent-style Windows variables for install paths that must resolve on the end user's machine:

```yaml
installer:
  name: "MyApp ${APP.VERSION}"
  install_directory: '%localappdata%\Acme\${CONFIG.installer.name}'
```

`${ENV.*}` is build-time interpolation. Use it only when you intentionally want the builder or CI environment baked into the config.

## Installer Flags

Generated install and uninstall scripts accept two runtime flags:

- `--yes`: bypass confirmation questions and skip the final close wait.
- `--no-wait`: skip only the final close wait.

Without those flags, the scripts ask before mutating the target directory. When `installer.pause_on_exit` is true, the console closes after 30 seconds or when the user presses Enter.

## Testing

Run tests against the `test` directory explicitly. A bare `python -m pytest` can wander into bundled compatibility dependencies.

```text
python -m pytest test -q
python -m mypy --config-file mypy.ini
```
