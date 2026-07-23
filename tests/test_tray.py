"""Tray menu freshness and update-check hardening.

Split in two: pure helpers (repo-slug parsing, no Qt runtime needed) and menu
behavior tests that spin up an offscreen QApplication so they run headless.
"""
import os

import pytest

from rekounts.ui.tray import GITHUB_REPO, _origin_repo_slug, _resolve_repo_slug

# ------------------------------------------------------------- update check
def test_hardcoded_repo_slug_matches_the_origin_remote():
    """The one hardcoded network target must not drift from the real repo.

    Skipped rather than failed when git can't answer (release tarball, CI
    without the remote), which is exactly when the app falls back to the
    constant anyway.
    """
    origin = _origin_repo_slug()
    if origin is None:
        pytest.skip("no git origin available here")
    assert origin.lower() == GITHUB_REPO.lower()


def test_resolve_repo_slug_always_returns_something_usable():
    slug = _resolve_repo_slug()
    assert slug and slug.count("/") == 1


def test_frozen_exe_degrades_to_the_constant(monkeypatch):
    # A PyInstaller build has no .git next to it and often no git on PATH.
    monkeypatch.setattr("sys.frozen", True, raising=False)
    assert _origin_repo_slug() is None
    assert _resolve_repo_slug() == GITHUB_REPO


def test_missing_git_directory_degrades_to_the_constant(monkeypatch):
    monkeypatch.setattr(os.path, "exists", lambda p: False)
    assert _origin_repo_slug() is None


@pytest.mark.parametrize("url, expected", [
    ("https://github.com/rekreatedigital/rekounts.git", "rekreatedigital/rekounts"),
    ("https://github.com/rekreatedigital/rekounts", "rekreatedigital/rekounts"),
    ("git@github.com:rekreatedigital/rekounts.git", "rekreatedigital/rekounts"),
    ("ssh://git@github.com/owner/repo.git", "owner/repo"),
    ("https://gitlab.com/owner/repo.git", None),
    ("", None),
])
def test_origin_url_parsing(monkeypatch, url, expected):
    import subprocess

    import rekounts.ui.tray as tray

    class _Out:
        returncode = 0
        stdout = url

    monkeypatch.setattr(os.path, "exists", lambda p: True)
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: _Out())
    assert tray._origin_repo_slug() == expected


def test_git_failure_is_swallowed(monkeypatch):
    import subprocess

    import rekounts.ui.tray as tray

    def boom(*a, **k):
        raise OSError("git not found")

    monkeypatch.setattr(os.path, "exists", lambda p: True)
    monkeypatch.setattr(subprocess, "run", boom)
    assert tray._origin_repo_slug() is None
    assert tray._resolve_repo_slug() == GITHUB_REPO


# ------------------------------------------------------------ menu behavior
# Offscreen so the suite stays headless and never pops a real tray icon.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
QtWidgets = pytest.importorskip("PySide6.QtWidgets")

from rekounts.config import Config  # noqa: E402  (after importorskip)
from rekounts.ui.tray import TrayApp  # noqa: E402

LANGUAGES = [("English", "en"), ("Spanish", "es"), ("Auto-detect", "auto")]


@pytest.fixture(scope="module")
def app():
    yield QtWidgets.QApplication.instance() or QtWidgets.QApplication([])


@pytest.fixture
def config(tmp_path):
    return Config(tmp_path / "config.json")


@pytest.fixture
def tray(app, config, monkeypatch):
    """A TrayApp whose microphone list is a fixed fake we can mutate."""
    import rekounts.ui.tray as tray_mod
    mics = ["Microphone (EMEET PIXY)", "Headset Microphone (3- SteelSeries Arctis Nova 5)"]
    monkeypatch.setattr(tray_mod, "list_microphones", lambda: list(mics))
    monkeypatch.setattr(tray_mod, "canonical_microphone_name",
                        lambda n: n if n in mics else None)

    t = TrayApp(app, on_open_settings=lambda: None, on_quit=lambda: None,
                config=config, languages=LANGUAGES)
    t.mics = mics
    yield t
    t.tray.hide()


