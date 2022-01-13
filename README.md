# App-builder

### Usage
```
Usage: app-builder [Options]
Options:
  -h, --help             Print these options
  -d, --get-dependencies Ensure all the dependencies are set up properly
  -l, --local-release    Create a local release
  -g, --github-release   Create a release and upload it to GitHub
  -i, --init             Initiate current git repo as an app-builder project
```

Use `-i` to create a template app-builder configuration file within your project: <br>
![image](https://user-images.githubusercontent.com/4103775/149367396-a30c3821-3f9b-4344-b762-9dc02b90174f.png)

From here on forth you can edit this file to configure your application to your requirements and use the rest of the app to compile releases and publish them on GitHub.

### History
This is a port of `deploy-scripts` with a focus on extracting only the functionality that is related to packaging an app. The first priority was to debundle our packaging and dependency tools from other drips and drabs. The main reason is that `deploy-scripts` shared a python instance with the app it is deploying, and as a result package-upgrades from the app side constantly broke the `deploy-scipts` side. With this rework, `app-builder` can check-out any version of itself completely isolated from the rest of the system.

### Roadmap
- Write documentation (or at least a how-to guide)
- Take what we need from the legacy code base and start with a cleaner implementation
- Also make this into a pip installable module
