"""Shared filesystem locations for Rekounts' per-user data.

Every piece of user state lives under one folder — `%APPDATA%\\Rekounts` on
Windows, `~/Rekounts` as a portable fallback. config.py, history.py and the
model store all resolve their paths from here so the "where does my data live"
answer is defined once, in one place, instead of copied into each module.

Nothing here creates directories; callers `mkdir(parents=True)` the specific
child they are about to write, exactly as before.
"""

import os
from pathlib import Path

# The pre-rename folder name. Only migrate.py acts on it; it lives here so the
# old name and the new one are declared side by side in the module that owns
# "where does my data live".
LEGACY_APP_DIR_NAME = "TalkativeAI"


def app_data_dir() -> Path:
    """The root folder for all Rekounts user data.

    `%APPDATA%` (roaming) on Windows; the home directory elsewhere so the module
    still imports and the tests still run on Linux/macOS CI.
    """
    return Path(os.environ.get("APPDATA", Path.home())) / "Rekounts"


def legacy_app_data_dir() -> Path:
    """Where the app kept user data under its old name, "TalkativeAI".

    Resolved exactly like :func:`app_data_dir` so an upgrading user's data is
    found on the same drive/roaming profile it was written to. See
    ``rekounts/migrate.py`` — nothing else should reference the old name.
    """
    return Path(os.environ.get("APPDATA", Path.home())) / LEGACY_APP_DIR_NAME


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
