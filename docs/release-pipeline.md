# Release Pipeline

This is the current 1.x release path from `app_builder.yaml` to local artifacts or GitHub Releases.

## 1. Command Entry

```text
app-builder release [--version <version>] [--verbose]
app-builder release-gh [--version <version>] [--draft | --no-draft] [--verbose]
```

`release` creates local artifacts. `release-gh` runs a local build first, then uploads the outputs selected by `publications.github.outputs` with GitHub CLI (`gh.exe`).

When `--version` is omitted, app-builder uses git-based version detection and falls back to `0.0.0-dev`.

For app-builder's own publication, the release version must equal the version in
`pyproject.toml`. The installed dogfood CLI reads its version from the installed
manifest, so the installer identity and `app-builder --version` cannot diverge.

## 2. Config Loading

`app_builder.yaml` is parsed as YAML, then string interpolation runs before dataclass schema validation.

Before dependencies or hooks run, release preflight rejects unsafe Windows app
names, invalid Git tag versions, dangerous install roots, invalid Python version
selectors, empty hook argv, and unsafe dist/runtime write paths. A runtime section
requires an explicit `python_version`; omitting the whole section disables it. Dist,
`python_bundled.path`, and `python_venv.path` must resolve to project
subdirectories. Install paths must be an
absolute application subdirectory or live beneath `%LOCALAPPDATA%`, `%APPDATA%`,
or `%USERPROFILE%`.

Supported interpolation variables:

- `${ENV.NAME}`
- `${GIT.DESCRIBE}`
- `${GIT.COMMIT}`
- `${GIT.SHORT_COMMIT}`
- `${GIT.BRANCH}`
- `${GIT.TAG}`
- `${GIT.IS_DIRTY}`
- `${APP.VERSION}`
- `${CONFIG.path.to.value}`

Interpolation is string-only. References to lists or mappings fail loudly, as do missing values and circular `CONFIG.*` references. `app_builder_version` stays literal because app-builder reads it from plain YAML before config interpolation is available.

## 3. Dependency And Build Hooks

The release path runs dependency stages before file collection:

- `pre_process`
- `pre_python_bundled`
- materialize bundled Python and its main dependencies
- `post_python_bundled`
- `pre_python_venv`
- materialize the project venv and its development dependencies
- `post_python_venv`
- `pre_dist`

Python dependencies come from `pyproject.toml` and an existing `poetry.lock`.
Normal builds run Poetry's read-only lock check and never regenerate the lock;
`app-builder lock` is the explicit lock-changing command. Registry artifacts are
installed with pip hash checking, Git sources require a full resolved commit,
mutable Poetry `file` and `directory` sources are rejected, Python's complete
Windows runtime is selected from the Python.org runtime index and verified against
its published SHA-256, and
ExeWrap is pinned to a versioned asset and SHA-256 digest. The installer manifest
records this build-input provenance.

Each project runtime records the lock digest and groups installed into it. A
different lock, changed group selection, or missing marker causes the runtime to
be rebuilt before dependencies are installed. Runtime creation is serialized per
target path. The complete candidate is built and validated in a unique sibling
directory, then atomically promoted, so a concurrent or failed build cannot expose
a partial runtime or destroy the previous usable one. This also applies when the
new selection is empty, so removed packages cannot survive from an earlier build.

Python.org index and artifact requests have a 30-second socket deadline and at
most three attempts for transient network failures. Normal runtime selection
excludes free-threaded package variants unless a future explicit config contract
opts into them.

