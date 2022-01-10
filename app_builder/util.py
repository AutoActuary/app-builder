from textwrap import dedent


def help():
    print(dedent("""
        Usage: app-builder [Options]
        Options:
          -h, --help             Print these options
          -d, --get-dependencies Ensure all the dependencies are set up properly
          -l, --local-release    Create a local release
          -g, --github-release   Create a release and upload it to GitHub 
        """))
