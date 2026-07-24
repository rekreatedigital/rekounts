"""Shared filesystem locations for Rekounts' per-user data.

Every piece of user state lives under one folder — `%APPDATA%\\Rekounts` on
Windows, `~/Library/Application Support/Rekounts` on macOS, `~/Rekounts` as a
portable fallback elsewhere. config.py, history.py and the model store all
resolve their paths from here so the "where does my data live" answer is
defined once, in one place, instead of copied into each module.

The ``APPDATA`` environment variable, when set, wins on EVERY platform, not
just Windows: it is the seam the test suite (tests/conftest.py) uses to pin all
user data to a throwaway directory, and honoring it everywhere is what keeps
macOS/Linux CI from ever touching a real home directory.

Nothing here creates directories; callers `mkdir(parents=True)` the specific
child they are about to write, exactly as before.
"""

import os
import sys
from pathlib import Path

# The pre-rename folder name. Only migrate.py acts on it; it lives here so the
# old name and the new one are declared side by side in the module that owns
# "where does my data live".
LEGACY_APP_DIR_NAME = "TalkativeAI"


def _base_dir() -> Path:
    """The platform's per-user application-data root.

    ``APPDATA`` overrides everywhere (see the module docstring); on Windows it
    is always set by the OS, so production behavior there is unchanged.
    """
    override = os.environ.get("APPDATA")
    if override:
        return Path(override)
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support"
    return Path.home()


def app_data_dir() -> Path:
    """The root folder for all Rekounts user data."""
    return _base_dir() / "Rekounts"


def legacy_app_data_dir() -> Path:
    """Where an upgrading user's data would be found under an OLD location.

    * Windows: `%APPDATA%\\TalkativeAI` — the pre-rename folder, resolved
      exactly like :func:`app_data_dir` so the data is found on the same
      drive/roaming profile it was written to.
    * macOS: `~/Rekounts` — the portable home-directory fallback this module
      used before the macOS port gave darwin a real Application Support home.
      (The TalkativeAI name never shipped on macOS, so the rename migration
      does not apply there; the location move does.)

    See ``rekounts/migrate.py`` — nothing else should reference old locations.
    """
    if sys.platform == "darwin" and not os.environ.get("APPDATA"):
        return Path.home() / "Rekounts"
    return _base_dir() / LEGACY_APP_DIR_NAME


def config_path() -> Path:
    return app_data_dir() / "config.json"


def history_path() -> Path:
    return app_data_dir() / "history.db"


def models_dir() -> Path:
    """Where downloaded speech models are installed — the app's OWN directory,
    never the shared Hugging Face cache. One subfolder per model name."""
    return app_data_dir() / "models"


def logs_dir() -> Path:
    return app_data_dir() / "logs"
