"""Print the project version, for build scripts that cannot import the package.

``rekounts/__init__.py`` is the one place the version literal lives. build.bat
needs it to name the release ZIP, Rekounts.spec needs it for the .exe's version
resource, and pyproject.toml resolves its own version from the same attribute —
but none of them can just import ``rekounts``, because importing the package
from a build script drags Qt and ctranslate2 into the build process.

    .venv\\Scripts\\python scripts\\version.py   ->   0.3.0
"""
import re
import sys
from pathlib import Path

INIT = Path(__file__).resolve().parent.parent / "rekounts" / "__init__.py"


def read_version() -> str:
    m = re.search(r'^__version__\s*=\s*["\']([^"\']+)["\']',
                  INIT.read_text(encoding="utf-8"), re.M)
    if not m:
        raise SystemExit(f"no __version__ found in {INIT}")
    return m.group(1)


if __name__ == "__main__":
    print(read_version())
    sys.exit(0)
