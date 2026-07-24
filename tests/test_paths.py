"""Where per-user data lives, per platform.

The APPDATA environment variable is the suite-wide isolation seam
(tests/conftest.py): it must win on EVERY platform, or macOS/Linux CI would
resolve paths into the runner's real home directory.
"""
import sys
from pathlib import Path

import rekounts.paths as paths


def test_appdata_override_wins_on_every_platform(monkeypatch, tmp_path):
    monkeypatch.setenv("APPDATA", str(tmp_path))
    for platform in ("win32", "darwin", "linux"):
        monkeypatch.setattr(sys, "platform", platform)
        assert paths.app_data_dir() == tmp_path / "Rekounts"


def test_darwin_defaults_to_application_support(monkeypatch, tmp_path):
    monkeypatch.delenv("APPDATA", raising=False)
    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setattr(Path, "home", staticmethod(lambda: tmp_path))
    assert paths.app_data_dir() == (
        tmp_path / "Library" / "Application Support" / "Rekounts")


def test_non_darwin_fallback_is_home(monkeypatch, tmp_path):
    monkeypatch.delenv("APPDATA", raising=False)
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setattr(Path, "home", staticmethod(lambda: tmp_path))
    assert paths.app_data_dir() == tmp_path / "Rekounts"


def test_darwin_legacy_is_the_old_portable_fallback(monkeypatch, tmp_path):
    """The pre-port fallback (~/Rekounts) is what a from-source mac user had;
    the TalkativeAI name never shipped on macOS."""
    monkeypatch.delenv("APPDATA", raising=False)
    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setattr(Path, "home", staticmethod(lambda: tmp_path))
    assert paths.legacy_app_data_dir() == tmp_path / "Rekounts"
    # And it differs from the new home, so migrate.needs_migration can fire.
    assert paths.legacy_app_data_dir() != paths.app_data_dir()


def test_windows_legacy_is_the_old_name(monkeypatch, tmp_path):
    monkeypatch.setenv("APPDATA", str(tmp_path))
    monkeypatch.setattr(sys, "platform", "win32")
    assert paths.legacy_app_data_dir() == tmp_path / "TalkativeAI"


def test_children_hang_off_the_app_dir(monkeypatch, tmp_path):
    monkeypatch.setenv("APPDATA", str(tmp_path))
    root = tmp_path / "Rekounts"
    assert paths.config_path() == root / "config.json"
    assert paths.history_path() == root / "history.db"
    assert paths.models_dir() == root / "models"
    assert paths.logs_dir() == root / "logs"
