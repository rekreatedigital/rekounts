"""The mouse wheel must scroll the page, never edit the page.

The Settings page is ~2100px of content in a ~500px viewport, so it cannot be
read without scrolling. Every one of these tests is a real user gesture: pointer
resting on a control, one notch of the wheel, while reading down the page.

Before the guard, each of those notches silently rewrote a setting and fired the
live-apply — which rebuilds the text pipeline, resyncs the microphone and can cut
short a dictation that is in flight. That is the bug these tests pin down.
"""
import os

import pytest

from rekounts.config import Config

# Offscreen so the suite stays headless and never pops a real window.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
QtCore = pytest.importorskip("PySide6.QtCore")
QtGui = pytest.importorskip("PySide6.QtGui")
QtWidgets = pytest.importorskip("PySide6.QtWidgets")

from rekounts.ui.settings_page import SettingsPage  # noqa: E402
from rekounts.ui.wheel_guard import (  # noqa: E402
    is_guarded, wheel_hungry_children)

FAKE_MICS = [("Microphone (ME6S)", "Microphone (ME6S)"),
             ("EMEET SmartCam", "EMEET SmartCam")]

# One notch down, one notch up — the bug fired in both directions.
NOTCH_DOWN, NOTCH_UP = -120, 120

# Every instant-apply value control on the page, with the config key it writes.
# Named rather than discovered, so a control that stops being reachable through
# its attribute is a loud failure instead of a silently shrunken test.
CONTROLS = (
    ("language", "language"),
    ("model", "model"),
    ("device", "device"),
    ("mic", "microphone"),
    ("sound_volume", "sound_volume"),
    ("insertion", "insertion_mode"),
    ("max_minutes", "max_recording_seconds"),
)


@pytest.fixture(scope="module")
def app():
    yield QtWidgets.QApplication.instance() or QtWidgets.QApplication([])


@pytest.fixture
def page(app, tmp_path, monkeypatch):
    """A shown, realistically-sized Settings page with a counting apply callback."""
    monkeypatch.setattr("rekounts.ui.settings_page.microphone_options",
                        lambda: list(FAKE_MICS))
    cfg = Config(path=tmp_path / "config.json")
    applies = []
    p = SettingsPage(cfg, None, on_saved=lambda: applies.append(1))
    p.resize(760, 558)          # the Hub's real page size: content overflows
    p.show()
    app.processEvents()
    p.cfg = cfg
    p.applies = applies
    yield p
    p.deleteLater()


def wheel(widget, delta):
    """One wheel notch delivered where the pointer is: on top of `widget`."""
    centre = widget.rect().center()
    return QtGui.QWheelEvent(
        QtCore.QPointF(centre), QtCore.QPointF(widget.mapToGlobal(centre)),
        QtCore.QPoint(0, delta), QtCore.QPoint(0, delta),
        QtCore.Qt.NoButton, QtCore.Qt.NoModifier, QtCore.Qt.NoScrollPhase, False)


def scroll_area(page):
    return page.findChild(QtWidgets.QScrollArea)


def spin(page, widget, delta):
    """Send one notch and settle any apply it may have scheduled."""
    QtWidgets.QApplication.sendEvent(widget, wheel(widget, delta))
    if page._apply_timer.isActive():
        page._flush_apply()
    QtWidgets.QApplication.instance().processEvents()


def arm(page, control, delta):
    """Park `control` where the tested direction can actually move it.

    A dropdown already sitting on its first entry cannot scroll up, so testing
    it there would prove nothing and quietly pass whether or not the bug exists.
    Defaults put device, microphone and insertion mode on entry 0.
    """
    if isinstance(control, QtWidgets.QComboBox):
        last = control.count() - 1
        at_end = control.currentIndex() >= last if delta < 0 \
            else control.currentIndex() <= 0
        if at_end:
            control.setCurrentIndex(0 if delta < 0 else last)
    else:                                       # QSpinBox: same idea, on value
        at_end = control.value() <= control.minimum() if delta < 0 \
            else control.value() >= control.maximum()
        if at_end:
            control.setValue(control.minimum() if delta > 0 else control.maximum())
    # That deliberate change is not what we are measuring — settle and forget it.
    page._flush_apply()
    page.applies.clear()


# ------------------------------------------------- the page needs scrolling
def test_the_settings_page_really_does_overflow_its_viewport(page):
    # Everything below is only a bug because the page must be scrolled to read.
    bar = scroll_area(page).verticalScrollBar()
    assert bar.maximum() > 0
    assert scroll_area(page).widget().height() > scroll_area(page).viewport().height()


# ----------------------------------------------------- no phantom changes
@pytest.mark.parametrize("attr,key", CONTROLS)
@pytest.mark.parametrize("delta", [NOTCH_DOWN, NOTCH_UP],
                         ids=["scroll-down", "scroll-up"])
def test_wheel_over_a_control_changes_nothing(page, attr, key, delta):
    control = getattr(page, attr)
    arm(page, control, delta)
    before = page.cfg.get(key)

    spin(page, control, delta)

    assert page.cfg.get(key) == before, (
        f"one wheel notch over “{attr}” rewrote {key}: "
        f"{before!r} -> {page.cfg.get(key)!r}")
    assert page.applies == [], (
        f"one wheel notch over “{attr}” fired {len(page.applies)} live-applies")


def test_reading_down_the_whole_page_changes_nothing(page):
    """The actual gesture: several notches while the pointer drifts over rows."""
    for attr, _ in CONTROLS:                    # start everything mid-range
        arm(page, getattr(page, attr), NOTCH_UP)
    before = {key: page.cfg.get(key) for _, key in CONTROLS}
    for attr, _ in CONTROLS:
        for delta in (NOTCH_DOWN, NOTCH_DOWN, NOTCH_UP):
            spin(page, getattr(page, attr), delta)
    assert {key: page.cfg.get(key) for _, key in CONTROLS} == before
    assert page.applies == []


