import importlib.util
from locate import this_dir
import sys

app_tools_dir = this_dir().parent.parent.joinpath("app_tools")

spec = importlib.util.spec_from_file_location("exec_py", str(app_tools_dir.joinpath("exec_py.py")))
exec_py = importlib.util.module_from_spec(spec)
spec.loader.exec_module(exec_py)

exec_py.exec_py(app_tools_dir.joinpath("versioned_main.py"))
