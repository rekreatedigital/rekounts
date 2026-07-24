"""Minimal, monochrome, Wispr Flow-style dictation pill.

Replaces the old colorful "aurora" overlay. Four visual states:

  idle        a small charcoal pill at the bottom-center of the active monitor,
              just enough to say "dictation is active".
  idle+hover  the pill widens and shows "Hold <hotkey> to dictate".
  recording   an oblong: [x] cancel  |  live monochrome waveform  |  [check] finish.
  processing  a brief pulsing-dots "thinking" animation until back to idle.

Design rules honored here:
  * Monochrome ONLY - charcoal/near-black backgrounds, white/gray elements. No hue.
  * Idle CPU near zero - the waveform/animation timer runs ONLY while recording or
    processing; the mouse-follow timer is slow (500 ms) and only move()s when the
    target actually changes, so nothing repaints when nothing changes.
  * Never steals focus - Qt.WindowDoesNotAcceptFocus + WA_ShowWithoutActivating,
    plus WS_EX_NOACTIVATE on the native window on Windows. Clicks on the buttons
    still register without pulling focus from the app you're dictating into.
  * Multi-monitor - the pill lives on whatever monitor the mouse pointer is on.

Public interface (the conductor wires these; a parallel session emits the states):
    overlay.set_state("idle" | "recording" | "processing")   # thread-safe Qt slot
    overlay.set_hotkey_label(text)                            # thread-safe Qt slot
    overlay.level_provider          # callable -> float, polled while recording
    overlay.on_cancel / overlay.on_finish   # callables invoked on [x] / [check]
    overlay.set_pill_enabled(bool)  # runtime show/hide (config "show_pill")

show_bottom_center()/hide_overlay() remain as thin compatibility shims so the
current __main__.py keeps working until the conductor rewires the app.
"""

import math
import os
import sys
from collections import deque

from PySide6 import QtCore, QtGui, QtWidgets

# --- macOS: keep the pill visible while OTHER apps are active ---------------
# Qt.Tool windows on macOS are NSPanels with hidesOnDeactivate=YES, so the pill
# would vanish the moment another app is focused — which is ALWAYS while
# dictating. Three layers fix that, applied to both the pill and its hint:
#   1. Qt.WA_MacAlwaysShowToolWindow (documented Qt attribute; needs no pyobjc)
#   2. NSWindow collectionBehavior CanJoinAllSpaces|FullScreenAuxiliary, so the
#      pill follows the user across Spaces and over full-screen apps
#   3. NSPanel non-activating style + hidesOnDeactivate=NO, belt-and-braces
# Layer 1 is always on. Layers 2-3 poke native window state that cannot be
# verified without real hardware, so they ship behind REKOUNTS_MAC_OVERLAY_NATIVE
# (default ON, set to 0 to disable) — see MACOS-TESTING.md for the check steps.
_NS_CAN_JOIN_ALL_SPACES = 1 << 0     # NSWindowCollectionBehaviorCanJoinAllSpaces
_NS_FULLSCREEN_AUXILIARY = 1 << 8    # ...FullScreenAuxiliary
_NS_NONACTIVATING_PANEL = 1 << 7     # NSWindowStyleMaskNonactivatingPanel


def _mac_collection_behavior() -> int:
    """The collectionBehavior bits the overlay windows need (pure, testable)."""
    return _NS_CAN_JOIN_ALL_SPACES | _NS_FULLSCREEN_AUXILIARY


def _mac_native_enabled(environ=None) -> bool:
    """Whether the native (pyobjc) visibility tweaks are enabled (the flag)."""
    environ = environ if environ is not None else os.environ
    return environ.get("REKOUNTS_MAC_OVERLAY_NATIVE", "1") != "0"


def _apply_mac_tool_window_attr(widget):
    """Layer 1: ask Qt to keep this tool window visible on app deactivate."""
    if sys.platform != "darwin":
        return
    attr = getattr(QtCore.Qt, "WA_MacAlwaysShowToolWindow", None)
    if attr is not None:
        widget.setAttribute(attr, True)


