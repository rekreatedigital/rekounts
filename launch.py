"""Direct launcher that avoids this machine's --copies venv redirector, which
spawns an extra inert pythonw process. Adds the venv site-packages to sys.path
and runs the app in a single process. Portable: falls back gracefully if the
venv layout differs.
"""
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_VENV_SP = os.path.join(_HERE, ".venv", "Lib", "site-packages")
if os.path.isdir(_VENV_SP) and _VENV_SP not in sys.path:
    sys.path.insert(0, _VENV_SP)

from rekounts.__main__ import main  # noqa: E402

if __name__ == "__main__":
    main()
