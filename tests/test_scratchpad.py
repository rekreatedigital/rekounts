"""The Scratchpad widget and the dictation routing that feeds it.

Split the same way tests/test_overlay.py is: pure geometry/text helpers first
(no Qt runtime needed), then widget behavior against an offscreen QApplication
so the suite stays headless and never pops a real window.
"""
import os

import pytest

# Pure helpers import cleanly (PySide6 must be importable, no display needed).
from rekounts.ui.scratchpad import (MIN_H, MIN_W, clamp_to_screens, resize_edge,
                                    spaced_append)


# --------------------------------------------------------------- resize edges
def test_resize_edge_names_each_side():
    assert resize_edge(2, 50, 200, 100, 8) == "l"
    assert resize_edge(198, 50, 200, 100, 8) == "r"
    assert resize_edge(100, 2, 200, 100, 8) == "t"
    assert resize_edge(100, 98, 200, 100, 8) == "b"


def test_resize_edge_names_each_corner():
    assert resize_edge(1, 1, 200, 100, 8) == "tl"
    assert resize_edge(199, 1, 200, 100, 8) == "tr"
    assert resize_edge(1, 99, 200, 100, 8) == "bl"
    assert resize_edge(199, 99, 200, 100, 8) == "br"


def test_resize_edge_is_empty_in_the_middle():
    assert resize_edge(100, 50, 200, 100, 8) == ""


def test_resize_edge_rejects_points_outside_the_box():
    assert resize_edge(-1, 50, 200, 100, 8) == ""
    assert resize_edge(200, 50, 200, 100, 8) == ""
    assert resize_edge(50, 100, 200, 100, 8) == ""


def test_resize_edge_degenerate_inputs_are_safe():
    assert resize_edge(0, 0, 0, 0, 8) == ""
    assert resize_edge(0, 0, 100, 100, 0) == ""


# ------------------------------------------------------------------ clamping
_SCREENS = [(0, 0, 1920, 1080)]


def test_geometry_on_screen_is_left_alone():
    assert clamp_to_screens([100, 100, 300, 400], _SCREENS) == [100, 100, 300, 400]


def test_geometry_on_an_unplugged_monitor_is_recovered():
    """A note saved on a second screen must not reopen where nobody can see it."""
    result = clamp_to_screens([3000, 200, 300, 400], _SCREENS)
    assert result != [3000, 200, 300, 400]
    x, y, w, h = result
    assert 0 <= x < 1920 and 0 <= y < 1080
    assert (w, h) == (300, 400)


def test_partially_offscreen_is_still_reachable_and_kept():
    # Overlaps the desktop, so the user can still grab it — leave it be.
    assert clamp_to_screens([-50, 10, 300, 400], _SCREENS) == [-50, 10, 300, 400]


def test_a_note_exactly_flush_past_the_edge_is_recovered():
    """Sharing only an edge is not being visible."""
    assert clamp_to_screens([1920, 0, 300, 400], _SCREENS) != [1920, 0, 300, 400]


def test_clamping_enforces_the_minimum_size():
    x, y, w, h = clamp_to_screens([10, 10, 5, 5], _SCREENS)
    assert (w, h) == (MIN_W, MIN_H)


def test_clamping_survives_having_no_screens():
    assert clamp_to_screens([10, 20, 300, 400], []) == [10, 20, 300, 400]


def test_clamping_rejects_a_malformed_rect():
    assert clamp_to_screens(None, _SCREENS) is None
    assert clamp_to_screens([1, 2, 3], _SCREENS) is None


# ------------------------------------------------------------ append spacing
def test_append_separates_from_a_preceding_word():
    assert spaced_append("o", "world") == " world"


def test_append_does_not_double_an_existing_space():
    assert spaced_append(" ", "world") == "world"


def test_append_respects_a_chunk_that_brings_its_own_space():
    """Live typing emits ' word'; adding another space would double it."""
    assert spaced_append("o", " world") == " world"


def test_append_at_the_start_of_an_empty_note_adds_nothing():
    assert spaced_append("", "hello") == "hello"


def test_append_of_nothing_is_nothing():
    assert spaced_append("o", "") == ""
    assert spaced_append("o", None) == ""


# =========================================================== widget behavior
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
QtWidgets = pytest.importorskip("PySide6.QtWidgets")
QtCore = pytest.importorskip("PySide6.QtCore")
QtGui = pytest.importorskip("PySide6.QtGui")

