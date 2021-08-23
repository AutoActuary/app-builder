# tools scripts

These tools scripts help us to

- download dependencies like R, Python, Pandoc and their packages
- specify which files to ship to clients
- specify which shortcuts to add to their start menu
- wrap all of this in a 7zip installer
- add an uninstaller for our clients

# Get started

To get started open the base directory of your project in a terminal window, and run the following command:

```
powershell.exe -c "(new-object net.webclient).DownloadFile('https://raw.githubusercontent.com/AutoActuary/deploy-scripts/master/copy-pasties/application.bat','application.bat'); ./application.bat -u"
```