def _apply_mac_panel_behavior(widget):
    """Layers 2-3: native NSWindow/NSPanel state, flag-guarded, best-effort.

    Must run AFTER the native window exists (i.e. from showEvent), because
    winId() forces window creation and the NSWindow is only reachable then.
    Every step is independent and swallowed on failure: a pyobjc quirk must
    degrade to "pill hides sometimes", never to a crash.
    """
    if sys.platform != "darwin" or not _mac_native_enabled():
        return
    try:
        # Only when Qt is actually driving Cocoa windows. Under the offscreen
        # platform (tests, CI) winId() is NOT an NSView pointer, and wrapping
        # it as one is a segfault, not an exception — no try/except saves us.
        if QtGui.QGuiApplication.platformName() != "cocoa":
            return
        import ctypes

        import objc
        view = objc.objc_object(c_void_p=ctypes.c_void_p(int(widget.winId())))
        window = view.window()
        if window is None:
            return
        try:
            window.setCollectionBehavior_(
                window.collectionBehavior() | _mac_collection_behavior())
        except Exception:
            pass
        try:
            window.setHidesOnDeactivate_(False)
        except Exception:
            pass
        try:
            # Only meaningful when Qt made the window an NSPanel (it does for
            # Qt.Tool); a plain NSWindow rejects the panel-only style bit.
            window.setStyleMask_(window.styleMask() | _NS_NONACTIVATING_PANEL)
        except Exception:
            pass
    except Exception:
        pass  # no pyobjc / restricted environment; layer 1 still applies

# --- geometry (logical px; Qt scales for DPI) ---
_IDLE_W, _IDLE_H = 98, 26
_PROC_W, _PROC_H = 98, 26
_REC_H = 40
_BTN_D = 26                       # cancel/finish circular button diameter
_PAD = 8                          # inner padding at the oblong ends
_GAP = 10                         # gap between a button and the waveform
_WAVE_W = 122
_REC_W = _PAD * 2 + _BTN_D * 2 + _GAP * 2 + _WAVE_W  # -> 208
_BOTTOM_MARGIN = 8                # px above the taskbar's top edge (availableGeometry
                                  # already excludes the taskbar, so this hugs it
                                  # without overlapping — safe with auto-hide / side
                                  # taskbars, where a taskbar-overlap z-order fight
                                  # gets flaky)
_N_BARS = 20

# When idle and unhovered the pill fades to a faint hint rather than a fixture;
# hover (and recording/processing) restore full opacity. Qt multiplies this window
# opacity with the per-pixel alpha, so the charcoal stays charcoal, just fainter.
_IDLE_OPACITY = 0.5

# --- monochrome palette (charcoal bg, white/gray elements; NO hue) ---
_BG_TOP = QtGui.QColor(34, 34, 38, 236)     # subtle top sheen
_BG_BOT = QtGui.QColor(20, 20, 23, 240)     # deep charcoal bottom
_BORDER = QtGui.QColor(255, 255, 255, 26)   # hairline
_TEXT = QtGui.QColor(214, 216, 222)
_ICON = QtGui.QColor(198, 200, 208)         # idle mic / neutral glyph
_ICON_DIM = QtGui.QColor(150, 152, 160)     # cancel glyph (recedes)
_ICON_HI = QtGui.QColor(242, 243, 247)      # hover / primary glyph
_WAVE = QtGui.QColor(226, 227, 233)
_BTN_BG = QtGui.QColor(255, 255, 255, 14)
_BTN_BG_HOVER = QtGui.QColor(255, 255, 255, 42)
# "A setting you changed hasn't landed yet." Amber reads as in-progress rather
# than as an error, and it is the one thing on the pill that is not greyscale,
# so it cannot be mistaken for part of the idle mic glyph.
_PENDING = QtGui.QColor(240, 178, 74)
_PENDING_DOT_D = 6                # diameter of the pending dot