Automatic `.py` entrypoint dispatch follows runtime availability: the two hooks before bundled-Python materialization use app-builder's current interpreter; hooks after that prefer bundled Python; hooks after venv materialization prefer the venv, then bundled Python, then app-builder's interpreter. The authoritative per-hook table is in [Hook Python dispatch](app-builder-help.html#hook-python). An explicit command such as `[python, scripts/build.py]` intentionally uses whatever `python` the machine provides.

`app-builder deps` runs this sequence through `post_python_venv` without building
release files. `app-builder python` is narrower: it materializes only the bundled
interpreter and does not run these hooks or install project dependencies.

`pre_dist` is the last hook that can generate files for the payload through normal include/remap rules. After the installer is assembled, app-builder removes files that could satisfy configured named outputs, then `post_dist` creates the current build's extra outputs. It may also sign the final installer, but it cannot modify the payload or manifest because those bytes are already embedded. Checksums and release notes are generated afterward.

## 4. Payload Build

app-builder collects project-relative files with:

- `installer.paths.include`
- `installer.paths.exclude`
- `installer.paths.remap`

Every include must match, the final payload must contain at least one file, and
every literal remap source must exist and be selected. Symlink or traversal paths
that escape the project are rejected. The detailed build log records every
resolved source-to-archive mapping.

The configured `installer.dist` directory is excluded from the payload even if a
broad include selects it. Set `installer.paths.include_dist: true` only when
release output genuinely belongs in the installed application.

Configured Python environments are materialized into the project but are not
implicitly selected for the payload. An installed app that needs bundled Python
must include `python_bundled.path`, normally `bin/python`, in
`installer.paths.include`. The project venv is normally a build environment and
is packaged only when selected deliberately.

When bundled Python is selected, the manifest records its final install-relative
root. After the payload reaches the installation directory, the installer
rewrites that runtime's `pyvenv.cfg` to its installed `python` directory before
running post-install hooks. Build-machine paths therefore cannot leak into
`sys._base_executable`, and the installed runtime remains able to create venvs.

Remap entries are source and destination pairs. Archive destinations are validated
before either writer runs. ZIP and 7-Zip both reject absolute paths, traversal,
Windows-reserved names, generated paths such as `version.txt`, case-insensitive
duplicate destinations, and file/directory collisions.

Generated payload metadata includes `version.txt`. That file is not an install identity marker; current installer identity comes from the embedded manifest.

`installer.payload_format` controls the inner archive:

- `zip` writes `<slug>-<version>.zip`.
- `7z` writes `<slug>-<version>.7z`.

The 7z writer keeps the useful 0.x behaviors without reviving the old tool folder model: remapped files are staged under their target archive names, files that 7z cannot read directly because of Windows locks are copied to temp first, and routine 7-Zip banner/progress/success output is suppressed while failures remain readable.

## 5. Manifest Build

The release manifest is written next to the artifacts and embedded into the installer scripts. It contains:

- app name and version;
- the exact Git commit checked out when the build started;
- configured install directory;
- payload archive name;
- uninstaller flag;
- Start Menu entries;
- install and uninstall hook argv lists;
- the installed bundled-Python root when that runtime is in the payload;
- included payload file records;
- locked dependency and downloaded-tool provenance used for the build.

The installed uninstaller reads the manifest for metadata and hooks. It does not use the manifest as authority for the deletion root.

## 6. Installer Build

The installer is a self-extracting executable with an appended stored ZIP. The outer ZIP is stored, not compressed, so Windows can still read it as a ZIP if a user renames the installer to `.zip`.

The outer layer layout is:

```text
install.cmd
bin/install.ps1
bin/uninstall.cmd       # when installer.add_uninstaller is true
bin/uninstall.ps1       # when installer.add_uninstaller is true
bin/7z.exe              # only when installer.payload_format: 7z
bin/7z.dll              # only when installer.payload_format: 7z
<slug>-<version>.zip    # or .7z
```

`install.cmd` is a manual helper for users who rename or extract the installer ZIP by hand. The normal executable path runs the PowerShell installer directly and forwards all command-line arguments.

## 7. Installer Bootstrap

The generated bootstrap:

1. runs `installer.bootstrap_hooks.pre_extract`;
2. creates a random temp extraction directory under `%TEMP%`;
3. receives the installer path through ExeWrap's child environment and extracts the outer layer with `tar.exe -xf <installer.exe> -C <temp>`;
4. runs the PowerShell installer script and forwards all command-line arguments;
5. removes the temp extraction directory.

## 8. Bootstrap Hooks

`installer.bootstrap_hooks.pre_extract` commands run before the outer installer layer is extracted. They are useful for banners, early checks, or other machine-level work that does not need app files.

These hooks are structured argv lists, not raw PowerShell strings. app-builder runs the argv as given. If a project explicitly runs `cmd.exe /C`, then cmd's own parsing rules apply because the project asked for a shell.

Because this hook runs before extraction, it cannot use the app payload, `install.cmd`, `bin/install.ps1`, bundled 7z tools, or staged app files.

## 9. Installation Runtime

`bin/install.ps1` performs the actual install:

- confirms the action unless a bypass flag is supplied;
- extracts the inner ZIP with `tar.exe` or the inner 7z with bundled `bin\7z.exe`;
- recognizes current app-builder installs for the same app;
- recognizes selected legacy app-builder install shapes for upgrade;
- refuses unknown directories and different app-builder apps by default;
- runs `pre_install`;
- moves a recognized current or legacy install to a private sibling backup before replacement;
- writes the installed manifest;
- copies `bin\uninstall.cmd` and `bin\uninstall.ps1` into the installed app's own `bin` directory when enabled;
- creates Start Menu shortcuts;
- registers a per-user Windows Installed Apps entry when the uninstaller is enabled;
- runs `post_install` after files, shortcuts, uninstall support, and Installed Apps registration are complete;
- removes superseded legacy Windows integration and the backup only after `post_install` succeeds;
- restores the prior directory, Start Menu group, and registration state when replacement fails;
- waits before closing when configured.

For existing `.py` installer-hook entrypoints, automatic dispatch checks
the configured `python_venv.path` and then `python_bundled.path` interpreter
locations recorded in the installer manifest. Each interpreter must be included
in the final payload. An explicit `[python, ...]` still deliberately uses PATH.

Installer runtime flags:

- `--yes`
  - bypass questions and the final close wait.
- `--no-wait`
  - skip only the final close wait.

When `installer.wait_on_exit` is true and no bypass flag is supplied, the console closes after 30 seconds or when the user presses Enter. Other keys are ignored.

## 10. Uninstall Runtime

The installed Start Menu uninstall shortcut points to:

```text
<install-root>\bin\uninstall.cmd
```

That cmd file launches:

```text
<install-root>\bin\uninstall.ps1
```

The PowerShell uninstaller infers the install root from its own location:

```powershell
$InstallDir = Split-Path -Parent $PSScriptRoot
```

This is deliberate. Moving an installed app directory should move its uninstall authority with it, and a manifest path mismatch must not delete a different directory.

Uninstall flow:

- confirm the action unless a bypass flag is supplied;
- run `pre_uninstall` while the app directory is still present;
- remove Start Menu entries;
- stage allowed `post_uninstall` entrypoints to temp;
- remove the install directory;
- remove the Windows Installed Apps entry after the install directory is gone;
- run `post_uninstall` from the temp staging directory;
- preserve temp diagnostics if post-uninstall cleanup fails.

If a `post_uninstall` entrypoint points inside the install directory, it must be a self-contained `.cmd`, `.ps1`, or `.exe`. app-builder stages only `argv[0]` to temp before removal.

## 11. Icons

`installer.icon` is optional. When configured, app-builder embeds it into generated executables. A Start Menu shortcut whose `icon` is omitted or `null` inherits that icon. app-builder automatically adds the inherited icon to the payload at its normal project-relative destination or its configured remap, and records that installed destination in the manifest.

When `installer.icon` is omitted, app-builder leaves the shortcut's `IconLocation` unset and Windows uses the target executable or file-type icon. Set a shortcut's `icon` to an empty string to request the same Windows fallback even when the installer has an icon. A nonempty shortcut `icon` is an explicit install-relative payload path and must already exist after remapping.

For app-builder's dogfood build, the same icon is embedded into the generated payload `app-builder.exe`.

## 12. Release Outputs And Assets

A local release produces:

- the inner payload archive, `.zip` or `.7z`;
- the installer executable, `<slug>-<version>-installer.exe`;
- the manifest JSON, `<slug>-<version>-manifest.json`;
- `<slug>-<version>-SHA256SUMS.txt` covering every resolved release output;
- `<slug>-<version>-release-notes.md`, generated from Git history and the artifact inventory.

Projects can declare named `outputs` as exact files or bounded filename globs
under `installer.dist`. A declaration can collect one file or a deterministic
collection such as wheels produced by `post_dist`. `publications.github.outputs`
selects built-in names (`payload`, `installer`, `manifest`, `checksums`) and
configured names explicitly. Unknown selections, duplicate paths, broad recursive
globs, unmet match counts, and case-insensitive GitHub filename collisions fail.
Files matching named-output declarations are removed before `post_dist`, so a
successful build cannot silently republish an asset left by an earlier run.

`release-gh` uploads exactly that selected set through GitHub CLI. The generated
notes become the GitHub release body rather than a duplicate asset.

Before upload, publication preflight enforces:

- a valid Git tag name and clean Git worktree outside the dist directory;
- package/release version agreement for app-builder itself;
- local and authenticated GitHub tag targets that either do not exist yet or point to HEAD;
- nonempty artifacts inside the configured dist directory;
- matching manifest identity and payload name;
- a manifest build commit equal to the current clean HEAD;
- a readable outer installer ZIP with its required bootstrap files;
- byte-for-byte agreement between the standalone payload and the payload embedded
  in the installer, plus semantic agreement between published and embedded manifests;
- matching SHA-256 checksums and no unexpected same-version files;
- authenticated `gh.exe` and a resolvable GitHub repository.

Every GitHub release command is pinned to the one repository resolved during
preflight, regardless of ambient `GH_REPO`. New releases target the exact audited
HEAD commit. Existing tagless drafts are retargeted to that commit. Existing
releases upload replacement assets and refresh metadata before stale assets are
removed, so a failed upload leaves the old release inventory intact.
`--draft` controls newly created releases; an existing release keeps its current
draft or published state when it is updated.

GitHub CLI requirements:

```text
winget install --id GitHub.cli
gh auth login
```

app-builder searches PATH, `where.exe`, Program Files, LocalAppData, WinGet, Chocolatey, Scoop, and package-local candidates before reporting that `gh.exe` is missing.

## 13. Build Progress And Logs

Release builds print eight named stages as they begin and end, including elapsed
time and failure context. Dependency installation uses quiet pip output so a
normal build remains readable. Every run writes a timestamped diagnostic log to
`<dist>/build-logs`; it includes resolved payload mappings, pinned build inputs,
output sizes and hashes, and the final publication selection. `--verbose` also
prints those details to the terminal.

## 14. Reusable Build Caches

Reusable downloads and managed app-builder versions use a user-local cache. On
Windows the root defaults to `%LOCALAPPDATA%\app-builder\cache`; on other
platforms it follows `XDG_CACHE_HOME` and then `~/.cache/app-builder`. Set
`APP_BUILDER_CACHE_ROOT` to make the complete app-builder cache tree explicit,
especially in CI. This is machine policy rather than project release behavior,
so it is not an `app_builder.yaml` setting.

The configured root contains content-keyed Python and ExeWrap archives under
`downloads`, managed app-builder checkouts under `versions`, and cache locks
under `locks`. Downloads use URL-derived keys so unrelated assets with the same
filename cannot collide. A download is written privately, digest-checked when a
digest is published, and atomically promoted while holding a cross-process lock.
A failed or partial download never becomes a cache hit.

When `APP_BUILDER_CACHE_ROOT` is explicitly set, app-builder supplies
`<root>/pip` and `<root>/poetry` to its pip and Poetry subprocesses. Explicit
standard `PIP_CACHE_DIR` and `POETRY_CACHE_DIR` values take precedence. When the
app-builder root is not explicitly set, pip and Poetry retain their own native
cache defaults.

Use `app-builder cache path` for the resolved root and `app-builder cache info`
for all effective locations. A GitHub Actions job can persist the complete tree:

```yaml
env:
  APP_BUILDER_CACHE_ROOT: ${{ runner.temp }}/app-builder-cache

steps:
  - uses: actions/cache@v4
    with:
      path: ${{ env.APP_BUILDER_CACHE_ROOT }}
      key: app-builder-v1-${{ runner.os }}-${{ hashFiles('poetry.lock', 'app_builder.yaml') }}
      restore-keys: |
        app-builder-v1-${{ runner.os }}-
```

All app-builder-owned settings use the `APP_BUILDER_` namespace. An unknown
name produces a warning with a likely spelling correction; values are never
printed. Set cache variables before the first app-builder command in a process.

## 15. Managed App-Builder Versions

An explicit 1.x `app_builder_version` ref is resolved from the app-builder Git
repository into the user cache at `%LOCALAPPDATA%\app-builder\cache` (or
`APP_BUILDER_CACHE_ROOT`). Cache keys include the source URL and requested ref.
The manifest records the requested ref, whether it resolved as a tag, branch, or
commit, and the exact commit used. Tags are immutable and a moved cached tag is
refused; branch refs are refreshed and rebuilt when their remote commit changes.
The selected commit's `poetry.lock` supplies the exact main dependency
set with artifact hash checking. The checked-out source runs directly instead of
being installed with a fresh dependency solve, and the cache manifest records the
lock digest.
Source refresh and per-ref creation use cross-process locks. A new cache is built
in a private sibling directory and atomically promoted only after its environment
and manifest are complete.

Use `app-builder versions list` to inspect the cache and
`app-builder versions remove <ref>` for deliberate eviction.
These cache-management commands always run in the installed outer CLI, even when
the current project pins another app-builder version.

## 16. Release Owner Checklist

1. When dependencies changed, run `app-builder lock` deliberately and commit both
   `pyproject.toml` and `poetry.lock`.
2. From a clean checkout, run `app-builder release --version <version> --verbose`.
3. Review the resolved output inventory, checksums, generated notes, build log,
   and executable signing status.
4. Exercise the actual installer executable in a disposable user environment:
   fresh install, application launch, same-app replacement, and uninstall through
   the generated shortcut or Windows Installed Apps entry.
5. Confirm the intended tag and HEAD, then run
   `app-builder release-gh --version <version>`; publication preflight repeats the
   identity and artifact checks before upload.

The Windows CI job runs the full suite and launches the final ExeWrap installer
executable. Retain a recorded local rehearsal for public releases as an additional
check of the exact candidate and local Windows environment.