def _labels(menu):
    return [a.text() for a in menu.actions()]


def _checked(menu):
    return [a.text() for a in menu.actions() if a.isChecked()]


def test_menu_is_kept_referenced_on_the_instance(tray):
    # PySide6 can garbage-collect a QMenu owned only by setContextMenu().
    assert tray.menu is not None
    assert tray.tray.contextMenu() is tray.menu


def test_submenus_are_empty_until_opened(tray):
    assert tray._mic_menu.actions() == []
    assert tray._lang_menu.actions() == []


def test_microphone_menu_lists_system_default_first_then_devices(tray):
    tray._mic_menu.aboutToShow.emit()
    assert _labels(tray._mic_menu) == ["System default"] + tray.mics


def test_microphone_menu_checks_system_default_by_default(tray):
    tray._mic_menu.aboutToShow.emit()
    assert _checked(tray._mic_menu) == ["System default"]


def test_microphone_menu_checkmark_follows_config_changed_elsewhere(tray, config):
    tray._mic_menu.aboutToShow.emit()
    assert _checked(tray._mic_menu) == ["System default"]

    # Settings window changes the mic behind the tray's back.
    config.set("microphone", "Microphone (EMEET PIXY)")

    tray._mic_menu.aboutToShow.emit()
    assert _checked(tray._mic_menu) == ["Microphone (EMEET PIXY)"]


def test_microphone_menu_picks_up_a_newly_appearing_device(tray):
    tray._mic_menu.aboutToShow.emit()
    assert "Microphone (Newly Plugged)" not in _labels(tray._mic_menu)

    tray.mics.append("Microphone (Newly Plugged)")

    tray._mic_menu.aboutToShow.emit()
    assert "Microphone (Newly Plugged)" in _labels(tray._mic_menu)


def test_reopening_does_not_duplicate_entries(tray):
    for _ in range(3):
        tray._mic_menu.aboutToShow.emit()
    assert _labels(tray._mic_menu) == ["System default"] + tray.mics


def test_exactly_one_microphone_entry_is_checked(tray, config):
    config.set("microphone", "Headset Microphone (3- SteelSeries Arctis Nova 5)")
    tray._mic_menu.aboutToShow.emit()
    assert len(_checked(tray._mic_menu)) == 1


def test_unplugged_configured_mic_leaves_nothing_checked(tray, config):
    config.set("microphone", "Microphone (Unplugged)")
    tray._mic_menu.aboutToShow.emit()
    assert _checked(tray._mic_menu) == []


def test_picking_a_microphone_writes_config_and_notifies(tray, config):
    seen = []
    tray.on_mic_changed = seen.append
    tray._mic_menu.aboutToShow.emit()

    [act] = [a for a in tray._mic_menu.actions() if a.text() == "Microphone (EMEET PIXY)"]
    act.trigger()

    assert config.get("microphone") == "Microphone (EMEET PIXY)"
    assert seen == ["Microphone (EMEET PIXY)"]
    assert config.path.exists()          # persisted, not just in memory


def test_picking_system_default_clears_the_configured_mic(tray, config):
    config.set("microphone", "Microphone (EMEET PIXY)")
    tray._mic_menu.aboutToShow.emit()

    [act] = [a for a in tray._mic_menu.actions() if a.text() == "System default"]
    act.trigger()

    assert config.get("microphone") is None


def test_a_failing_device_query_still_leaves_a_usable_menu(tray, monkeypatch):
    import rekounts.ui.tray as tray_mod

    def boom():
        raise RuntimeError("PortAudio exploded")

    monkeypatch.setattr(tray_mod, "list_microphones", boom)
    tray._mic_menu.aboutToShow.emit()
    assert _labels(tray._mic_menu) == ["System default"]