def pick_screen_index(px, py, rects, default=0):
    """Index of the screen rect containing point (px, py), else `default`.

    Pure helper (no Qt) mirroring QGuiApplication.screenAt, so the mouse-follow
    screen-picking logic is unit-testable with injected fake screen rects.
    `rects` is a list of (x, y, w, h).
    """
    for i, (rx, ry, rw, rh) in enumerate(rects):
        if rx <= px < rx + rw and ry <= py < ry + rh:
            return i
    return default


def bottom_center_xy(ax, ay, aw, ah, w, h, margin=_BOTTOM_MARGIN):
    """Top-left (x, y) that centers a w*h box along the bottom of an available
    geometry rect (ax, ay, aw, ah), `margin` px above its bottom edge. Pure."""
    x = ax + (aw - w) // 2
    y = ay + ah - h - margin
    return x, y


class Overlay(QtWidgets.QWidget):
    # Internal signals let set_state()/set_hotkey_label()/hide be called from any
    # thread: emitting a signal hops to the GUI thread (queued) automatically.
    _cmd = QtCore.Signal(str)      # "idle" | "recording" | "processing" | "hide"
    _hk = QtCore.Signal(str)
    _pend = QtCore.Signal(str)     # pending-settings message, "" to clear

    def __init__(self):
        super().__init__(
            None,
            QtCore.Qt.FramelessWindowHint | QtCore.Qt.WindowStaysOnTopHint
            | QtCore.Qt.Tool | QtCore.Qt.WindowDoesNotAcceptFocus)
        self.setAttribute(QtCore.Qt.WA_TranslucentBackground)
        self.setAttribute(QtCore.Qt.WA_ShowWithoutActivating)
        _apply_mac_tool_window_attr(self)
        self.setMouseTracking(True)

        # --- public, set by the wirer ---
        self.level_provider = None        # callable -> float
        self.on_cancel = lambda: None
        self.on_finish = lambda: None

        # --- state ---
        self._state = "idle"
        self._enabled = True              # config "show_pill"
        self._hotkey = "F8"
        self._pending = ""                # settings change that hasn't landed yet
        self._hovered = False
        self._hover_btn = None            # None | "cancel" | "finish"
        self._levels = deque([0.0] * _N_BARS, maxlen=_N_BARS)
        self._phase = 0.0                 # drives processing dots
        self._last_xy = None              # last move() target, to skip no-op moves
        self._cancel_rect = QtCore.QRectF()
        self._finish_rect = QtCore.QRectF()

        self._hint = _HintBubble()

        # animation timer: waveform + processing dots. Runs ONLY while active.
        self._anim = QtCore.QTimer(self)
        self._anim.setInterval(40)        # ~25 fps
        self._anim.timeout.connect(self._tick)

        # mouse-follow timer: slow poll of which monitor the cursor is on.
        self._follow = QtCore.QTimer(self)
        self._follow.setInterval(500)
        self._follow.timeout.connect(self._reposition)

        self._cmd.connect(self._apply_cmd)
        self._hk.connect(self._apply_hotkey)
        self._pend.connect(self._apply_pending)

        self._resize_for_state()

    # ------------------------------------------------------------------ public
    @QtCore.Slot(str)
    def set_state(self, state):
        """Switch visual state. Thread-safe (marshals to the GUI thread)."""
        self._cmd.emit(state)

    @QtCore.Slot(str)
    def set_hotkey_label(self, text):
        """Set the hotkey shown in hint text (e.g. "F8"). Thread-safe."""
        self._hk.emit(text or "")

    @QtCore.Slot(str)
    def set_pending(self, text):
        """Show (or clear, with "") a settings change that has NOT landed yet.

        The pill is always on screen, so this is the one surface that does not
        depend on the notifications switch — the multi-second model reload used
        to be completely invisible with toasts turned off. Thread-safe.
        """
        self._pend.emit(text or "")

    @QtCore.Slot(bool)
    def set_pill_enabled(self, enabled):
        """Runtime toggle for config "show_pill". Thread-safe via _apply_cmd."""
        self._cmd.emit("enable" if enabled else "disable")

    # --- compatibility shims (old __main__ connects these via the bridge) ---
    @QtCore.Slot()
    def show_bottom_center(self):
        self._cmd.emit("recording")

    @QtCore.Slot()
    def hide_overlay(self):
        self._cmd.emit("hide")

    # -------------------------------------------------------------- internals
    @QtCore.Slot(str)
    def _apply_cmd(self, cmd):
        if cmd == "enable":
            self._enabled = True
            self._apply_state(self._state)
            return
        if cmd in ("disable", "hide"):
            if cmd == "disable":
                self._enabled = False
            self._anim.stop()
            self._follow.stop()
            self._hint.hide()
            self.hide()
            return
        if cmd in ("idle", "recording", "processing"):
            self._apply_state(cmd)

    def _apply_state(self, state):
        self._state = state
        self._hover_btn = None
        self._hint.hide()
        if state == "recording":
            self._levels.extend([0.0] * _N_BARS)
            self._phase = 0.0
            if not self._anim.isActive():
                self._anim.start()
        elif state == "processing":
            self._phase = 0.0
            if not self._anim.isActive():
                self._anim.start()
        else:  # idle
            self._anim.stop()

        if not self._enabled:
            self.hide()
            return

        self._resize_for_state()
        self._reposition()
        self._refresh_opacity()
        if not self.isVisible():
            self.show()
        self.raise_()
        if not self._follow.isActive():
            self._follow.start()
        self.update()

    def _refresh_opacity(self):
        """Fade the idle pill back when it's not being used; full opacity while
        recording/processing or while hovered (so the hint stays readable)."""
        dim = self._state == "idle" and not self._hovered
        self.setWindowOpacity(_IDLE_OPACITY if dim else 1.0)

    @QtCore.Slot(str)
    def _apply_hotkey(self, text):
        self._hotkey = text or ""
        if self._hovered:
            self._resize_for_state()
            self._reposition()
        self.update()

    @QtCore.Slot(str)
    def _apply_pending(self, text):
        if text == self._pending:
            return
        self._pending = text
        # The pending message replaces the idle hint, so the hovered pill has to
        # be re-measured for it.
        if self._hovered:
            self._resize_for_state()
            self._reposition()
        self.update()

    def _resize_for_state(self):
        if self._state == "recording":
            self.setFixedSize(_REC_W, _REC_H)
        elif self._state == "processing":
            self.setFixedSize(_PROC_W, _PROC_H)
        else:  # idle
            if self._hovered:
                fm = QtGui.QFontMetrics(self._hint_font())
                w = fm.horizontalAdvance(self._idle_hint()) + 22 + 30  # mic + pad
                self.setFixedSize(max(_IDLE_W, w), 30)
            else:
                self.setFixedSize(_IDLE_W, _IDLE_H)

    def _reposition(self):
        """Place the pill bottom-center of the monitor under the mouse pointer.
        Only calls move() when the target actually changes (no idle churn)."""
        app = QtWidgets.QApplication.instance()
        if app is None:
            return
        screens = QtGui.QGuiApplication.screens()
        if not screens:
            return
        pos = QtGui.QCursor.pos()
        rects = [(s.geometry().x(), s.geometry().y(),
                  s.geometry().width(), s.geometry().height()) for s in screens]
        idx = pick_screen_index(pos.x(), pos.y(), rects, default=0)
        avail = screens[idx].availableGeometry()
        x, y = bottom_center_xy(avail.x(), avail.y(), avail.width(),
                                avail.height(), self.width(), self.height())
        if self._last_xy != (x, y):
            self._last_xy = (x, y)
            self.move(x, y)
        if self._hint.isVisible():
            self._position_hint()

    def _tick(self):
        if self._state == "recording":
            level = 0.0
            if callable(self.level_provider):
                try:
                    level = float(self.level_provider())
                except Exception:
                    level = 0.0
            self._levels.append(max(0.0, min(1.0, level * 4.0)))
        self._phase += 0.14
        self.update()

    # ------------------------------------------------------------ interaction
    def enterEvent(self, event):
        self._hovered = True
        self._refresh_opacity()
        if self._state == "idle":
            self._resize_for_state()
            self._reposition()
        elif self._state == "recording":
            self._show_hint(self._recording_hint())
        self.update()

    def leaveEvent(self, event):
        self._hovered = False
        self._hover_btn = None
        self._refresh_opacity()
        self._hint.hide()
        if self._state == "idle":
            self._resize_for_state()
            self._reposition()
        self.update()

    def mouseMoveEvent(self, event):
        if self._state != "recording":
            return
        pos = event.position() if hasattr(event, "position") else event.localPos()
        hit = None
        if self._cancel_rect.contains(pos):
            hit = "cancel"
        elif self._finish_rect.contains(pos):
            hit = "finish"
        if hit != self._hover_btn:
            self._hover_btn = hit
            self.update()

    def mousePressEvent(self, event):
        if self._state != "recording":
            return
        pos = event.position() if hasattr(event, "position") else event.localPos()
        if self._cancel_rect.contains(pos):
            self._safe(self.on_cancel)
        elif self._finish_rect.contains(pos):
            self._safe(self.on_finish)

    @staticmethod
    def _safe(fn):
        try:
            if callable(fn):
                fn()
        except Exception:
            pass

    def showEvent(self, event):
        super().showEvent(event)
        self._apply_no_activate()
        _apply_mac_panel_behavior(self)

    def _apply_no_activate(self):
        """On Windows, add WS_EX_NOACTIVATE so clicking the pill never activates
        it (belt-and-suspenders with WindowDoesNotAcceptFocus)."""
        if sys.platform != "win32":
            return
        try:
            import ctypes
            hwnd = int(self.winId())
            GWL_EXSTYLE = -20
            WS_EX_NOACTIVATE = 0x08000000
            user32 = ctypes.windll.user32
            ex = user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
            user32.SetWindowLongW(hwnd, GWL_EXSTYLE, ex | WS_EX_NOACTIVATE)
        except Exception:
            pass  # non-Windows or restricted; the Qt flags still apply

    # ------------------------------------------------------------------ hints
    def _hint_font(self):
        f = QtGui.QFont()
        f.setPointSize(9)
        f.setWeight(QtGui.QFont.Medium)
        return f

    def _idle_hint(self):
        # A pending change is the more useful thing to say: the user just made
        # it, and it is why this dictation may not behave as they expect.
        if self._pending:
            return self._pending
        return "Hold %s to dictate" % (self._hotkey or "hotkey")

    def _recording_hint(self):
        return "Press %s or ✓ to finish and paste" % (self._hotkey or "hotkey")

    def _show_hint(self, text):
        self._hint.set_text(text)
        self._position_hint()
        self._hint.show()

    def _position_hint(self):
        self._hint.adjustSize()
        g = self.frameGeometry()
        x = g.center().x() - self._hint.width() // 2
        y = g.top() - self._hint.height() - 8
        self._hint.move(x, y)

    # ------------------------------------------------------------------ paint
    def paintEvent(self, event):
        p = QtGui.QPainter(self)
        p.setRenderHint(QtGui.QPainter.Antialiasing)
        r = QtCore.QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        radius = r.height() / 2.0

        g = QtGui.QLinearGradient(r.topLeft(), r.bottomLeft())
        g.setColorAt(0.0, _BG_TOP)
        g.setColorAt(1.0, _BG_BOT)
        p.setBrush(g)
        p.setPen(QtCore.Qt.NoPen)
        p.drawRoundedRect(r, radius, radius)
        p.setBrush(QtCore.Qt.NoBrush)
        p.setPen(QtGui.QPen(_BORDER, 1))
        p.drawRoundedRect(r, radius, radius)

        if self._state == "recording":
            self._paint_recording(p, r)
        elif self._state == "processing":
            self._paint_processing(p, r)
        else:
            self._paint_idle(p, r)
        self._draw_pending_dot(p, r)

    def _paint_idle(self, p, r):
        if self._hovered:
            p.setFont(self._hint_font())
            p.setPen(_TEXT)
            tr = r.adjusted(30, 0, -10, 0)
            self._draw_mic(p, QtCore.QPointF(r.left() + 18, r.center().y()), _ICON)
            p.drawText(tr, QtCore.Qt.AlignVCenter | QtCore.Qt.AlignLeft,
                       self._idle_hint())
        else:
            self._draw_mic(p, r.center(), _ICON)

    def _draw_pending_dot(self, p, r):
        """A small amber dot on the pill while a change hasn't landed yet.

        Drawn in EVERY state, not just idle: a dictation started inside a stale
        window is exactly the case the user needs flagged, and the recording
        pill is what is on screen then. Sits in the top-right rounded corner,
        clear of the mic glyph, the hint text and the ✓ button.
        """
        if not self._pending:
            return
        d = _PENDING_DOT_D
        dot = QtCore.QRectF(r.right() - d - 7, r.top() + 7, d, d)
        p.save()
        p.setPen(QtCore.Qt.NoPen)
        p.setBrush(_PENDING)
        p.drawEllipse(dot)
        p.restore()

    def _draw_mic(self, p, center, color):
        """A tiny minimalist microphone glyph (monochrome), centered on `center`."""
        p.save()
        p.translate(center)
        pen = QtGui.QPen(color, 1.6)
        pen.setCapStyle(QtCore.Qt.RoundCap)
        # capsule body
        p.setPen(QtCore.Qt.NoPen)
        p.setBrush(color)
        p.drawRoundedRect(QtCore.QRectF(-3, -8, 6, 10), 3, 3)
        # stand arc + stem + base
        p.setBrush(QtCore.Qt.NoBrush)
        p.setPen(pen)
        p.drawArc(QtCore.QRectF(-5.5, -4, 11, 9), 200 * 16, 140 * 16)
        p.drawLine(QtCore.QPointF(0, 4.5), QtCore.QPointF(0, 7.5))
        p.drawLine(QtCore.QPointF(-3, 7.5), QtCore.QPointF(3, 7.5))
        p.restore()

    def _paint_recording(self, p, r):
        cy = r.center().y()
        cancel_c = QtCore.QPointF(_PAD + _BTN_D / 2.0, cy)
        finish_c = QtCore.QPointF(r.right() - _PAD - _BTN_D / 2.0, cy)
        self._cancel_rect = QtCore.QRectF(
            cancel_c.x() - _BTN_D / 2.0, cy - _BTN_D / 2.0, _BTN_D, _BTN_D)
        self._finish_rect = QtCore.QRectF(
            finish_c.x() - _BTN_D / 2.0, cy - _BTN_D / 2.0, _BTN_D, _BTN_D)

        self._draw_button(p, self._cancel_rect, "cancel")
        self._draw_button(p, self._finish_rect, "finish")

        wave_x0 = _PAD + _BTN_D + _GAP
        self._draw_wave(p, wave_x0, r.top(), _WAVE_W, r.height())

    def _draw_button(self, p, rect, kind):
        hovered = self._hover_btn == kind
        p.setPen(QtCore.Qt.NoPen)
        p.setBrush(_BTN_BG_HOVER if hovered else _BTN_BG)
        p.drawEllipse(rect)
        c = rect.center()
        if kind == "cancel":
            col = _ICON_HI if hovered else _ICON_DIM
            pen = QtGui.QPen(col, 1.8)
            pen.setCapStyle(QtCore.Qt.RoundCap)
            p.setPen(pen)
            d = 4.0
            p.drawLine(QtCore.QPointF(c.x() - d, c.y() - d),
                       QtCore.QPointF(c.x() + d, c.y() + d))
            p.drawLine(QtCore.QPointF(c.x() - d, c.y() + d),
                       QtCore.QPointF(c.x() + d, c.y() - d))
        else:  # finish (check) - primary action, a touch brighter
            col = _ICON_HI if hovered else _ICON
            pen = QtGui.QPen(col, 2.0)
            pen.setCapStyle(QtCore.Qt.RoundCap)
            pen.setJoinStyle(QtCore.Qt.RoundJoin)
            p.setPen(pen)
            path = QtGui.QPainterPath()
            path.moveTo(c.x() - 4.5, c.y() + 0.5)
            path.lineTo(c.x() - 1.0, c.y() + 4.0)
            path.lineTo(c.x() + 5.0, c.y() - 4.0)
            p.drawPath(path)

    def _draw_wave(self, p, x0, top, width, height):
        p.setPen(QtCore.Qt.NoPen)
        bar_w = 3.0
        slot = width / _N_BARS
        cy = top + height / 2.0
        for i, lvl in enumerate(self._levels):
            # gentle idle shimmer so the bars breathe even in near-silence
            idle = 0.10 + 0.05 * (0.5 + 0.5 * math.sin(self._phase + i * 0.5))
            v = max(idle, lvl)
            bar_h = max(3.0, v * (height - 12))
            x = x0 + i * slot + (slot - bar_w) / 2.0
            col = QtGui.QColor(_WAVE)
            col.setAlpha(150 + int(105 * min(1.0, v)))
            p.setBrush(col)
            p.drawRoundedRect(QtCore.QRectF(x, cy - bar_h / 2.0, bar_w, bar_h),
                              bar_w / 2.0, bar_w / 2.0)

    def _paint_processing(self, p, r):
        p.setPen(QtCore.Qt.NoPen)
        n = 3
        gap = 12.0
        rad = 3.0
        cx = r.center().x()
        cy = r.center().y()
        x0 = cx - gap
        for i in range(n):
            a = 0.5 + 0.5 * math.sin(self._phase - i * 0.9)
            col = QtGui.QColor(_ICON)
            col.setAlpha(70 + int(170 * a))
            p.setBrush(col)
            p.drawEllipse(QtCore.QPointF(x0 + i * gap, cy), rad, rad)


