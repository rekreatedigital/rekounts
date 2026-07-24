"""Direct launcher that avoids this machine's --copies venv redirector, which
spawns an extra inert pythonw process. Adds the venv site-packages to sys.path
and runs the app in a single process. Portable: falls back gracefully if the
venv layout differs (Windows `.venv\\Lib\\site-packages`, POSIX
`.venv/lib/python3.x/site-packages`).
"""
import glob
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_CANDIDATES = [os.path.join(_HERE, ".venv", "Lib", "site-packages")]
_CANDIDATES += sorted(glob.glob(
    os.path.join(_HERE, ".venv", "lib", "python3*", "site-packages")))
for _sp in _CANDIDATES:
    if os.path.isdir(_sp) and _sp not in sys.path:
        sys.path.insert(0, _sp)
        break

from rekounts.__main__ import main  # noqa: E402

if __name__ == "__main__":
    main()
