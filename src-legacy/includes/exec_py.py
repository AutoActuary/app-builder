def exec_py(filepath, global_names=None, local_names=None):
    """
    This function mimics execfile from python 2. It is used to execute a python script
    as if run from the terminal, but in the same python instance as the current python
    instance, with the default globals of the current python script. A simple Import
    can't achieve the same, since import only imports once and import doesn't run code
    in the main guard.

    >>> import tempfile
    >>> import os
    >>> fname = os.path.join(tempfile.gettempdir(), "test_exec_py_"+os.urandom(24).hex()+".py")
    >>> with open(fname, 'w') as f:
    ...     _ = f.write('''
    ... print(f'Hello from {__file__}')
    ... print('hello' in globals())
    ... var_from_file = True
    ... if __name__ == '__main__':
    ...     print('Hello from inside main')
    ... ''')

    Access the filename and the main guard. Variable hello should not be in globals.
    >>> exec_py(fname) #doctest: +ELLIPSIS
    Hello from ...test_exec_py....py
    False
    Hello from inside main

    There shouldn't leak anything into this namespace
    >>> 'var_from_file' in globals()
    False

    The __file__ attribute should remain in tact after calling the script
    >>> __file__  #doctest: +ELLIPSIS
    '...exec_py.py'

    Our globals should be passed down to the lower script
    >>> hello = True
    >>> exec_py(fname, global_names=globals()) #doctest: +ELLIPSIS
    H...
    True
    H...

    Globals are accessible within the script
    >>> 'var_from_file' in globals()
    True

    >>> os.remove(fname)
    """
    if global_names is None:
        global_names = {}

    global_names.update({
        "__file__": filepath,
        "__name__": "__main__",
    })

    with open(filepath, 'rb') as file:
        exec(compile(file.read(), filepath, 'exec'), global_names, local_names)
