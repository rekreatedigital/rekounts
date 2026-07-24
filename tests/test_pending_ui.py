"""The two surfaces that make a deferred apply impossible to miss.

Both are deliberately independent of the "Tray notifications" switch, because
that switch being off is exactly the case where a multi-second model reload used
to be invisible.
"""
import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
QtCore = pytest.importorskip("PySide6.QtCore")
QtWidgets = pytest.importorskip("PySide6.QtWidgets")

from rekounts.config import Config                       # noqa: E402
from rekounts.history import History                     # noqa: E402
from rekounts.ui.overlay import Overlay                  # noqa: E402
from rekounts.ui.settings_page import SettingsPage       # noqa: E402

FAKE_MICS = [("Microphone (ME6S)", "Microphone (ME6S)")]


@pytest.fixture(scope="module")
def app():
    yield QtWidgets.QApplication.instance() or QtWidgets.QApplication([])


@pytest.fixture
def overlay(app):
    o = Overlay()
    yield o
    o.deleteLater()


@pytest.fixture
def page(app, tmp_path, monkeypatch):
    monkeypatch.setattr("rekounts.ui.settings_page.microphone_options",
                        lambda: list(FAKE_MICS))
    cfg = Config(path=tmp_path / "config.json")
    history = History(path=tmp_path / "history.db")
    applies = []
    p = SettingsPage(cfg, history, on_saved=lambda: applies.append(1))
    p.applies = applies
    p.cfg = cfg
    yield p
    p.deleteLater()
    history.close()


# ------------------------------------------------------------------- the pill
def test_pill_starts_with_nothing_pending(overlay):
    assert overlay._pending == ""


def test_set_pending_shows_and_clears(overlay):
    overlay.set_pending("Loading Medium…")
    assert overlay._pending == "Loading Medium…"
    overlay.set_pending("")
    assert overlay._pending == ""


def test_none_clears_rather_than_showing_the_word_none(overlay):
    overlay.set_pending("Loading Medium…")
    overlay.set_pending(None)
    assert overlay._pending == ""


def test_pending_replaces_the_idle_hint(overlay):
    """The pending message is what the user needs; the hotkey reminder isn't."""
    overlay.set_hotkey_label("F8")
    assert "F8" in overlay._idle_hint()
    overlay.set_pending("Loading Medium…")
    assert overlay._idle_hint() == "Loading Medium…"
    overlay.set_pending("")
    assert "F8" in overlay._idle_hint()


def test_pending_survives_state_changes(overlay):
    """A reload outlives the dictation started during it — the dot must too."""
    overlay.set_pending("Loading Medium…")
    for state in ("recording", "processing", "idle"):
        overlay.set_state(state)
        assert overlay._pending == "Loading Medium…"


def test_the_pill_paints_in_every_state_while_pending(overlay):
    """The dot is drawn for recording/processing too (dictating inside a stale
    window is the case worth flagging), so painting must survive there."""
    overlay.set_pending("Loading Medium…")
    for state in ("idle", "recording", "processing"):
        overlay.set_state(state)
        overlay.grab()          # would raise if paintEvent blew up


def test_hovered_pill_resizes_to_fit_a_long_pending_message(overlay):
    overlay.set_state("idle")
    overlay._hovered = True
    overlay._resize_for_state()
    narrow = overlay.width()
    overlay.set_pending("Loading Medium… dictation still uses Small.")
    assert overlay.width() > narrow


# -------------------------------------------------------------- the Hub strip
# isHidden(), not isVisible(): the page itself is never shown in these tests, so
# isVisible() is False for every child regardless of the strip's own state.
def test_status_strip_is_hidden_until_something_is_pending(page):
    assert page.status.isHidden() is True
    assert page.status.text() == ""


def test_status_strip_shows_and_hides(page):
    page.set_status("Loading Medium…")
    assert page.status.text() == "Loading Medium…"
    assert page.status.isHidden() is False
    page.set_status("")
    assert page.status.isHidden() is True


def test_status_strip_treats_none_as_clear(page):
    page.set_status("Loading Medium…")
    page.set_status(None)
    assert page.status.isHidden() is True


# ----------------------------------------------------------- apply debouncing
def test_a_burst_of_changes_still_applies_within_one_delay(page, monkeypatch):
    """QTimer.start() RESTARTS a timer. Re-arming it on every change let a user
    working down the page push the apply back indefinitely — the "few seconds"
    from the report. A running timer must be left to run out."""
    page.sound_effects.setChecked(False)
    assert page._apply_timer.isActive()
    first_remaining = page._apply_timer.remainingTime()

    # More changes arrive while the first is still pending.
    page.strip_discourse.setChecked(False)
    page.show_pill.setChecked(False)

    assert page._apply_timer.remainingTime() <= first_remaining, \
        "the apply was pushed further away by later changes"


def test_the_apply_covers_every_change_made_during_the_burst(page, tmp_path):
    """One apply for the whole burst is fine — apply_settings re-reads the
    WHOLE config, and each change is persisted the moment it is made."""
    page.sound_effects.setChecked(False)
    page.strip_discourse.setChecked(False)
    page._flush_apply()

    assert page.applies == [1]                     # coalesced into one apply
    on_disk = Config(path=tmp_path / "config.json")
    assert on_disk.get("sound_effects") is False
    assert on_disk.get("strip_discourse_fillers") is False