# --------------------------------------------------- ...the page scrolls
@pytest.mark.parametrize("attr,_key", CONTROLS)
def test_wheel_over_a_control_scrolls_the_page_instead(page, attr, _key):
    """The notch is not swallowed — it does what the user meant it to do.

    Qt only walks the parent chain for *spontaneous* wheel events, so a guard
    that merely ignores the event leaves a synthesised one (and, in the report,
    a real one over a control that had already eaten it) going nowhere. The
    guard hands the notch to the scroll area itself, which is why this can be
    asserted at all.
    """
    bar = scroll_area(page).verticalScrollBar()
    bar.setValue(0)

    spin(page, getattr(page, attr), NOTCH_DOWN)

    assert bar.value() > 0, f"wheel over “{attr}” scrolled nothing"


def test_wheel_up_scrolls_back(page):
    bar = scroll_area(page).verticalScrollBar()
    bar.setValue(bar.maximum())
    spin(page, page.device, NOTCH_UP)
    assert bar.value() < bar.maximum()


def test_a_real_propagating_wheel_scrolls_exactly_one_notch(page):
    """The path a wheel takes on the user's actual desk, walked by hand.

    A synthesised event is delivered to one widget and stops there; a real one
    is spontaneous, so Qt keeps offering it to each parent in turn until someone
    accepts. That second path is the one that can double-scroll — the guard
    delivers the notch to the scroll area itself, and if it then let the event
    travel on, Qt would hand the very same notch to that same scroll area again.

    So: replay Qt's walk. The page must move by exactly one notch, not two.
    """
    area = scroll_area(page)
    bar = area.verticalScrollBar()
    bar.setValue(0)
    viewport = area.viewport()
    QtWidgets.QApplication.sendEvent(viewport, wheel(viewport, NOTCH_DOWN))
    one_notch = bar.value()
    assert one_notch > 0

    bar.setValue(0)
    widget, event = page.device, wheel(page.device, NOTCH_DOWN)
    while widget is not None:                   # Qt's spontaneous-wheel walk
        event.ignore()
        QtWidgets.QApplication.sendEvent(widget, event)
        if event.isAccepted() or widget.isWindow():
            break
        widget = widget.parentWidget()
    QtWidgets.QApplication.instance().processEvents()

    assert bar.value() == one_notch, (
        f"the page moved {bar.value()}px for one notch, expected {one_notch}px")
    assert page.cfg.get("device") == "cpu"      # and still changed nothing


def test_one_notch_scrolls_the_page_exactly_once(page):
    """Delivering the event ourselves must not double up with Qt's own walk."""
    bar = scroll_area(page).verticalScrollBar()
    bar.setValue(0)
    # A notch aimed at the viewport is the reference: one notch, one page step.
    viewport = scroll_area(page).viewport()
    QtWidgets.QApplication.sendEvent(viewport, wheel(viewport, NOTCH_DOWN))
    expected = bar.value()

    bar.setValue(0)
    spin(page, page.device, NOTCH_DOWN)
    assert bar.value() == expected


# ------------------------------------------------------- structural cover
def test_every_value_control_on_the_settings_page_is_guarded(page):
    """The point of the guard living in SettingsRow: a new row cannot forget it.

    If this fails, someone added a control to the Settings page through a path
    that skips SettingsRow — call ``guard_wheel()`` on it.
    """
    controls = wheel_hungry_children(page)
    assert controls, "no value controls found — the sweep is looking in the wrong place"
    unguarded = [c for c in controls if not is_guarded(c)]
    assert unguarded == [], (
        "unguarded wheel controls: "
        f"{[type(c).__name__ + '/' + (c.objectName() or '?') for c in unguarded]}")


def test_a_control_added_through_a_plain_row_is_guarded_automatically(page):
    """Adding a combo to the page is safe by default — that is the whole design."""
    from rekounts.ui.settings_page import SettingsRow

    box = QtWidgets.QComboBox()
    box.addItems(["one", "two", "three"])
    row = SettingsRow("A brand new setting", box)
    assert is_guarded(box)
    row.deleteLater()


def test_the_guard_leaves_the_keyboard_alone(page):
    """Blocking the wheel must not make a control unusable — arrows still work."""
    page.device.setFocus()
    before = page.device.currentIndex()
    QtWidgets.QApplication.sendEvent(
        page.device,
        QtGui.QKeyEvent(QtCore.QEvent.KeyPress, QtCore.Qt.Key_Down,
                        QtCore.Qt.NoModifier))
    assert page.device.currentIndex() != before
    assert page.cfg.get("device") == page.device.currentData()


def test_no_hub_page_has_an_unguarded_wheel_control(app, tmp_path, monkeypatch):
    """Covers the pages this fix did not have to touch — and the next one added.

    Dictation and Dictionary are scroll areas too; today they hold nothing that
    reacts to the wheel. The day one of them grows a dropdown, this fails.
    """
    monkeypatch.setattr("rekounts.ui.settings_page.microphone_options",
                        lambda: list(FAKE_MICS))
    from rekounts.history import History
    from rekounts.ui.dashboard import Dashboard

    cfg = Config(path=tmp_path / "config.json")
    history = History(path=tmp_path / "history.db")
    try:
        hub = Dashboard(cfg, history)
        hub.resize(1000, 640)
        app.processEvents()
        unguarded = [c for c in wheel_hungry_children(hub) if not is_guarded(c)]
        assert unguarded == [], (
            "unguarded wheel controls in the Hub: "
            f"{[type(c).__name__ for c in unguarded]} — call guard_wheel() on them")
        hub.deleteLater()
    finally:
        history.close()
