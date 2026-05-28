# app_builder.yaml Configuration Reference

Generated from `app_builder.schema` metadata. `app-builder init` renders its example YAML from the same source.

Required fields can appear in examples without defaults. That means users must provide project-specific values; the loader still rejects missing required values, unknown keys, unsupported shapes, and explicit `null` where a field is not nullable.

## Complete app_builder.yaml Template

This is the full generated template. Required fields contain example values that you must replace for your app. Optional fields show their defaults or empty lists.

```yaml
# app_builder.yaml
# Generated from app_builder.schema metadata.
# Required and common optional fields contain examples; replace them for your app.
# String values can reference ${ENV.NAME}, ${GIT.DESCRIBE}, ${GIT.COMMIT},
# ${GIT.SHORT_COMMIT}, ${GIT.BRANCH}, ${GIT.TAG}, ${GIT.IS_DIRTY},
# ${APP.VERSION}, and ${CONFIG.path.to.value}.
# Interpolation is string-only and runs before schema validation.
# Keep app_builder_version literal; the version dispatcher reads it before
# the full 1.x config interpolation layer is loaded.
# Optional, nullable string | null. Version selector read by the meta CLI before loading
# the full config. Use current for the installed 1.x app-builder; explicit 1.x tags,
# branches, or commits are resolved through the managed version cache. Use the command
# line form app-builder 0.x for legacy 0.x projects. Default if omitted: current.
app_builder_version: current

# Optional, nullable mapping | null. Optional bundled Python runtime. Set to null to
# disable. Default if omitted: PythonBundledOptions defaults.
python_bundled:
  # Optional string. Project-relative directory where the bundled Python runtime is
  # materialized. Default if omitted: bin/python.
  path: bin/python

  # Optional string. NuGet Python package version or version prefix to materialize.
  # Default if omitted: 3.11.1.
  python_version: 3.12.10

# Optional, nullable mapping | null. Optional Poetry dev virtual environment derived from
# bundled Python when available. Set to null to disable. Default if omitted:
# PythonVenvOptions defaults.
python_venv:
  # Optional string. Project-relative directory where the Poetry dev virtual environment
  # is created. Default if omitted: venv.
  path: venv

  # Optional string. NuGet Python package version or version prefix used when the virtual
  # environment is self-contained because python_bundled is disabled. Default if omitted:
  # 3.11.1.
  python_version: 3.12.10

# Required mapping. Required installer metadata and release payload settings.
installer:
  # Required string. Human-facing application name.
  name: MyApp

  # Required string. Windows install directory. Use percent-style environment variables
  # such as %localappdata% when the path must resolve on the user's machine; generated
  # installer scripts expand them at install time.
  install_directory: '%localappdata%\MyCompany\MyApp'

  # Optional string. Project-relative .ico file used for generated executables and Start
  # Menu shortcuts when a shortcut does not specify its own icon. Default if omitted:
  # application-templates/icon.ico.
  icon: application-templates/icon.ico

  # Optional string. Inner payload archive format. Use zip for the Windows tar.exe path or
  # 7z for stronger compression with bundled 7-Zip extraction. Default if omitted: zip.
  payload_format: zip

  # Optional boolean. Whether generated installer scripts should wait briefly before
  # exiting. The wait closes after 30 seconds or Enter; --yes skips prompts and the wait,
  # while --no-wait skips only the wait. Default if omitted: true.
  pause_on_exit: true

  # Optional boolean. Whether the installer bundle should include an uninstall script.
  # Default if omitted: true.
  add_uninstaller: true

  # Optional list[mapping]. Windows Start Menu shortcut declarations. Default if omitted:
  # [].
  start_menu:
    - target: application-templates/program.cmd
      display_name: MyApp
      icon: application-templates/icon.ico

  # Optional mapping. Early installer hook command declarations. Default if omitted:
  # BootstrapHooks defaults.
  bootstrap_hooks:
    # Optional list[list[string]]. Argv commands run before the installer extracts its top
    # layer. These commands cannot use payload files, installer scripts, or bundled top-
    # layer tools because none have been extracted yet. Default if omitted: [].
    pre_extract: []

  # Optional mapping. Installer and uninstaller hook command declarations. Default if
  # omitted: InstallHooks defaults.
  install_hooks:
    # Optional list[list[string]]. Argv commands written into installer metadata to run
    # before installation. Default if omitted: [].
    pre_install: []

    # Optional list[list[string]]. Argv commands written into installer metadata to run
    # after installation. Default if omitted: [].
    post_install: []

    # Optional list[list[string]]. Argv commands written into installer metadata to run
    # before uninstall while the installed app directory is still present. Default if
    # omitted: [].
    pre_uninstall: []

    # Optional list[list[string]]. Argv commands written into installer metadata to run
    # after the install directory has been removed. Entrypoints inside the install
    # directory must be self-contained .cmd, .ps1, or .exe files because app-builder
    # stages only argv[0] to temp before removal. Default if omitted: [].
    post_uninstall: []

  # Optional string. Project-relative output directory for release artifacts. Default if
  # omitted: dist.
  dist: dist

  # Optional mapping. Payload include, exclude, and remap rules. Default if omitted:
  # PathsMapping defaults.
  paths:
    # Optional list[string]. Project-relative files or globs included in the release
    # payload. Default if omitted: [].
    include:
      - src
      - app_builder.yaml
      - application-templates

    # Optional list[string]. Project-relative files or globs excluded from the release
    # payload. Default if omitted: [].
    exclude:
      - '**/__pycache__'
      - dist
      - venv

    # Optional list[tuple[string, string]]. Two-item source and destination pairs for
    # relocating payload files. Default if omitted: [].
    remap:
      - [README.md, docs/README.md]

# Optional mapping. Build and release hook command declarations. Default if omitted:
# BuildHooks defaults.
build_hooks:
  # Optional list[list[string]]. Argv commands run before dependency or release processing
  # begins. Default if omitted: [].
  pre_process: []

  # Optional list[list[string]]. Argv commands run before bundled Python is materialized.
  # Default if omitted: [].
  pre_python_bundled: []

  # Optional list[list[string]]. Argv commands run after bundled Python is materialized.
  # Default if omitted: [].
  post_python_bundled: []

  # Optional list[list[string]]. Argv commands run before the virtual environment is
  # materialized. Default if omitted: [].
  pre_python_venv: []

  # Optional list[list[string]]. Argv commands run after the virtual environment is
  # materialized. Default if omitted: [].
  post_python_venv: []

  # Optional list[list[string]]. Argv commands run before the release payload is
  # assembled. Default if omitted: [].
  pre_dist: []

  # Optional list[list[string]]. Argv commands run after the release payload is assembled.
  # Default if omitted: [].
  post_dist: []

  # Optional list[list[string]]. Argv commands run before GitHub release upload. Default
  # if omitted: [].
  pre_github_release: []

  # Optional list[list[string]]. Argv commands run after GitHub release upload. Default if
  # omitted: [].
  post_github_release: []

  # Optional list[list[string]]. Argv commands run at the end of release processing.
  # Default if omitted: [].
  post_process: []
```

