# app-builder 0.x version bridge

## Goal

Allow an already-installed app-builder 0.x launcher to select and run an app-builder
1.x version for a project that has migrated to `app_builder.yaml`. Users do not have
to replace their old launcher before the migrated project can build.

The old launcher already follows most of the required recipe:

1. Read the requested app-builder version from `application.yaml`.
2. Clone that Git ref into its `versions/<ref>` cache.
3. Create a version-specific venv and install the ref's root `requirements.txt`.
4. Dispatch to the checked-out app-builder implementation.

Modern 1.x is not directly runnable by every historical dispatch form. This local
bridge adapts the old recipe with two contained compatibility tricks:

1. The root requirements file points pip back to this package through a local HTML
   package link, so the bridge is installed by the old launcher's existing step 3.
2. A guarded `.pth` activator exposes the sibling checked-out 1.x repository when
   that version venv starts, while 1.x also accepts the older direct `main.py` entry.

The result is the normal 1.x CLI reading `app_builder.yaml`. Outside an exact legacy
version-cache layout, the activator does nothing. It does not replace or upgrade the
outer 0.x installation.