def test_language_menu_lists_every_language(tray):
    tray._lang_menu.aboutToShow.emit()
    assert _labels(tray._lang_menu) == [label for label, _ in LANGUAGES]


def test_language_menu_checkmark_follows_config_changed_elsewhere(tray, config):
    tray._lang_menu.aboutToShow.emit()
    assert _checked(tray._lang_menu) == ["English"]

    config.set("language", "es")

    tray._lang_menu.aboutToShow.emit()
    assert _checked(tray._lang_menu) == ["Spanish"]


def test_language_menu_does_not_duplicate_on_reopen(tray):
    for _ in range(3):
        tray._lang_menu.aboutToShow.emit()
    assert len(tray._lang_menu.actions()) == len(LANGUAGES)


def test_picking_a_language_writes_config(tray, config):
    seen = []
    tray.on_language_changed = seen.append
    tray._lang_menu.aboutToShow.emit()

    [act] = [a for a in tray._lang_menu.actions() if a.text() == "Auto-detect"]
    act.trigger()

    assert config.get("language") == "auto"
    assert seen == ["auto"]


def test_no_config_means_no_device_submenus(app):
    t = TrayApp(app, on_open_settings=lambda: None, on_quit=lambda: None)
    try:
        assert t._mic_menu is None and t._lang_menu is None
        assert "Microphone" not in _labels(t.menu)
    finally:
        t.tray.hide()


# ------------------------------------------------- the notifications gate
# Every toast must pass one gate (the "Tray notifications" switch), so the
# tray-originated toasts (mic/language/update-check) can no longer bypass it.
def _spy_toasts(monkeypatch, t):
    shown = []
    monkeypatch.setattr(t.tray, "showMessage", lambda *a: shown.append(a))
    return shown


def test_notify_gate_suppresses_tray_originated_toasts_when_off(app, config,
                                                                monkeypatch):
    t = TrayApp(app, on_open_settings=lambda: None, on_quit=lambda: None,
                config=config, languages=LANGUAGES,
                notifications_enabled=lambda: False)
    try:
        shown = _spy_toasts(monkeypatch, t)
        t.notify("plain")
        t._apply_mic("Some Mic")              # used to call notify() directly
        t._apply_language("es", "Spanish")    # ditto
        t._sig.toast.emit("update result")    # the update-check worker's path
        assert shown == []
    finally:
        t.tray.hide()


def test_notify_gate_allows_toasts_when_on(app, config, monkeypatch):
    t = TrayApp(app, on_open_settings=lambda: None, on_quit=lambda: None,
                config=config, languages=LANGUAGES,
                notifications_enabled=lambda: True)
    try:
        shown = _spy_toasts(monkeypatch, t)
        t.notify("hello")
        assert shown == [("Rekounts", "hello")]
    finally:
        t.tray.hide()


def test_notify_defaults_to_shown_without_a_provider(tray, monkeypatch):
    shown = _spy_toasts(monkeypatch, tray)
    tray.notify("hi")
    assert shown == [("Rekounts", "hi")]


def test_notify_gate_is_read_live(app, config, monkeypatch):
    state = {"on": False}
    t = TrayApp(app, on_open_settings=lambda: None, on_quit=lambda: None,
                config=config, notifications_enabled=lambda: state["on"])
    try:
        shown = _spy_toasts(monkeypatch, t)
        t.notify("first")           # gate off -> dropped
        state["on"] = True
        t.notify("second")          # gate flipped on with nothing rebuilt
        assert shown == [("Rekounts", "second")]
    finally:
        t.tray.hide()


def test_a_broken_gate_still_shows_the_message(app, config, monkeypatch):
    def boom():
        raise RuntimeError("gate exploded")

    t = TrayApp(app, on_open_settings=lambda: None, on_quit=lambda: None,
                config=config, notifications_enabled=boom)
    try:
        shown = _spy_toasts(monkeypatch, t)
        t.notify("must survive")
        assert shown == [("Rekounts", "must survive")]
    finally:
        t.tray.hide()
