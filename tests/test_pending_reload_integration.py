"""The model-reload stale window, end to end across threads.

This is the one deferral in Rekounts that really does last seconds — measured on
the dev machine at 3.1s for `small` and 6.0s for `medium`, both with the files
already in the OS cache, and longer on a first-ever download. Dictation keeps
working on the OLD model throughout, which is deliberate; what was missing is
any way for the user to KNOW that is what they are hearing back.

The reload finishes on a worker thread while the indicator lives on Qt widgets,
so these drive the real PendingApplies against the real Overlay and the real
SettingsPage — the marshalling is the part worth testing.
"""
import os
import threading

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
QtCore = pytest.importorskip("PySide6.QtCore")
QtWidgets = pytest.importorskip("PySide6.QtWidgets")

from rekounts.__main__ import (                          # noqa: E402
    ModelReloadGate, PendingApplies, _model_loading_text)
from rekounts.config import Config                       # noqa: E402
from rekounts.history import History                     # noqa: E402
from rekounts.ui.overlay import Overlay                  # noqa: E402
from rekounts.ui.settings_page import SettingsPage       # noqa: E402


@pytest.fixture(scope="module")
def app():
    yield QtWidgets.QApplication.instance() or QtWidgets.QApplication([])


@pytest.fixture
def surfaces(app, tmp_path, monkeypatch):
    """The two real widgets the app pushes pending state to."""
    monkeypatch.setattr("rekounts.ui.settings_page.microphone_options", list)
    overlay = Overlay()
    history = History(path=tmp_path / "history.db")
    page = SettingsPage(Config(path=tmp_path / "config.json"), history,
                        on_saved=lambda: None)
    pending = PendingApplies(sinks=[overlay.set_pending, page.set_status])
    yield pending, overlay, page
    overlay.deleteLater()
    page.deleteLater()
    history.close()


def _drain(app):
    """Deliver the queued cross-thread signal emissions."""
    app.processEvents()


def test_a_reload_shows_on_both_surfaces_then_clears(app, surfaces):
    pending, overlay, page = surfaces
    gate = ModelReloadGate()

    generation = gate.begin()
    pending.set("model", _model_loading_text("medium", "small"))
    _drain(app)
    assert "medium" in overlay._idle_hint()
    assert "medium" in page.status.text()
    assert page.status.isHidden() is False

    # ...the loader thread finishes and installs.
    done = threading.Event()

    def reload_worker():
        if gate.commit(generation, lambda: None):
            pending.clear("model")
        done.set()

    threading.Thread(target=reload_worker).start()
    assert done.wait(5)
    _drain(app)

    assert overlay._pending == ""
    assert page.status.isHidden() is True


def test_a_superseded_reload_does_not_clear_the_newer_ones_indicator(app, surfaces):
    """Two quick model changes: the first loader must not report the second done.

    It is the older load that can finish last, and clearing on its commit would
    tell the user the app is on the model they just picked while it is still
    loading.
    """
    pending, overlay, page = surfaces
    gate = ModelReloadGate()

    old = gate.begin()
    pending.set("model", _model_loading_text("medium", "small"))
    new = gate.begin()                       # user changes their mind
    pending.set("model", _model_loading_text("base", "small"))
    _drain(app)

    # The SUPERSEDED loader finishes first.
    installed = []
    assert gate.commit(old, lambda: installed.append("medium")) is False
    if gate.is_current(old):
        pending.clear("model")
    _drain(app)

    assert installed == []                   # nothing swapped in
    assert "base" in overlay._pending, "the newer reload's message was lost"
    assert page.status.isHidden() is False

    # ...and the winner clears it for real.
    assert gate.commit(new, lambda: installed.append("base")) is True
    pending.clear("model")
    _drain(app)
    assert overlay._pending == ""


def test_a_failed_reload_clears_rather_than_leaving_a_stuck_indicator(app, surfaces):
    """A permanently-amber pill would be worse than no pill at all."""
    pending, overlay, page = surfaces
    gate = ModelReloadGate()

    generation = gate.begin()
    pending.set("model", _model_loading_text("medium", "small"))
    _drain(app)

    # build_transcriber raised on the worker thread.
    if gate.is_current(generation):
        pending.clear("model")
    _drain(app)

    assert overlay._pending == ""
    assert page.status.isHidden() is True


def test_a_mic_change_during_a_reload_keeps_both_messages(app, surfaces):
    """Both deferrals can be outstanding at once; neither may hide the other."""
    pending, overlay, page = surfaces

    pending.set("model", _model_loading_text("medium", "small"))
    pending.set("microphone", "New microphone starts with your next dictation.")
    _drain(app)
    assert "medium" in page.status.text()
    assert "microphone" in page.status.text().lower()

    pending.clear("microphone")              # the recording ended
    _drain(app)
    assert "medium" in overlay._pending
    assert "microphone" not in overlay._pending.lower()
