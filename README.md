# App-builder

### History
This is a port of `deploy-scripts` with a focus on extracting only the functionality that is related to packaging an app. The first priority was to debundle our packaging and dependency tools from other drips and drabs. The main reason is that `deploy-scripts` shared a python instance with the app it is deploying, and as a result package-upgrades from the app side constantly broke the `deploy-scipts` side. With this rework, `app-builder` can check-out any version of itself completely isolated from the rest of the system.

### Roadmap
- Write documentation (or at least a how-to guide)
- Take what we need from the legacy code base and start with a cleaner implementation
- Also make this into a pip installable module
