# app_builder.yaml Configuration Reference

Generated from `app_builder.schema` metadata. `app-builder init` renders its example YAML from the same source.

Required fields can appear in examples without defaults. That means users must provide project-specific values; the loader still rejects missing required values, unknown keys, unsupported shapes, and explicit `null` where a field is not nullable.

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

Example:

```yaml
installer:
  name: "MyApp ${APP.VERSION}"
  install_directory: '${ENV.LOCALAPPDATA}\Acme\${CONFIG.installer.name}'
  paths:
    include:
      - "build/${APP.VERSION}"
    remap:
      - [README.md, "docs/${CONFIG.installer.name}.md"]
```

## Top-Level Config

| Field | Type | Required | Default | Description |
| --- | --- | --- | --- | --- |
| `app_builder_version` | `string \| null` | no | `current` | Version selector read by the meta CLI before loading the full config. Use current for the installed 1.x app-builder; explicit 1.x tags, branches, or commits are resolved through the managed version cache. Use the command line form app-builder 0.x for legacy 0.x projects. |
| `python_bundled` | `mapping \| null` | no | `PythonBundledOptions defaults` | Optional bundled Python runtime. Set to null to disable. |
| `python_venv` | `mapping \| null` | no | `PythonVenvOptions defaults` | Optional Poetry dev virtual environment derived from bundled Python when available. Set to null to disable. |
| `installer` | `mapping` | yes | required | Required installer metadata and release payload settings. |
| `build_hooks` | `mapping` | no | `BuildHooks defaults` | Build and release hook command declarations. |

## `config.python_bundled`

| Field | Type | Required | Default | Description |
| --- | --- | --- | --- | --- |
| `path` | `string` | no | `bin/python` | Project-relative directory where the bundled Python runtime is materialized. |
| `python_version` | `string` | no | `3.11.1` | NuGet Python package version or version prefix to materialize. |

## `config.python_venv`

| Field | Type | Required | Default | Description |
| --- | --- | --- | --- | --- |
| `path` | `string` | no | `venv` | Project-relative directory where the Poetry dev virtual environment is created. |
| `python_version` | `string` | no | `3.11.1` | NuGet Python package version or version prefix used when the virtual environment is self-contained because python_bundled is disabled. |

## `config.installer`

| Field | Type | Required | Default | Description |
| --- | --- | --- | --- | --- |
| `name` | `string` | yes | required | Human-facing application name. |
| `install_directory` | `string` | yes | required | Windows install directory. Percent-style environment variables are expanded at build time. |
| `icon` | `string` | no | `application-templates/icon.ico` | Project-relative .ico file embedded into generated ExeWrap executables and used for Start Menu shortcuts when a shortcut does not specify its own icon. |
| `payload_format` | `string` | no | `zip` | Inner payload archive format. Use zip for the Windows tar.exe path or 7z for stronger compression with bundled 7-Zip extraction. |
| `pause_on_exit` | `boolean` | no | `true` | Whether generated installer scripts should wait briefly before exiting. The wait closes after 30 seconds or Enter; --yes skips prompts and the wait, while --no-wait skips only the wait. |
| `add_uninstaller` | `boolean` | no | `true` | Whether the installer bundle should include an uninstall script. |
| `start_menu` | `list[mapping]` | no | `[]` | Windows Start Menu shortcut declarations. |
| `bootstrap_hooks` | `mapping` | no | `BootstrapHooks defaults` | Early ExeWrap bootstrap hook command declarations. |
| `install_hooks` | `mapping` | no | `InstallHooks defaults` | Installer and uninstaller hook command declarations. |
| `dist` | `string` | no | `dist` | Project-relative output directory for release artifacts. |
| `paths` | `mapping` | no | `PathsMapping defaults` | Payload include, exclude, and remap rules. |

## `config.installer.start_menu[]`

| Field | Type | Required | Default | Description |
| --- | --- | --- | --- | --- |
| `target` | `string` | yes | required | Project-relative command or file launched by the shortcut. |
| `display_name` | `string \| null` | no | `null` | Shortcut display name. Defaults to the installer name when omitted by downstream tooling. |
| `icon` | `string \| null` | no | `null` | Project-relative icon path for the shortcut. |

## `config.installer.bootstrap_hooks`

| Field | Type | Required | Default | Description |
| --- | --- | --- | --- | --- |
| `pre_extract` | `list[list[string]]` | no | `[]` | Argv commands injected into the ExeWrap PowerShell bootstrap before the installer extracts its top layer. These commands cannot use payload files, installer scripts, or bundled top-layer tools because none have been extracted yet. |

## `config.installer.install_hooks`

| Field | Type | Required | Default | Description |
| --- | --- | --- | --- | --- |
| `pre_install` | `list[list[string]]` | no | `[]` | Argv commands written into installer metadata to run before installation. |
| `post_install` | `list[list[string]]` | no | `[]` | Argv commands written into installer metadata to run after installation. |
| `pre_uninstall` | `list[list[string]]` | no | `[]` | Argv commands written into installer metadata to run before uninstall while the installed app directory is still present. |
| `post_uninstall` | `list[list[string]]` | no | `[]` | Argv commands written into installer metadata to run after the install directory has been removed. Entrypoints inside the install directory must be self-contained .cmd, .ps1, or .exe files because app-builder stages only argv[0] to temp before removal. |

## `config.installer.paths`

| Field | Type | Required | Default | Description |
| --- | --- | --- | --- | --- |
| `include` | `list[string]` | no | `[]` | Project-relative files or globs included in the release payload. |
| `exclude` | `list[string]` | no | `[]` | Project-relative files or globs excluded from the release payload. |
| `remap` | `list[tuple[string, string]]` | no | `[]` | Two-item source and destination pairs for relocating payload files. |

## `config.build_hooks`

| Field | Type | Required | Default | Description |
| --- | --- | --- | --- | --- |
| `pre_process` | `list[list[string]]` | no | `[]` | Argv commands run before dependency or release processing begins. |
| `pre_python_bundled` | `list[list[string]]` | no | `[]` | Argv commands run before bundled Python is materialized. |
| `post_python_bundled` | `list[list[string]]` | no | `[]` | Argv commands run after bundled Python is materialized. |
| `pre_python_venv` | `list[list[string]]` | no | `[]` | Argv commands run before the virtual environment is materialized. |
| `post_python_venv` | `list[list[string]]` | no | `[]` | Argv commands run after the virtual environment is materialized. |
| `pre_dist` | `list[list[string]]` | no | `[]` | Argv commands run before the release payload is assembled. |
| `post_dist` | `list[list[string]]` | no | `[]` | Argv commands run after the release payload is assembled. |
| `pre_github_release` | `list[list[string]]` | no | `[]` | Argv commands run before GitHub release upload. |
| `post_github_release` | `list[list[string]]` | no | `[]` | Argv commands run after GitHub release upload. |
| `post_process` | `list[list[string]]` | no | `[]` | Argv commands run at the end of release processing. |

## Command Values

Hook fields are `list[list[string]]`. Each command is an argv list. Use an explicit shell argv, such as `[cmd, /c, ...]`, when shell behavior is required.

When a hook command's `argv[0]` is a `.py` file, app-builder runs it with a project-owned Python from `python_bundled` or `python_venv`. It does not fall back to system Python. Use an explicit argv such as `[python, script.py]` only when the target machine is expected to provide Python.