String values are interpolated before schema validation. Supported variables are `${ENV.NAME}`, `${GIT.DESCRIBE}`, `${GIT.COMMIT}`, `${GIT.SHORT_COMMIT}`, `${GIT.BRANCH}`, `${GIT.TAG}`, `${GIT.IS_DIRTY}`, `${APP.VERSION}`, and `${CONFIG.path.to.value}`. Interpolation is string-only; references to lists or mappings are rejected.

## String Interpolation

Use `${...}` inside YAML string values when a config value should be derived from the environment, git, the app-builder release version, or another config string. Interpolation happens after YAML parsing and before dataclass schema validation, so the final expanded value is what the schema sees.

| Variable | Value | Notes |
| --- | --- | --- |
| `${ENV.NAME}` | Environment variable from the running process. | Lookup is case-insensitive as a Windows convenience. Missing variables fail the config load. |
| `${GIT.DESCRIBE}` | `git describe --tags --always --dirty`, with the same fallback as app-builder's version detection. | Good for version-from-tag config values. |
| `${GIT.COMMIT}` | Full current commit hash. | Fails if git cannot read the repository. |
| `${GIT.SHORT_COMMIT}` | Short current commit hash. | Fails if git cannot read the repository. |
| `${GIT.BRANCH}` | Current branch name. | Empty string when HEAD is detached or no branch is available. |
| `${GIT.TAG}` | Exact tag at HEAD. | Empty string when HEAD is not exactly on a tag. |
| `${GIT.IS_DIRTY}` | `true` when `git status --porcelain` has output, otherwise `false`. | Fails if git cannot read the repository. |
| `${APP.VERSION}` | The app-builder release version. | Honors `--version`; otherwise uses app-builder's git-based version detection. |
| `${CONFIG.path.to.value}` | Another resolved string value in the same config. | Resolves recursively. Circular references, missing paths, and references to non-string values fail. List indexes are allowed in the path, but the final target must be a string. |

