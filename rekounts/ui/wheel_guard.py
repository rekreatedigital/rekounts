"""Stop the mouse wheel from changing the setting you were only trying to read.

A page taller than its viewport has to be scrolled to be read at all. Qt sends a
wheel event to the widget under the pointer, and QComboBox / QAbstractSpinBox
accept it — ``SH_ComboBox_AllowWheelScrolling`` is 1 under Fusion — so one notch
with the pointer resting on a dropdown silently changes that setting, and the
page does not even move. On a page that live-applies every change the moment it
happens, that is not a cosmetic annoyance: it rewrote a user's Processing device
mid-dictation and kicked off a model reload while the recording was in flight,
and a notch on the recording cap can end a dictation outright.

The rule this module enforces is one sentence: **on a scrollable page the wheel
belongs to the page, never to a control.** Not "unless the control has focus" —
after you pick an item the dropdown keeps focus and sits exactly under the
pointer, which is the very next place you scroll to keep reading. That
focus-gated variant leaves the most likely version of the bug wide open.
Keyboard adjustment (arrows, Page Up/Down, typing) is untouched, so every
control stays fully operable — only the gesture that means "scroll" stops
meaning "change".

Why the guard *delivers* the event instead of just ignoring it: Qt only walks up
the parent chain looking for someone to scroll when the wheel event is
**spontaneous** (it came from the platform). An ignored event that nothing
propagates is a control that swallows the notch and a page that sits still — the
same dead feeling as the bug itself, and unprovable in a test, because a
synthesised event never propagates at all. Handing the notch to the enclosing
scroll area ourselves means the page scrolls for real, and behaves the same on a
test runner as it does on the user's desk.

Adding a control to a guarded page needs no ceremony: ``SettingsRow`` guards
whatever control it is given, and ``SettingsPage`` sweeps itself once more when
it is built. ``tests/test_wheel_guard.py`` fails if any Hub page ever grows a
wheel-hungry control that neither path caught.
"""

from PySide6 import QtCore, QtGui, QtWidgets

# Widgets whose stock reaction to the wheel is to change their own VALUE.
# QScrollBar is a QAbstractSlider too, but a scrollbar reacting to the wheel is
# the whole point of a scrollbar — it is excluded below, not guarded.
WHEEL_HUNGRY = (QtWidgets.QComboBox, QtWidgets.QAbstractSpinBox,
                QtWidgets.QAbstractSlider)

# Marks a widget as already guarded, so sweeping a page twice (row-level plus
# the page-level backstop) installs one filter, not two.
_MARK = "_rekounts_wheel_guarded"


class _WheelGuard(QtCore.QObject):
    """Event filter that hands every wheel notch to the page behind the control.

    Parented to the widget it guards, so its lifetime is exactly that widget's.
    """

    def eventFilter(self, obj, event):
        if event.type() != QtCore.QEvent.Wheel:
            return False
        area = enclosing_scroll_area(obj)
        if area is not None:
            _deliver_to_page(area, obj, event)
            # We delivered it. Accepting stops Qt's own propagation walk from
            # finding the same scroll area a second time and double-scrolling.
            event.accept()
        else:
            # Nothing to scroll — refuse the value change and let Qt do whatever
            # it would have done with an unwanted event.
            event.ignore()
        return True     # either way the control never sees it


def enclosing_scroll_area(widget):
    """The scrollable area this widget sits inside, or None."""
    parent = widget.parentWidget()
    while parent is not None:
        if isinstance(parent, QtWidgets.QAbstractScrollArea):
            return parent
        parent = parent.parentWidget()
    return None


def _deliver_to_page(area, obj, event):
    """Re-aim one wheel notch at the scroll area's viewport."""
    viewport = area.viewport()
    forwarded = QtGui.QWheelEvent(
        QtCore.QPointF(obj.mapTo(viewport, event.position().toPoint())),
        event.globalPosition(), event.pixelDelta(), event.angleDelta(),
        event.buttons(), event.modifiers(), event.phase(), event.inverted())
    QtWidgets.QApplication.sendEvent(viewport, forwarded)


def is_guarded(widget) -> bool:
    """True if `widget` will hand the wheel to its page instead of eating it."""
    return bool(widget.property(_MARK))


def wheel_hungry_children(widget):
    """Every control under `widget` (including itself) that eats wheel events."""
    found = []
    if isinstance(widget, WHEEL_HUNGRY):
        found.append(widget)
    found.extend(w for w in widget.findChildren(QtWidgets.QWidget)
                 if isinstance(w, WHEEL_HUNGRY))
    return [w for w in found if not isinstance(w, QtWidgets.QScrollBar)]


def guard_wheel(widget):
    """Make `widget` and every value control inside it leave the wheel alone.

    Safe to call repeatedly and on widgets that contain nothing to guard, so it
    can sit unconditionally at the end of a row or page constructor.
    """
    for control in wheel_hungry_children(widget):
        if is_guarded(control):
            continue
        control.setProperty(_MARK, True)
        # A wheel passing over a control must not hand it the keyboard focus
        # either — WheelFocus is the other half of the same mistake.
        if control.focusPolicy() == QtCore.Qt.WheelFocus:
            control.setFocusPolicy(QtCore.Qt.StrongFocus)
        control.installEventFilter(_WheelGuard(control))