from rekounts.scratchpad_store import ScratchpadStore  # noqa: E402
from rekounts.ui.scratchpad import (  # noqa: E402  (after importorskip)
    SHADOW, Scratchpad, ScratchpadRouter)


@pytest.fixture(scope="module")
def app():
    yield QtWidgets.QApplication.instance() or QtWidgets.QApplication([])


@pytest.fixture
def store(tmp_path):
    return ScratchpadStore(path=tmp_path / "scratchpad.json")


@pytest.fixture
def pad(app, store):
    p = Scratchpad(store=store)
    yield p
    p.hide()
    p.deleteLater()


# ------------------------------------------------------------------ chrome
def test_the_pad_is_frameless_and_translucent(pad):
    """The whole design rests on this: no OS title bar, no opaque rectangle."""
    assert pad.windowFlags() & QtCore.Qt.FramelessWindowHint
    assert pad.testAttribute(QtCore.Qt.WA_TranslucentBackground)


def test_the_pad_accepts_focus_unlike_the_pill(pad):
    """The pill must never take focus; the pad is typed into, so it must."""
    assert not (pad.windowFlags() & QtCore.Qt.WindowDoesNotAcceptFocus)


def test_window_controls_are_only_close_and_minimize(pad):
    assert pad.close_button.kind == "close"
    assert pad.minimize_button.kind == "minimize"


def test_chrome_is_invisible_at_rest_and_fades_in_on_hover(pad):
    assert pad.close_button._opacity == pytest.approx(0.0)
    pad.enterEvent(None)
    pad._fade.setCurrentTime(pad.CHROME_FADE_MS)
    assert pad.close_button._opacity == pytest.approx(1.0)
    pad.leaveEvent(None)
    pad._fade.setCurrentTime(pad.CHROME_FADE_MS)
    assert pad.close_button._opacity == pytest.approx(0.0)


def test_the_toolbar_stays_readable_at_rest(pad):
    """Unlike close/minimize, the format buttons never vanish entirely."""
    assert pad.format_buttons["bold"]._opacity >= pad.TOOLBAR_REST_OPACITY


def test_toolbar_has_the_five_text_controls_and_no_image_button(pad):
    assert set(pad.format_buttons) == {"bold", "italic", "underline",
                                       "strike", "bullets"}


def test_format_buttons_never_steal_the_caret(pad):
    """Clicking Bold has to leave focus in the note or it formats nothing."""
    for button in pad.format_buttons.values():
        assert button.focusPolicy() == QtCore.Qt.NoFocus


def test_closing_hides_rather_than_destroying(pad):
    pad.show()
    pad.close()
    assert not pad.isVisible()
    # Still a live widget the tray can reopen.
    assert pad.edit is not None


# --------------------------------------------------------------- formatting
def test_bold_applies_to_what_is_typed_next(pad):
    pad.format_buttons["bold"].setChecked(True)
    pad.edit.textCursor().insertText("loud", pad.edit.currentCharFormat())
    cursor = pad.edit.textCursor()
    cursor.movePosition(QtGui.QTextCursor.Left, QtGui.QTextCursor.KeepAnchor)
    assert cursor.charFormat().fontWeight() >= QtGui.QFont.Bold


def test_toolbar_reflects_the_format_under_the_caret(pad):
    pad.format_buttons["italic"].setChecked(True)
    pad.edit.textCursor().insertText("slanted", pad.edit.currentCharFormat())
    pad._sync_buttons()
    assert pad.format_buttons["italic"].isChecked()


def test_bullets_toggle_on_and_off(pad):
    pad.edit.setPlainText("a task")
    pad.format_buttons["bullets"].setChecked(True)
    assert pad.edit.textCursor().currentList() is not None
    pad.format_buttons["bullets"].setChecked(False)
    assert pad.edit.textCursor().currentList() is None


def test_syncing_the_toolbar_does_not_reformat_the_document(pad):
    """set_checked_silently must not loop back into an apply."""
    pad.edit.setPlainText("plain")
    pad.format_buttons["bold"].set_checked_silently(True)
    cursor = pad.edit.textCursor()
    cursor.select(QtGui.QTextCursor.Document)
    assert cursor.charFormat().fontWeight() < QtGui.QFont.Bold


# ---------------------------------------------------------------- dictation
def test_dictation_lands_in_the_note(pad):
    pad.append_dictation("hello there")
    assert "hello there" in pad.edit.toPlainText()