`app_builder_version` is the exception to the usual interpolation surface. The command dispatcher reads that selector from plain YAML before importing the full 1.x app-builder package, so keep it literal (`current`, a branch, a tag, or a commit).

For Windows paths, single-quoted YAML strings are usually easiest because backslashes stay literal. If you use double-quoted YAML strings for Windows paths, write backslashes as `\\`.

Use percent-style Windows variables such as `%localappdata%` for install paths that must resolve on the user's machine. `${ENV.*}` is resolved while building the release, so it bakes in the builder or CI environment.

Example:

```yaml
installer:
  name: "MyApp ${APP.VERSION}"
  install_directory: '%localappdata%\Acme\${CONFIG.installer.name}'
  paths:
    include:
      - "build/${APP.VERSION}"
    remap:
      - [README.md, "docs/${CONFIG.installer.name}.md"]
```

## Top-Level Config

| Field | Type | Required | Default | Example | Description |
| --- | --- | --- | --- | --- | --- |
| `app_builder_version` | `string \| null` | no | `current` | `current` | Version selector read by the meta CLI before loading the full config. Use current for the installed 1.x app-builder; explicit 1.x tags, branches, or commits are resolved through the managed version cache. Use the command line form app-builder 0.x for legacy 0.x projects. |
| `python_bundled` | `mapping \| null` | no | `see nested defaults` |  | Optional bundled Python runtime. Set to null to disable. |
| `python_venv` | `mapping \| null` | no | `see nested defaults` |  | Optional Poetry dev virtual environment derived from bundled Python when available. Set to null to disable. |
| `installer` | `mapping` | yes | required |  | Required installer metadata and release payload settings. |
| `build_hooks` | `mapping` | no | `see nested defaults` |  | Build and release hook command declarations. |

## `config.python_bundled`

| Field | Type | Required | Default | Example | Description |
| --- | --- | --- | --- | --- | --- |
| `path` | `string` | no | `bin/python` | `bin/python` | Project-relative directory where the bundled Python runtime is materialized. |
| `python_version` | `string` | no | `3.11.1` | `3.12.10` | NuGet Python package version or version prefix to materialize. |

## `config.python_venv`

| Field | Type | Required | Default | Example | Description |
| --- | --- | --- | --- | --- | --- |
| `path` | `string` | no | `venv` | `venv` | Project-relative directory where the Poetry dev virtual environment is created. |
| `python_version` | `string` | no | `3.11.1` | `3.12.10` | NuGet Python package version or version prefix used when the virtual environment is self-contained because python_bundled is disabled. |

## `config.installer`

| Field | Type | Required | Default | Example | Description |
| --- | --- | --- | --- | --- | --- |
| `name` | `string` | yes | required | `MyApp` | Human-facing application name. |
| `install_directory` | `string` | yes | required | `'%localappdata%\MyCompany\MyApp'` | Windows install directory. Use percent-style environment variables such as %localappdata% when the path must resolve on the user's machine; generated installer scripts expand them at install time. |
| `icon` | `string` | no | `application-templates/icon.ico` | `application-templates/icon.ico` | Project-relative .ico file used for generated executables and Start Menu shortcuts when a shortcut does not specify its own icon. |
| `payload_format` | `string` | no | `zip` | `zip` | Inner payload archive format. Use zip for the Windows tar.exe path or 7z for stronger compression with bundled 7-Zip extraction. |
| `pause_on_exit` | `boolean` | no | `true` | `true` | Whether generated installer scripts should wait briefly before exiting. The wait closes after 30 seconds or Enter; --yes skips prompts and the wait, while --no-wait skips only the wait. |
| `add_uninstaller` | `boolean` | no | `true` | `true` | Whether the installer bundle should include an uninstall script. |
| `start_menu` | `list[mapping]` | no | `[]` | `[{target: application-templates/program.cmd, display_name: MyApp, icon: application-templates/icon.ico}]` | Windows Start Menu shortcut declarations. |
| `bootstrap_hooks` | `mapping` | no | `see nested defaults` |  | Early installer hook command declarations. |
| `install_hooks` | `mapping` | no | `see nested defaults` |  | Installer and uninstaller hook command declarations. |
| `dist` | `string` | no | `dist` | `dist` | Project-relative output directory for release artifacts. |
| `paths` | `mapping` | no | `see nested defaults` |  | Payload include, exclude, and remap rules. |

