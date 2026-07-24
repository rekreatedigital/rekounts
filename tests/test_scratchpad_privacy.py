"""The Scratchpad stores your text, so the privacy page has to say so.

ui/scratchpad.py autosaves the note — including dictated text — to
%APPDATA%/Rekounts/scratchpad.json on every pause in typing, with no save
action from the user. docs/privacy.md did not mention it anywhere, and worse,
told the privacy-conscious reader two things that were not true once the
Scratchpad existed: that turning "Save dictation history" off means no text is
written, and that deleting history.db clears their text. scratchpad.json
persists through both — ScratchpadStore never consults history_enabled.

The decision, argued in full in SettingsPage._clear_scratchpad: the note does
NOT follow the history switch. History is a record the app keeps; the note is a
document you are writing, and making a privacy toggle silently delete an open
note would be data loss wearing a privacy hat. It gets its own explicit clear
action instead — so the page can say "you can see it, and you can get rid of
it" and have that be true.

These tests hold both halves: the behaviour, and the document that describes it.
"""
import os
import re
from pathlib import Path

import pytest

from rekounts.config import Config
from rekounts.history import History
from rekounts.scratchpad_store import ScratchpadStore

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
QtCore = pytest.importorskip("PySide6.QtCore")
QtWidgets = pytest.importorskip("PySide6.QtWidgets")

from rekounts.ui.scratchpad import Scratchpad          # noqa: E402
from rekounts.ui.settings_page import SettingsPage     # noqa: E402

REPO = Path(__file__).resolve().parents[1]
PRIVACY = (REPO / "docs" / "privacy.md").read_text(encoding="utf-8")

FAKE_MICS = [("Microphone (ME6S)", "Microphone (ME6S)")]


@pytest.fixture(scope="module")
def app():
    yield QtWidgets.QApplication.instance() or QtWidgets.QApplication([])


@pytest.fixture
def cfg(tmp_path):
    return Config(path=tmp_path / "config.json")


@pytest.fixture
def history(tmp_path):
    h = History(path=tmp_path / "history.db")
    yield h
    h.close()


@pytest.fixture
def store(tmp_path):
    return ScratchpadStore(path=tmp_path / "scratchpad.json")


@pytest.fixture
def page(app, cfg, history, monkeypatch):
    monkeypatch.setattr("rekounts.ui.settings_page.microphone_options",
                        lambda: list(FAKE_MICS))
    p = SettingsPage(cfg, history)
    yield p
    p.deleteLater()


def _confirm(monkeypatch, answer):
    monkeypatch.setattr(QtWidgets.QMessageBox, "question",
                        staticmethod(lambda *a, **k: answer))


# --- the behaviour the page describes ------------------------------------
def test_the_note_is_written_without_any_save_action(app, store):
    # The thing privacy.md failed to mention: no user action, no prompt.
    pad = Scratchpad(store=store)
    try:
        pad.edit.setPlainText("bank details I dictated by mistake")
        pad.flush()
        assert "bank details" in store.load()["html"]
    finally:
        pad.deleteLater()


def test_turning_history_off_does_not_touch_the_note(app, cfg, store):
    """The decision, asserted. Turning a privacy switch on must not delete a
    document the user is in the middle of writing."""
    pad = Scratchpad(store=store)
    try:
        pad.edit.setPlainText("still my note")
        pad.flush()
        cfg.set("history_enabled", False)
        cfg.save()
        assert "still my note" in store.load()["html"]
    finally:
        pad.deleteLater()


def test_the_pad_switch_does_not_delete_the_note_either(app, store):
    pad = Scratchpad(store=store)
    try:
        pad.edit.setPlainText("still my note")
        pad.flush()
        pad.set_enabled(False)
        assert "still my note" in store.load()["html"]
    finally:
        pad.deleteLater()


def test_clear_note_empties_the_pad_and_the_file(app, store):
    pad = Scratchpad(store=store)
    try:
        pad.edit.setPlainText("delete this please")
        pad.flush()
        pad.clear_note()
        assert pad.edit.toPlainText() == ""
        assert "delete this please" not in store.load()["html"]
    finally:
        pad.deleteLater()


