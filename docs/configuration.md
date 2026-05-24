# app_builder.yaml Configuration Reference

Generated from `app_builder.schema` metadata. `app-builder init` renders its example YAML from the same source.

Required fields can appear in examples without defaults. That means users must provide project-specific values; the loader still rejects missing required values, unknown keys, unsupported shapes, and explicit `null` where a field is not nullable.

## Top-Level Config

| Field | Type | Required | Default | Description |
| --- | --- | --- | --- | --- |
| `app_builder_version` | `string \| null` | no | `v1.0.0` | Accepted as metadata only. Version dispatch is intentionally disabled for now. |
| `python_bundled` | `mapping \| null` | no | `PythonBundledOptions defaults` | Optional bundled Python runtime. Set to null to disable. |
| `python_venv` | `mapping \| null` | no | `PythonVenvOptions defaults` | Optional virtual environment derived from bundled Python when available. Set to null to disable. |
| `installer` | `mapping` | yes | required | Required installer metadata and release payload settings. |
| `build_hooks` | `mapping` | no | `BuildHooks defaults` | Build and release hook command declarations. |

## `config.python_bundled`

| Field | Type | Required | Default | Description |
| --- | --- | --- | --- | --- |
| `path` | `string` | no | `bin/python` | Project-relative directory where the bundled Python runtime is materialized. |
| `python_version` | `string` | no | `3.11.1` | NuGet Python package version or version prefix to materialize. |
| `pip_version` | `string` | no | `23.2.1` | Pip version specifier installed into the bundled runtime. |
| `requirements` | `list[string]` | no | `[]` | Inline pip requirements installed into the bundled runtime. |
| `requirements_files` | `list[string]` | no | `[]` | Project-relative requirement file globs installed into the bundled runtime. |

## `config.python_venv`

| Field | Type | Required | Default | Description |
| --- | --- | --- | --- | --- |
| `path` | `string` | no | `venv` | Project-relative directory where the derived virtual environment is created. |
| `requirements` | `list[string]` | no | `[]` | Inline pip requirements installed into the virtual environment. |
| `requirements_files` | `list[string]` | no | `[]` | Project-relative requirement file globs installed into the virtual environment. |

## `config.installer`

| Field | Type | Required | Default | Description |
| --- | --- | --- | --- | --- |
| `name` | `string` | yes | required | Human-facing application name. |
| `install_directory` | `string` | yes | required | Windows install directory. Percent-style environment variables are expanded at build time. |
| `ascii_banner` | `string` | no | `application-templates/asciibanner.txt` | Project-relative ASCII banner used by generated installer assets. |
| `icon` | `string` | no | `application-templates/icon.ico` | Project-relative icon used by generated installer assets. |
| `pause_on_exit` | `boolean` | no | `true` | Whether generated installer scripts should pause before exiting. |
| `add_uninstaller` | `boolean` | no | `true` | Whether the installer bundle should include an uninstall script. |
| `start_menu` | `list[mapping]` | no | `[]` | Windows Start Menu shortcut declarations. |
| `install_hooks` | `mapping` | no | `InstallHooks defaults` | Installer and uninstaller hook command declarations. |
| `dist` | `string` | no | `dist` | Project-relative output directory for release artifacts. |
| `paths` | `mapping` | no | `PathsMapping defaults` | Payload include, exclude, and remap rules. |

## `config.installer.start_menu[]`

| Field | Type | Required | Default | Description |
| --- | --- | --- | --- | --- |
| `target` | `string` | yes | required | Project-relative command or file launched by the shortcut. |
| `display_name` | `string \| null` | no | `null` | Shortcut display name. Defaults to the installer name when omitted by downstream tooling. |
| `icon` | `string \| null` | no | `null` | Project-relative icon path for the shortcut. |

## `config.installer.install_hooks`

| Field | Type | Required | Default | Description |
| --- | --- | --- | --- | --- |
| `pre_install` | `list[list[string]]` | no | `[]` | Argv commands written into installer metadata to run before installation. |
| `post_install` | `list[list[string]]` | no | `[]` | Argv commands written into installer metadata to run after installation. |
| `pre_uninstall` | `list[list[string]]` | no | `[]` | Argv commands written into installer metadata to run before uninstall. |
| `post_uninstall` | `list[list[string]]` | no | `[]` | Argv commands written into installer metadata to run after uninstall. |

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
