from locate import this_dir
import subprocess
import sys

if __name__ == "__main__":
    # For now shadow the previous legacy application
    sys.exit(subprocess.call([str(this_dir().joinpath("..", "src-legacy", "tools", "application-full.bat"))]))