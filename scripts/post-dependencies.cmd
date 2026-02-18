@echo off

REM Create a path configuration file to allow Python to find the `app_builder` Python module.
REM See https://docs.python.org/3/library/site.html
(
    echo ../../../..
) > "%~dp0\..\bin\python\Lib\site-packages\app_builder.pth"