def test_dictation_is_separated_from_existing_text(pad):
    pad.edit.setPlainText("Hello")
    cursor = pad.edit.textCursor()
    cursor.movePosition(QtGui.QTextCursor.End)
    pad.edit.setTextCursor(cursor)
    pad.append_dictation("world")
    assert pad.edit.toPlainText() == "Hello world"


def test_dictation_inherits_the_current_formatting(pad):
    """The design brief's requirement: dictated text is plain, but it takes on
    whatever the user has switched on in the toolbar."""
    pad.format_buttons["bold"].setChecked(True)
    pad.append_dictation("emphatic")
    cursor = pad.edit.textCursor()
    cursor.movePosition(QtGui.QTextCursor.Left, QtGui.QTextCursor.KeepAnchor)
    assert cursor.charFormat().fontWeight() >= QtGui.QFont.Bold


def test_dictation_lands_at_the_caret_not_at_the_end(pad):
    pad.edit.setPlainText("start end")
    cursor = pad.edit.textCursor()
    cursor.setPosition(len("start"))
    pad.edit.setTextCursor(cursor)
    pad.append_dictation("middle")
    assert pad.edit.toPlainText() == "start middle end"


def test_empty_dictation_changes_nothing(pad):
    pad.edit.setPlainText("untouched")
    pad.append_dictation("")
    assert pad.edit.toPlainText() == "untouched"


# ------------------------------------------------------------- wants_dictation
def test_a_hidden_pad_never_claims_dictation(pad):
    assert pad.wants_dictation() is False


def test_a_focused_visible_enabled_pad_claims_dictation(pad):
    pad._shown, pad._active = True, True
    assert pad.wants_dictation() is True


def test_a_visible_but_unfocused_pad_does_not_claim_dictation(pad):
    """The whole routing rule in one assertion: focus decides, not visibility."""
    pad._shown, pad._active = True, False
    assert pad.wants_dictation() is False


def test_a_disabled_pad_never_claims_dictation(pad):
    pad._shown, pad._active = True, True
    pad.set_enabled(False)
    assert pad.wants_dictation() is False


def test_disabling_hides_an_open_pad_but_keeps_the_note(pad):
    pad.edit.setPlainText("my note")
    pad.show()
    pad.set_enabled(False)
    assert not pad.isVisible()
    assert pad.edit.toPlainText() == "my note"


def test_a_disabled_pad_refuses_to_open(pad):
    pad.set_enabled(False)
    pad.open_and_raise()
    assert not pad.isVisible()


# -------------------------------------------------------------- persistence
def test_the_note_survives_a_restart(app, store):
    first = Scratchpad(store=store)
    first.edit.setPlainText("remember this")
    first.flush()
    first.deleteLater()

    second = Scratchpad(store=store)
    try:
        assert "remember this" in second.edit.toPlainText()
    finally:
        second.deleteLater()


def test_formatting_survives_a_restart(app, store):
    first = Scratchpad(store=store)
    first.format_buttons["bold"].setChecked(True)
    first.edit.textCursor().insertText("strong", first.edit.currentCharFormat())
    first.flush()
    first.deleteLater()

    second = Scratchpad(store=store)
    try:
        cursor = second.edit.textCursor()
        cursor.movePosition(QtGui.QTextCursor.End)
        cursor.movePosition(QtGui.QTextCursor.Left, QtGui.QTextCursor.KeepAnchor)
        assert cursor.charFormat().fontWeight() >= QtGui.QFont.Bold
    finally:
        second.deleteLater()


def test_size_and_position_survive_a_restart(app, store):
    first = Scratchpad(store=store)
    first.show()
    first.setGeometry(120, 140, 400, 460)
    first.flush()
    first.hide()
    first.deleteLater()

    second = Scratchpad(store=store)
    try:
        second.show()
        assert (second.width(), second.height()) == (400, 460)
    finally:
        second.hide()
        second.deleteLater()


def test_loading_a_note_does_not_immediately_mark_it_dirty(app, store):
    store.save("<p>preexisting</p>")
    pad = Scratchpad(store=store)
    try:
        assert not pad._save_timer.isActive()
    finally:
        pad.deleteLater()


def test_hiding_flushes_a_pending_edit(pad):
    pad.show()
    pad.edit.setPlainText("typed then closed")
    assert pad._save_timer.isActive()
    pad.hide()
    assert pad.store.load()["html"]
    assert "typed then closed" in pad.store.load()["html"]


def test_a_broken_store_cannot_take_the_app_down(app, tmp_path):
    class _Exploding:
        def load(self):
            return {"html": "", "geometry": None}

        def save(self, *a, **k):
            raise OSError("the disk is on fire")

    pad = Scratchpad(store=_Exploding())
    try:
        pad.flush()          # must not raise
    finally:
        pad.deleteLater()