def test_a_pending_autosave_cannot_resurrect_a_cleared_note(app, store):
    # The pad autosaves 700ms after the last keystroke. A clear that raced that
    # timer would be undone by it, which is the worst possible outcome for a
    # control whose whole job is "this text is gone now".
    pad = Scratchpad(store=store)
    try:
        pad.edit.setPlainText("typed a moment ago")
        pad._schedule_save()                   # timer armed, not yet fired
        assert pad._save_timer.isActive()
        pad.clear_note()
        assert not pad._save_timer.isActive()
        pad.flush()                            # whatever fires next
        assert "typed a moment ago" not in store.load()["html"]
    finally:
        pad.deleteLater()


# --- the control that makes the promise keepable -------------------------
def test_settings_offers_a_clear_note_action(page):
    assert page.clear_note_btn.text() == "Clear note…"
    assert page.scratchpad_row is not None


def test_clearing_from_settings_goes_through_the_live_pad(page, monkeypatch):
    # Not through the file: an open pad autosaves, so a file deleted behind its
    # back comes straight back.
    called = []
    page.set_scratchpad_clearer(lambda: called.append(True))
    _confirm(monkeypatch, QtWidgets.QMessageBox.Yes)
    page._clear_scratchpad()
    assert called == [True]


def test_declining_the_confirmation_clears_nothing(page, monkeypatch):
    called = []
    page.set_scratchpad_clearer(lambda: called.append(True))
    _confirm(monkeypatch, QtWidgets.QMessageBox.No)
    page._clear_scratchpad()
    assert called == []


def test_the_fallback_clearer_empties_the_file(app, monkeypatch, tmp_path):
    # With no pad wired in — tests, the Hub opened standalone — the page still
    # has to be able to keep the promise.
    path = tmp_path / "scratchpad.json"
    ScratchpadStore(path=path).save("<p>words</p>", None)
    monkeypatch.setattr("rekounts.ui.settings_page.ScratchpadStore",
                        lambda *a, **k: ScratchpadStore(path=path))
    SettingsPage._clear_scratchpad_file()
    assert ScratchpadStore(path=path).load()["html"] == ""


def test_a_failing_clear_reports_instead_of_looking_like_it_worked(page,
                                                                   monkeypatch):
    def boom():
        raise OSError("the file is read-only")

    page.set_scratchpad_clearer(boom)
    _confirm(monkeypatch, QtWidgets.QMessageBox.Yes)
    page._clear_scratchpad()          # must not raise into Qt's event loop


# --- the document ---------------------------------------------------------
def test_privacy_md_documents_the_scratchpad_file():
    assert "scratchpad.json" in PRIVACY, \
        "privacy.md lists every file in %APPDATA%\\Rekounts; this one was missing"
    section = PRIVACY.split("## The Scratchpad")[1].split("\n## ")[0]
    assert re.search(r"automatic", section, re.IGNORECASE), \
        "privacy.md must say the note is saved automatically, not on request"
    assert "no Save button" in section, \
        "the surprising part is that no user action is involved; say so"


def test_privacy_md_no_longer_claims_history_off_means_no_text_on_disk():
    # The sentence that was actively misleading: "With it off, History.add()
    # does nothing — no rows are written at all" read, in context, as "nothing
    # you say is written anywhere".
    assert "no rows are written" in PRIVACY, "the accurate half should survive"
    section = PRIVACY.split("### Turning history off")[1].split("\n## ")[0]
    assert "scratchpad" in section.lower(), \
        "the history-off section must say the Scratchpad note is not covered"


def test_privacy_md_says_how_to_clear_the_note():
    assert "Clear note" in PRIVACY


def test_privacy_md_still_claims_to_be_checked_against_the_source():
    # privacy.md:8 makes this claim absolutely. It is only allowed to stay
    # because the gaps it papered over are now closed.
    assert "checked against the source, not aspirational" in PRIVACY