## `config.installer.start_menu[]`

| Field | Type | Required | Default | Example | Description |
| --- | --- | --- | --- | --- | --- |
| `target` | `string` | yes | required | `application-templates/program.cmd` | Project-relative command or file launched by the shortcut. |
| `display_name` | `string \| null` | no | `null` | `MyApp` | Shortcut display name. Defaults to the installer name when omitted by downstream tooling. |
| `icon` | `string \| null` | no | `null` | `application-templates/icon.ico` | Project-relative icon path for the shortcut. |

## `config.installer.bootstrap_hooks`

| Field | Type | Required | Default | Example | Description |
| --- | --- | --- | --- | --- | --- |
| `pre_extract` | `list[list[string]]` | no | `[]` |  | Argv commands run before the installer extracts its top layer. These commands cannot use payload files, installer scripts, or bundled top-layer tools because none have been extracted yet. |

## `config.installer.install_hooks`

| Field | Type | Required | Default | Example | Description |
| --- | --- | --- | --- | --- | --- |
| `pre_install` | `list[list[string]]` | no | `[]` |  | Argv commands written into installer metadata to run before installation. |
| `post_install` | `list[list[string]]` | no | `[]` |  | Argv commands written into installer metadata to run after installation. |
| `pre_uninstall` | `list[list[string]]` | no | `[]` |  | Argv commands written into installer metadata to run before uninstall while the installed app directory is still present. |
| `post_uninstall` | `list[list[string]]` | no | `[]` |  | Argv commands written into installer metadata to run after the install directory has been removed. Entrypoints inside the install directory must be self-contained .cmd, .ps1, or .exe files because app-builder stages only argv[0] to temp before removal. |

## `config.installer.paths`

| Field | Type | Required | Default | Example | Description |
| --- | --- | --- | --- | --- | --- |
| `include` | `list[string]` | no | `[]` | `[src, app_builder.yaml, application-templates]` | Project-relative files or globs included in the release payload. |
| `exclude` | `list[string]` | no | `[]` | `['**/__pycache__', dist, venv]` | Project-relative files or globs excluded from the release payload. |
| `remap` | `list[tuple[string, string]]` | no | `[]` | `[[README.md, docs/README.md]]` | Two-item source and destination pairs for relocating payload files. |

## `config.build_hooks`

| Field | Type | Required | Default | Example | Description |
| --- | --- | --- | --- | --- | --- |
| `pre_process` | `list[list[string]]` | no | `[]` |  | Argv commands run before dependency or release processing begins. |
| `pre_python_bundled` | `list[list[string]]` | no | `[]` |  | Argv commands run before bundled Python is materialized. |
| `post_python_bundled` | `list[list[string]]` | no | `[]` |  | Argv commands run after bundled Python is materialized. |
| `pre_python_venv` | `list[list[string]]` | no | `[]` |  | Argv commands run before the virtual environment is materialized. |
| `post_python_venv` | `list[list[string]]` | no | `[]` |  | Argv commands run after the virtual environment is materialized. |
| `pre_dist` | `list[list[string]]` | no | `[]` |  | Argv commands run before the release payload is assembled. |
| `post_dist` | `list[list[string]]` | no | `[]` |  | Argv commands run after the release payload is assembled. |
| `pre_github_release` | `list[list[string]]` | no | `[]` |  | Argv commands run before GitHub release upload. |
| `post_github_release` | `list[list[string]]` | no | `[]` |  | Argv commands run after GitHub release upload. |
| `post_process` | `list[list[string]]` | no | `[]` |  | Argv commands run at the end of release processing. |

## Command Values

Hook fields are `list[list[string]]`. Each command is an argv list. Use an explicit shell argv, such as `[cmd, /c, ...]`, when shell behavior is required.

When a hook command's `argv[0]` is a `.py` file, app-builder runs it with the Python runtime configured for the project, preferring `python_venv` and then `python_bundled`. That means a hook such as `[scripts/build.py]` does not need `python.exe` on PATH. Use an explicit argv such as `[python, script.py]` only when the target machine is expected to provide Python.