# ------------------------------------------------------------------ resizing
def test_the_shadow_ring_is_part_of_the_grab_band(pad):
    """The transparent margin belongs to our window either way — using it for
    resizing turns dead space into a wider, easier edge."""
    assert pad._edge_at(QtCore.QPoint(1, 1)) == "tl"
    assert pad._edge_at(QtCore.QPoint(pad.width() // 2, 1)) == "t"


def test_the_note_body_does_not_resize(pad):
    centre = QtCore.QPoint(pad.width() // 2, pad.height() // 2)
    assert pad._edge_at(centre) == ""


def test_resizing_from_the_left_never_walks_the_window_away(pad):
    """Shrinking past the minimum must pin the dragged edge, not the far one."""
    pad.show()
    pad.setGeometry(300, 300, pad.minimumWidth() + 40, 400)
    right = pad.geometry().right()
    pad._resize_edge = "l"
    pad._resize_origin = (QtCore.QRect(pad.geometry()), QtCore.QPoint(300, 300))
    pad._perform_resize(QtCore.QPoint(300 + 5000, 300))   # drag far right
    assert pad.geometry().right() == right
    assert pad.width() == pad.minimumWidth()


def test_the_minimum_size_leaves_a_usable_note(pad):
    assert pad.minimumWidth() == MIN_W + SHADOW * 2
    assert pad.minimumHeight() == MIN_H + SHADOW * 2


# ================================================================== routing
class _FakeInserter:
    def __init__(self):
        self.calls = []

    def insert(self, text):
        self.calls.append(text)
        return "pasted"


class _FakePad:
    def __init__(self, wants):
        self._wants = wants
        self.appended = []

    def wants_dictation(self):
        return self._wants

    def append_dictation(self, text):
        self.appended.append(text)


def test_router_passes_through_when_the_pad_is_not_focused():
    inserter = _FakeInserter()
    router = ScratchpadRouter(_FakePad(False), inserter)
    assert router.insert("hello") == "pasted"
    assert inserter.calls == ["hello"]


def test_router_diverts_to_the_pad_when_it_is_focused():
    inserter = _FakeInserter()
    pad = _FakePad(True)
    router = ScratchpadRouter(pad, inserter)
    assert router.insert("hello") == ScratchpadRouter.OUTCOME
    assert pad.appended == ["hello"]
    assert inserter.calls == []          # the clipboard is never touched


def test_the_routed_outcome_counts_as_delivered_in_history():
    """A dictation that landed in the pad is not a failed insertion."""
    from rekounts.controller import _insertion_succeeded
    assert _insertion_succeeded(ScratchpadRouter.OUTCOME) is True


def test_a_broken_pad_falls_back_to_normal_insertion():
    class _Broken:
        def wants_dictation(self):
            raise RuntimeError("boom")

    inserter = _FakeInserter()
    router = ScratchpadRouter(_Broken(), inserter)
    assert router.insert("hello") == "pasted"
    assert inserter.calls == ["hello"]   # the dictation is never lost


def test_router_works_against_the_real_pad(pad):
    inserter = _FakeInserter()
    router = ScratchpadRouter(pad, inserter)

    router.insert("goes to the app")
    assert inserter.calls == ["goes to the app"]

    pad._shown, pad._active = True, True
    router.insert("goes to the note")
    assert inserter.calls == ["goes to the app"]        # unchanged
    assert "goes to the note" in pad.edit.toPlainText()


def test_bullets_sit_close_to_the_left_margin(pad):
    """Qt's 40px default indent pushes bullets a third of the way across a
    ~300px note; the reference keeps them nearly flush."""
    assert pad.edit.document().indentWidth() <= 20


def test_switching_bullets_off_only_leaves_the_current_line(pad):
    """Two bulleted lines, caret on the second: the first keeps its bullet."""
    pad.edit.setPlainText("first")
    pad.format_buttons["bullets"].setChecked(True)
    cursor = pad.edit.textCursor()
    cursor.movePosition(QtGui.QTextCursor.End)
    cursor.insertBlock()
    cursor.insertText("second")
    pad.edit.setTextCursor(cursor)
    pad.format_buttons["bullets"].setChecked(False)

    doc = pad.edit.document()
    assert doc.findBlockByNumber(0).textList() is not None
    assert doc.findBlockByNumber(1).textList() is None