class _HintBubble(QtWidgets.QWidget):
    """A tiny charcoal tooltip bubble shown above the pill on hover. Monochrome,
    never accepts focus (so it can't steal focus while the user dictates)."""

    def __init__(self):
        super().__init__(
            None,
            QtCore.Qt.FramelessWindowHint | QtCore.Qt.WindowStaysOnTopHint
            | QtCore.Qt.Tool | QtCore.Qt.WindowDoesNotAcceptFocus)
        self.setAttribute(QtCore.Qt.WA_TranslucentBackground)
        self.setAttribute(QtCore.Qt.WA_ShowWithoutActivating)
        _apply_mac_tool_window_attr(self)
        self._text = ""
        f = QtGui.QFont()
        f.setPointSize(9)
        f.setWeight(QtGui.QFont.Medium)
        self._font = f

    def showEvent(self, event):
        super().showEvent(event)
        _apply_mac_panel_behavior(self)

    def set_text(self, text):
        self._text = text or ""
        self.adjustSize()
        self.update()

    def sizeHint(self):
        fm = QtGui.QFontMetrics(self._font)
        w = fm.horizontalAdvance(self._text) + 24
        h = fm.height() + 12
        return QtCore.QSize(w, h)

    def paintEvent(self, event):
        p = QtGui.QPainter(self)
        p.setRenderHint(QtGui.QPainter.Antialiasing)
        r = QtCore.QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        radius = min(10.0, r.height() / 2.0)
        p.setPen(QtCore.Qt.NoPen)
        p.setBrush(_BG_BOT)
        p.drawRoundedRect(r, radius, radius)
        p.setBrush(QtCore.Qt.NoBrush)
        p.setPen(QtGui.QPen(_BORDER, 1))
        p.drawRoundedRect(r, radius, radius)
        p.setFont(self._font)
        p.setPen(_TEXT)
        p.drawText(r, QtCore.Qt.AlignCenter, self._text)
