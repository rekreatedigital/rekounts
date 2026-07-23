"""Tests for the monochrome dictation pill overlay.

Split in two: pure geometry helpers (no Qt runtime needed) and widget-behavior
tests that spin up an offscreen QApplication so they run headless in CI.
"""
import os

import pytest

# Pure helpers import cleanly (PySide6 must be importable, but no display needed).
from rekounts.ui.overlay import bottom_center_xy, pick_screen_index


# --------------------------------------------------------------- pure helpers
def test_pick_screen_index_picks_containing_rect():
    rects = [(0, 0, 1920, 1080), (1920, 0, 1920, 1080)]
    assert pick_screen_index(10, 10, rects) == 0
    assert pick_screen_index(2000, 500, rects) == 1


def test_pick_screen_index_falls_back_to_default():
    rects = [(0, 0, 100, 100)]
    assert pick_screen_index(500, 500, rects, default=0) == 0
    assert pick_screen_index(500, 500, rects, default=7) == 7


def test_pick_screen_index_edges_are_half_open():
    rects = [(0, 0, 100, 100), (100, 0, 100, 100)]
    # right/bottom edge belongs to the next screen, not this one
    assert pick_screen_index(100, 0, rects) == 1
    assert pick_screen_index(99, 0, rects) == 0


def test_bottom_center_xy_centers_and_lifts_off_bottom():
    x, y = bottom_center_xy(0, 0, 1920, 1080, 200, 40, margin=52)
    assert x == (1920 - 200) // 2
    assert y == 1080 - 40 - 52


def test_bottom_center_xy_respects_screen_origin():
    x, y = bottom_center_xy(1920, 0, 1920, 1080, 100, 30, margin=50)
    assert x == 1920 + (1920 - 100) // 2
    assert y == 0 + 1080 - 30 - 50


def test_default_bottom_margin_hugs_the_taskbar():
    from rekounts.ui.overlay import _BOTTOM_MARGIN
    # Small margin so the pill sits just above the taskbar, not floating ~100px up.
    assert _BOTTOM_MARGIN <= 12
    # Omitting margin uses that module default (availableGeometry excludes taskbar).
    _, y = bottom_center_xy(0, 0, 1920, 1080, 200, 40)
    assert y == 1080 - 40 - _BOTTOM_MARGIN


# --------------------------------------------------------- widget behavior
# Offscreen so the suite stays headless and never pops a real window.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
QtWidgets = pytest.importorskip("PySide6.QtWidgets")
QtCore = pytest.importorskip("PySide6.QtCore")
from rekounts.ui.overlay import (  # noqa: E402  (after importorskip)
    _REC_H, _REC_W, Overlay)


@pytest.fixture(scope="module")
def app():
    inst = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    yield inst


@pytest.fixture
def overlay(app):
    o = Overlay()
    yield o
    o.hide()
    o.deleteLater()


class _FakeMouse:
    """Minimal stand-in for QMouseEvent exposing position()."""
    def __init__(self, x, y):
        self._p = QtCore.QPointF(x, y)

    def position(self):
        return self._p


def test_recording_starts_animation_and_sizes_to_oblong(overlay):
    overlay.set_state("recording")
    assert overlay._state == "recording"
    assert overlay._anim.isActive()
    assert (overlay.width(), overlay.height()) == (_REC_W, _REC_H)


def test_processing_animates_then_idle_stops(overlay):
    overlay.set_state("processing")
    assert overlay._anim.isActive()
    overlay.set_state("idle")
    assert overlay._state == "idle"
    assert not overlay._anim.isActive()


def test_unknown_state_is_ignored(overlay):
    overlay.set_state("recording")
    overlay.set_state("bogus")
    assert overlay._state == "recording"


def test_level_provider_polled_while_recording(overlay):
    overlay.level_provider = lambda: 0.1
    overlay.set_state("recording")
    overlay._tick()
    # level is normalized as clamp(level * 4) -> 0.4 lands at the end of the deque
    assert overlay._levels[-1] == pytest.approx(0.4)


