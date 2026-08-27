# app_builder.yaml Configuration Reference

Generated from `app_builder.schema` metadata. `app-builder init` renders its example YAML from the same source.

Required fields can appear in examples without defaults. That means users must provide project-specific values; the loader still rejects missing required values, unknown keys, unsupported shapes, and explicit `null` where a field is not nullable.

## Complete app_builder.yaml Template

This is the full generated template. Required fields contain example values that you must replace for your app. Optional fields show their defaults or empty lists. For an empty list of mappings, the adjacent comment lists every supported item field.

```yaml
# app_builder.yaml
# Generated from app_builder.schema metadata.
# Every supported config key is shown. Replace the starter values for your app.
# Empty lists are safe defaults; comments identify structured item fields.
# String values can reference ${ENV.NAME}, ${GIT.DESCRIBE}, ${GIT.COMMIT},
# ${GIT.SHORT_COMMIT}, ${GIT.BRANCH}, ${GIT.TAG}, ${GIT.IS_DIRTY},
# ${APP.VERSION}, and ${CONFIG.path.to.value}.
# Interpolation is string-only and runs before schema validation.
# Keep app_builder_version literal; app-builder reads it before config
# interpolation is available.
# Optional, nullable string | null. Literal version selector read by the app-builder
# launcher before config interpolation. Use current for the installed 1.x version;
# explicit 1.x tags, branches, or commits use the managed version cache. Use app-builder
# 0.x for legacy projects. Default if omitted: current.
app_builder_version: current

# Optional, nullable mapping | null. Optional bundled Python runtime. Set to null to
# disable. Default if omitted: PythonBundledOptions defaults.
python_bundled:
  # Optional string. Project-relative directory where the bundled Python runtime is
  # materialized. Default if omitted: bin/python.
  path: bin/python

  # Optional string. Python.org Windows runtime version to materialize. Use
  # major.minor.patch for a stable release; prereleases accept forms such as 3.15.0b4 or
  # 3.15.0-beta. Default if omitted: 3.11.1.
  python_version: 3.12.10

# Optional, nullable mapping | null. Optional Poetry dev virtual environment derived from
# bundled Python when available. Set to null to disable. Default if omitted:
# PythonVenvOptions defaults.
python_venv:
  # Optional string. Project-relative directory where the Poetry dev virtual environment
  # is created. Default if omitted: venv.
  path: venv

  # Optional string. Python.org Windows runtime version used when the virtual environment
  # is self-contained because python_bundled is disabled. Prerelease selectors are
  # supported. Default if omitted: 3.11.1.
  python_version: 3.12.10

# Required mapping. Required installer metadata and release payload settings.
installer:
  # Required string. Human-facing application name and Windows install identity. It must
  # be a trimmed, filename-safe, non-reserved Windows name.
  name: MyApp

  # Required string. Windows install directory. A variable-root path must start with
  # %LOCALAPPDATA%, %APPDATA%, or %USERPROFILE% and name an application subdirectory; the
  # installer expands it on the user's machine. Parent-directory traversal is rejected. A
  # fixed absolute path is also allowed when it is not a drive root or protected Windows
  # directory.
  install_directory: '%LOCALAPPDATA%\MyCompany\MyApp'

  # Optional, nullable string | null. Optional project-relative .ico file embedded into
  # generated executables. Start Menu shortcuts with no icon inherit it, and app-builder
  # includes it in the payload automatically at its normal or remapped destination.
  # Default if omitted: null.
  icon: application-templates/icon.ico

  # Optional string. Inner payload archive format. Use zip for the Windows tar.exe path or
  # 7z for stronger compression with bundled 7-Zip extraction. Default if omitted: zip.
  payload_format: zip

  # Optional boolean. Whether generated installer scripts should wait briefly before
  # exiting. The wait closes after 30 seconds or Enter; --yes skips prompts and the wait,
  # while --no-wait skips only the wait. Default if omitted: true.
  wait_on_exit: true

  # Optional boolean. Whether installation adds the installed uninstall scripts, Start
  # Menu uninstall shortcut, and per-user Windows Installed Apps registration. Default if
  # omitted: true.
  add_uninstaller: true

  # Optional list[mapping]. Windows Start Menu shortcut declarations. Default if omitted:
  # [].
  start_menu:
    - target: application-templates/program.cmd
      display_name: MyApp
      icon: null

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
    # after payload files, shortcuts, uninstall support, and Windows Installed Apps
    # registration are complete. Default if omitted: [].
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

  # Optional string. Project-relative subdirectory inside the project where release
  # artifacts and build logs are written. Default if omitted: dist.
  dist: dist

  # Optional mapping. Payload include, exclude, and remap rules. Default if omitted:
  # PathsMapping defaults.
  paths:
    # Optional list[string]. Required project-relative files or globs included in the
    # release payload. Every entry must match, and the final payload must be nonempty
    # after excludes. Default if omitted: [].
    include:
      - app_builder.yaml
      - application-templates
      - bin/python
      - README.md

    # Optional list[string]. Project-relative files or globs removed from the selected
    # payload. Default if omitted: [].
    exclude:
      - '**/__pycache__'
      - dist
      - venv

    # Optional boolean. Whether files beneath installer.dist may enter the application
    # payload. The default excludes dist even when a broad include selects the project
    # root, preventing old release files and build logs from being installed. Default if
    # omitted: false.
    include_dist: false

    # Optional list[tuple[string, string]]. Two-item source and archive-destination pairs.
    # Each source must be a selected literal project-relative path; destinations must be
    # safe, unique archive paths. Default if omitted: [].
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

  # Optional list[list[string]]. Argv commands run after installer assembly and stale
  # named-output candidates are cleared, but before output collection, checksums, and
  # release notes. This stage may create extra outputs or sign the installer; it must not
  # modify the sealed payload or manifest. Default if omitted: [].
  post_dist: []

  # Optional list[list[string]]. Argv commands run before GitHub release upload. Default
  # if omitted: [].
  pre_github_release: []

  # Optional list[list[string]]. Argv commands run after GitHub release upload. Default if
  # omitted: [].
  post_github_release: []

# Optional list[mapping]. Named release output collections produced by hooks or other
# project build steps and picked up from installer.dist. Default if omitted: [].
outputs: []
# Item fields: name, pattern, min_matches, max_matches.

# Optional mapping. Explicit publication output selections. Default if omitted:
# Publications defaults.
publications:
  # Optional mapping. GitHub release publication settings. Default if omitted:
  # GitHubPublication defaults.
  github:
    # Optional list[string]. Exact logical output names uploaded to the GitHub release. A
    # configured name expands to every matched file; unknown names and case-insensitive
    # upload filename collisions are rejected. Default if omitted: [payload, installer,
    # manifest, checksums].
    outputs:
      - payload
      - installer
      - manifest
      - checksums
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

`app_builder_version` is the exception to the usual interpolation surface. app-builder reads that selector from plain YAML before config interpolation is available, so keep it literal (`current`, a branch, a tag, or a commit).

For Windows paths, single-quoted YAML strings are usually easiest because backslashes stay literal. If you use double-quoted YAML strings for Windows paths, write backslashes as `\\`.

Use `%LOCALAPPDATA%`, `%APPDATA%`, or `%USERPROFILE%` for variable-root install paths that must resolve on the user's machine. `${ENV.*}` is resolved while building the release, so it bakes in the builder or CI environment.

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
| `app_builder_version` | `string \| null` | no | `current` | `current` | Literal version selector read by the app-builder launcher before config interpolation. Use current for the installed 1.x version; explicit 1.x tags, branches, or commits use the managed version cache. Use app-builder 0.x for legacy projects. |
| `python_bundled` | `mapping \| null` | no | `see nested defaults` |  | Optional bundled Python runtime. Set to null to disable. |
| `python_venv` | `mapping \| null` | no | `see nested defaults` |  | Optional Poetry dev virtual environment derived from bundled Python when available. Set to null to disable. |
| `installer` | `mapping` | yes | required |  | Required installer metadata and release payload settings. |
| `build_hooks` | `mapping` | no | `see nested defaults` |  | Build and release hook command declarations. |
| `outputs` | `list[mapping]` | no | `[]` |  | Named release output collections produced by hooks or other project build steps and picked up from installer.dist. |
| `publications` | `mapping` | no | `see nested defaults` |  | Explicit publication output selections. |

## `config.python_bundled`

| Field | Type | Required | Default | Example | Description |
| --- | --- | --- | --- | --- | --- |
| `path` | `string` | no | `bin/python` | `bin/python` | Project-relative directory where the bundled Python runtime is materialized. |
| `python_version` | `string` | no | `3.11.1` | `3.12.10` | Python.org Windows runtime version to materialize. Use major.minor.patch for a stable release; prereleases accept forms such as 3.15.0b4 or 3.15.0-beta. |

## `config.python_venv`

| Field | Type | Required | Default | Example | Description |
| --- | --- | --- | --- | --- | --- |
| `path` | `string` | no | `venv` | `venv` | Project-relative directory where the Poetry dev virtual environment is created. |
| `python_version` | `string` | no | `3.11.1` | `3.12.10` | Python.org Windows runtime version used when the virtual environment is self-contained because python_bundled is disabled. Prerelease selectors are supported. |

## `config.installer`

| Field | Type | Required | Default | Example | Description |
| --- | --- | --- | --- | --- | --- |
| `name` | `string` | yes | required | `MyApp` | Human-facing application name and Windows install identity. It must be a trimmed, filename-safe, non-reserved Windows name. |
| `install_directory` | `string` | yes | required | `'%LOCALAPPDATA%\MyCompany\MyApp'` | Windows install directory. A variable-root path must start with %LOCALAPPDATA%, %APPDATA%, or %USERPROFILE% and name an application subdirectory; the installer expands it on the user's machine. Parent-directory traversal is rejected. A fixed absolute path is also allowed when it is not a drive root or protected Windows directory. |
| `icon` | `string \| null` | no | `null` | `application-templates/icon.ico` | Optional project-relative .ico file embedded into generated executables. Start Menu shortcuts with no icon inherit it, and app-builder includes it in the payload automatically at its normal or remapped destination. |
| `payload_format` | `string` | no | `zip` | `zip` | Inner payload archive format. Use zip for the Windows tar.exe path or 7z for stronger compression with bundled 7-Zip extraction. |
| `wait_on_exit` | `boolean` | no | `true` | `true` | Whether generated installer scripts should wait briefly before exiting. The wait closes after 30 seconds or Enter; --yes skips prompts and the wait, while --no-wait skips only the wait. |
| `add_uninstaller` | `boolean` | no | `true` | `true` | Whether installation adds the installed uninstall scripts, Start Menu uninstall shortcut, and per-user Windows Installed Apps registration. |
| `start_menu` | `list[mapping]` | no | `[]` | `[{target: application-templates/program.cmd, display_name: MyApp, icon: null}]` | Windows Start Menu shortcut declarations. |
| `bootstrap_hooks` | `mapping` | no | `see nested defaults` |  | Early installer hook command declarations. |
| `install_hooks` | `mapping` | no | `see nested defaults` |  | Installer and uninstaller hook command declarations. |
| `dist` | `string` | no | `dist` | `dist` | Project-relative subdirectory inside the project where release artifacts and build logs are written. |
| `paths` | `mapping` | no | `see nested defaults` |  | Payload include, exclude, and remap rules. |

## `config.installer.start_menu[]`

| Field | Type | Required | Default | Example | Description |
| --- | --- | --- | --- | --- | --- |
| `target` | `string` | yes | required | `application-templates/program.cmd` | Install-relative command or file launched by the shortcut. The target must be present at that payload path after remapping. |
| `display_name` | `string \| null` | no | `null` | `MyApp` | Shortcut display name. Defaults to the installer name when omitted by downstream tooling. |
| `icon` | `string \| null` | no | `null` | `application-templates/icon.ico` | Optional install-relative shortcut icon path. When omitted or null, the shortcut inherits installer.icon; use an empty string to leave IconLocation unset. Explicit icon paths must be present in the payload after remapping. |

## `config.installer.bootstrap_hooks`

| Field | Type | Required | Default | Example | Description |
| --- | --- | --- | --- | --- | --- |
| `pre_extract` | `list[list[string]]` | no | `[]` |  | Argv commands run before the installer extracts its top layer. These commands cannot use payload files, installer scripts, or bundled top-layer tools because none have been extracted yet. |

## `config.installer.install_hooks`

| Field | Type | Required | Default | Example | Description |
| --- | --- | --- | --- | --- | --- |
| `pre_install` | `list[list[string]]` | no | `[]` |  | Argv commands written into installer metadata to run before installation. |
| `post_install` | `list[list[string]]` | no | `[]` |  | Argv commands written into installer metadata to run after payload files, shortcuts, uninstall support, and Windows Installed Apps registration are complete. |
| `pre_uninstall` | `list[list[string]]` | no | `[]` |  | Argv commands written into installer metadata to run before uninstall while the installed app directory is still present. |
| `post_uninstall` | `list[list[string]]` | no | `[]` |  | Argv commands written into installer metadata to run after the install directory has been removed. Entrypoints inside the install directory must be self-contained .cmd, .ps1, or .exe files because app-builder stages only argv[0] to temp before removal. |

## `config.installer.paths`

| Field | Type | Required | Default | Example | Description |
| --- | --- | --- | --- | --- | --- |
| `include` | `list[string]` | no | `[]` | `[app_builder.yaml, application-templates, bin/python, README.md]` | Required project-relative files or globs included in the release payload. Every entry must match, and the final payload must be nonempty after excludes. |
| `exclude` | `list[string]` | no | `[]` | `['**/__pycache__', dist, venv]` | Project-relative files or globs removed from the selected payload. |
| `include_dist` | `boolean` | no | `false` | `false` | Whether files beneath installer.dist may enter the application payload. The default excludes dist even when a broad include selects the project root, preventing old release files and build logs from being installed. |
| `remap` | `list[tuple[string, string]]` | no | `[]` | `[[README.md, docs/README.md]]` | Two-item source and archive-destination pairs. Each source must be a selected literal project-relative path; destinations must be safe, unique archive paths. |

## `config.build_hooks`

| Field | Type | Required | Default | Example | Description |
| --- | --- | --- | --- | --- | --- |
| `pre_process` | `list[list[string]]` | no | `[]` |  | Argv commands run before dependency or release processing begins. |
| `pre_python_bundled` | `list[list[string]]` | no | `[]` |  | Argv commands run before bundled Python is materialized. |
| `post_python_bundled` | `list[list[string]]` | no | `[]` |  | Argv commands run after bundled Python is materialized. |
| `pre_python_venv` | `list[list[string]]` | no | `[]` |  | Argv commands run before the virtual environment is materialized. |
| `post_python_venv` | `list[list[string]]` | no | `[]` |  | Argv commands run after the virtual environment is materialized. |
| `pre_dist` | `list[list[string]]` | no | `[]` |  | Argv commands run before the release payload is assembled. |
| `post_dist` | `list[list[string]]` | no | `[]` |  | Argv commands run after installer assembly and stale named-output candidates are cleared, but before output collection, checksums, and release notes. This stage may create extra outputs or sign the installer; it must not modify the sealed payload or manifest. |
| `pre_github_release` | `list[list[string]]` | no | `[]` |  | Argv commands run before GitHub release upload. |
| `post_github_release` | `list[list[string]]` | no | `[]` |  | Argv commands run after GitHub release upload. |

## `config.outputs[]`

| Field | Type | Required | Default | Example | Description |
| --- | --- | --- | --- | --- | --- |
| `name` | `string` | yes | required | `wheels` | Unique logical name used by publication targets. Built-in names such as payload, installer, manifest, and checksums are reserved. |
| `pattern` | `string` | yes | required | `wheels/*.whl` | Exact path or non-recursive glob relative to installer.dist. Wildcards are allowed only in the filename segment. |
| `min_matches` | `integer` | no | `1` | `1` | Minimum number of files the pattern must resolve; must be zero or greater. |
| `max_matches` | `integer \| null` | no | `1` | `null` | Maximum number of files the pattern may resolve. It must be at least min_matches; set to null for no upper bound. |

## `config.publications`

| Field | Type | Required | Default | Example | Description |
| --- | --- | --- | --- | --- | --- |
| `github` | `mapping` | no | `see nested defaults` |  | GitHub release publication settings. |

## `config.publications.github`

| Field | Type | Required | Default | Example | Description |
| --- | --- | --- | --- | --- | --- |
| `outputs` | `list[string]` | no | `[payload, installer, manifest, checksums]` |  | Exact logical output names uploaded to the GitHub release. A configured name expands to every matched file; unknown names and case-insensitive upload filename collisions are rejected. |

## Command Values

Hook fields are `list[list[string]]`. Each command is an argv list. Use an explicit shell argv, such as `[cmd, /c, ...]`, when shell behavior is required.

Automatic `.py` entrypoint dispatch is stage-aware. See [Hook Python dispatch](app-builder-help.html#hook-python) for the interpreter used at each lifecycle point. An explicit argv such as `[python, script.py]` deliberately uses the machine's PATH.