def test_level_provider_errors_are_swallowed(overlay):
    def boom():
        raise RuntimeError("mic exploded")

    overlay.level_provider = boom
    overlay.set_state("recording")
    overlay._tick()  # must not raise
    assert overlay._levels[-1] == 0.0


def test_hotkey_label_appears_in_hints(overlay):
    overlay.set_hotkey_label("Ctrl+Q")
    assert "Ctrl+Q" in overlay._idle_hint()
    assert "Ctrl+Q" in overlay._recording_hint()


def test_finish_and_cancel_buttons_fire_callbacks(overlay):
    fired = []
    overlay.on_cancel = lambda: fired.append("cancel")
    overlay.on_finish = lambda: fired.append("finish")
    overlay.set_state("recording")
    overlay.grab()  # trigger a paint so the button hit-rects are populated

    overlay.mousePressEvent(_FakeMouse(overlay._cancel_rect.center().x(),
                                       overlay._cancel_rect.center().y()))
    overlay.mousePressEvent(_FakeMouse(overlay._finish_rect.center().x(),
                                       overlay._finish_rect.center().y()))
    assert fired == ["cancel", "finish"]


def test_clicking_empty_area_fires_nothing(overlay):
    fired = []
    overlay.on_cancel = lambda: fired.append("cancel")
    overlay.on_finish = lambda: fired.append("finish")
    overlay.set_state("recording")
    overlay.grab()
    # dead center is the waveform, between the two buttons
    overlay.mousePressEvent(_FakeMouse(overlay.width() / 2, overlay.height() / 2))
    assert fired == []


def test_clicks_ignored_outside_recording(overlay):
    fired = []
    overlay.on_finish = lambda: fired.append("finish")
    overlay.set_state("idle")
    overlay.mousePressEvent(_FakeMouse(1, 1))
    assert fired == []


def test_does_not_accept_focus(overlay):
    flags = overlay.windowFlags()
    assert flags & QtCore.Qt.WindowDoesNotAcceptFocus
    assert overlay.testAttribute(QtCore.Qt.WA_ShowWithoutActivating)


def test_disable_hides_and_enable_restores(overlay):
    overlay.set_state("recording")
    overlay.set_pill_enabled(False)
    assert not overlay.isVisible()
    assert not overlay._anim.isActive()
    overlay.set_pill_enabled(True)
    assert overlay.isVisible()


def test_hide_shim_stops_timers(overlay):
    overlay.set_state("recording")
    overlay.hide_overlay()
    assert not overlay.isVisible()
    assert not overlay._anim.isActive()
    assert not overlay._follow.isActive()


def test_show_bottom_center_shim_enters_recording(overlay):
    overlay.show_bottom_center()
    assert overlay._state == "recording"


# --------------------------------------------------------------- idle opacity
# Qt stores window opacity as an 8-bit value, so a set 0.5 reads back as 127/255
# (~0.498); abs=0.01 absorbs that ±1/255 quantization while still separating the
# dimmed idle level from full opacity.
_OPACITY_TOL = 0.01


def test_idle_is_dimmed_active_states_are_full_opacity(overlay):
    from rekounts.ui.overlay import _IDLE_OPACITY
    overlay.set_state("idle")
    assert overlay.windowOpacity() == pytest.approx(_IDLE_OPACITY, abs=_OPACITY_TOL)
    overlay.set_state("recording")
    assert overlay.windowOpacity() == pytest.approx(1.0, abs=_OPACITY_TOL)
    overlay.set_state("processing")
    assert overlay.windowOpacity() == pytest.approx(1.0, abs=_OPACITY_TOL)


def test_hover_restores_opacity_then_leave_re_dims(overlay):
    from rekounts.ui.overlay import _IDLE_OPACITY
    overlay.set_state("idle")
    assert overlay.windowOpacity() == pytest.approx(_IDLE_OPACITY, abs=_OPACITY_TOL)
    overlay.enterEvent(None)                       # hover -> readable
    assert overlay.windowOpacity() == pytest.approx(1.0, abs=_OPACITY_TOL)
    overlay.leaveEvent(None)                       # leave -> fades back
    assert overlay.windowOpacity() == pytest.approx(_IDLE_OPACITY, abs=_OPACITY_TOL)
