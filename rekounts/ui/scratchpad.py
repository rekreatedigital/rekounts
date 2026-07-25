"""The Scratchpad — a floating sticky note you can dictate into.

The product problem: to dictate a note you had to open Notepad first. The pad
removes that step. Right-click the tray icon, "Open Scratchpad", talk — the text
lands in an editable note that is still there tomorrow.

Design
------
Windows Sticky Notes, reimagined for Rekounts' charcoal palette, and cleaner:

* **No title bar.** The note body starts at the top edge. Frameless, rounded,
  with a soft painted drop shadow so it floats above whatever is behind it.
* **Chrome appears on hover.** Close and minimize are two small glyphs in the
  top-right corner with no bar behind them; they fade in when the pointer is
  over the note and fade back out when it leaves.
* **A quiet formatting toolbar along the bottom** — bold, italic, underline,
  strikethrough, bullets. Text only; there is no image button, because the pad
  is a place for words. The toolbar is always present but recedes, brightening
  with the rest of the chrome on hover.
* **Draggable by its body, resizable from its edges.** With no title bar to grab,
  the empty band around the text and the toolbar strip are the drag handles, and
  every edge and corner resizes.

Why the shadow is painted by hand rather than being a QGraphicsDropShadowEffect:
``QWidget.render()`` — which is how ``tools/capture_scratchpad_shots.py`` and
the tests photograph the pad without ever putting it on screen — does not
reliably apply graphics effects, so an effect-based shadow would be invisible in
exactly the images that are supposed to prove the design.

Focus, and where dictation goes
-------------------------------
This is the one place the pad deliberately differs from ``ui/overlay.py``, which
it otherwise takes its structure from. The pill sets ``WindowDoesNotAcceptFocus``
and ``WS_EX_NOACTIVATE`` so it can never steal focus from the app you are
dictating into. The pad is the opposite: you type in it, so it MUST accept focus.

That makes "where does the text go?" a real question, and the rule is the least
surprising one available: **dictation lands in the pad only while the pad is the
focused window.** Click into Word and dictation goes to Word, exactly as before;
click into the pad and it goes to the pad. It is the same rule the user already
knows — text goes where the cursor is — with the pad simply being one more place
the cursor can be. See :class:`ScratchpadRouter`.

Qt is imported at module scope, so — like every other module under
``rekounts/ui`` — this must only be imported *after* the speech model exists.
See the import-order note in ``rekounts/__main__.py``.
"""

import logging

from PySide6 import QtCore, QtGui, QtWidgets

from rekounts.scratchpad_store import ScratchpadStore

log = logging.getLogger(__name__)

# --- geometry (logical px; Qt scales for DPI) --------------------------------
# The transparent ring around the card that the drop shadow is painted into.
# It is also the outer half of the resize grab band: the pixels look empty but
# belong to our window either way, so letting them resize the note turns dead
# space into a generous, easy-to-hit edge.
SHADOW = 14
RADIUS = 14
DEFAULT_W, DEFAULT_H = 330, 380
MIN_W, MIN_H = 240, 190
# How far inside the card's edge a press still counts as a resize.
RESIZE_MARGIN = 6
# Breathing room between the card edge and its contents.
PAD = 15
# The empty strip along the top. There is no title bar, so this is what stands
# in for one: it holds the hover chrome at its right and is a drag handle.
TOP_ZONE = 26
TOOLBAR_H = 34
CHROME_BTN = 20
FORMAT_BTN = 26

# --- palette -----------------------------------------------------------------
# One FLAT surface, deliberately: the reference note is a single unbroken sheet,
# and a gradient — however subtle — is the first thing that makes a pad read as
# a UI panel instead of a piece of paper. It sits a step lighter than the Hub's
# cards (theme.CARD, #1a1c22) because the pad floats above other windows, and a
# raised surface darker than what it covers reads as a hole, not as paper. The
# faint cool cast keeps it in the same monochrome family as the rest of the app.
_PAPER = QtGui.QColor(36, 38, 44)
_EDGE = QtGui.QColor(255, 255, 255, 20)
_SHADOW_COLOR = QtGui.QColor(0, 0, 0, 120)
_TEXT = QtGui.QColor(232, 234, 237)          # theme.TEXT
_GLYPH = QtGui.QColor(226, 228, 234)
_BTN_HOVER = QtGui.QColor(255, 255, 255, 26)
_BTN_CHECKED = QtGui.QColor(255, 255, 255, 40)
_CLOSE_HOVER = QtGui.QColor(214, 106, 106)   # the one warm note, on hover only

PLACEHOLDER = "Dictate or type a note…"


# ============================================================== pure helpers
def resize_edge(x, y, w, h, margin) -> str:
    """Which edge/corner the point (x, y) grabs inside a w*h box, or "".

    Returns a compass-ish token: ``"l" "r" "t" "b" "tl" "tr" "bl" "br"``. Pure
    and Qt-free so the whole resize hit-test can be unit-tested without ever
    creating a window.
    """
    if w <= 0 or h <= 0 or margin <= 0:
        return ""
    if not (0 <= x < w and 0 <= y < h):
        return ""
    vertical = "t" if y < margin else ("b" if y >= h - margin else "")
    horizontal = "l" if x < margin else ("r" if x >= w - margin else "")
    return vertical + horizontal


def clamp_to_screens(geometry, screen_rects, min_w=MIN_W, min_h=MIN_H):
    """Nudge a restored ``[x, y, w, h]`` back onto a screen that still exists.

    A note saved on a second monitor must not reopen at coordinates that are now
    off the desktop — the user would open the pad and see nothing at all. If the
    saved rect overlaps any screen it is left alone; otherwise it is moved onto
    the first screen. Pure: ``screen_rects`` is a list of ``(x, y, w, h)``.
    """
    if not geometry or len(geometry) != 4:
        return None
    x, y, w, h = (int(v) for v in geometry)
    w, h = max(int(min_w), w), max(int(min_h), h)
    if not screen_rects:
        return [x, y, w, h]
    # "Visible" means a real overlap, not a shared edge — a note one pixel onto
    # the desktop is not a note the user can grab.
    for sx, sy, sw, sh in screen_rects:
        if x < sx + sw and x + w > sx and y < sy + sh and y + h > sy:
            return [x, y, w, h]
    sx, sy, sw, sh = screen_rects[0]
    return [sx + max(0, (sw - w) // 2), sy + max(0, (sh - h) // 2), w, h]


def spaced_append(before: str, addition: str) -> str:
    """The text to actually insert so dictation doesn't weld onto the last word.

    ``before`` is the character immediately left of the caret (``""`` at the
    start of the note). A separator is added only when both sides would
    otherwise collide — so a caret after "Hello" gets " world", a caret after
    "Hello " gets "world", and live-typing chunks that already carry their own
    leading space are left alone.
    """
    addition = addition or ""
    if not addition or not before:
        return addition
    if before.isspace() or addition[:1].isspace():
        return addition
    return " " + addition


# ================================================================== buttons
class _GlyphButton(QtWidgets.QAbstractButton):
    """A borderless button that paints its own glyph.

    Every control on the pad is one of these rather than a styled QPushButton:
    the pad is a hand-painted surface, and a stock button — even restyled —
    brings a frame, a focus ring and a platform hover of its own that break the
    "one continuous piece of paper" look.

    ``opacity`` is driven by the pad's hover animation, so a button can fade to
    invisible while still being a live widget.
    """

    def __init__(self, kind, size, tooltip="", checkable=False):
        super().__init__()
        self.kind = kind
        self._opacity = 1.0
        self._hovered = False
        self.setFixedSize(size, size)
        self.setCheckable(checkable)
        self.setToolTip(tooltip)
        self.setCursor(QtCore.Qt.PointingHandCursor)
        # Never take focus: clicking Bold must leave the caret in the note,
        # otherwise the format the user just asked for is applied to a text
        # cursor that is no longer where they were typing.
        self.setFocusPolicy(QtCore.Qt.NoFocus)

    def set_opacity(self, value: float):
        value = max(0.0, min(1.0, float(value)))
        if value != self._opacity:
            self._opacity = value
            self.update()

    def set_checked_silently(self, checked: bool):
        """Reflect the caret's format without re-applying it to the document."""
        self.blockSignals(True)
        self.setChecked(bool(checked))
        self.blockSignals(False)
        self.update()

    def enterEvent(self, e):
        self._hovered = True
        self.update()

    def leaveEvent(self, e):
        self._hovered = False
        self.update()

    # ------------------------------------------------------------------ paint
    def paintEvent(self, _):
        if self._opacity <= 0.01:
            return
        p = QtGui.QPainter(self)
        p.setRenderHint(QtGui.QPainter.Antialiasing)
        p.setRenderHint(QtGui.QPainter.TextAntialiasing)
        p.setOpacity(self._opacity)
        r = QtCore.QRectF(self.rect())

        if self.isChecked() or self._hovered:
            fill = _BTN_CHECKED if self.isChecked() else _BTN_HOVER
            if self.kind == "close" and self._hovered:
                fill = _CLOSE_HOVER
            p.setPen(QtCore.Qt.NoPen)
            p.setBrush(fill)
            p.drawRoundedRect(r.adjusted(0.5, 0.5, -0.5, -0.5), 6, 6)

        color = QtGui.QColor(_GLYPH)
        if self.kind == "close" and self._hovered:
            color = QtGui.QColor(255, 255, 255)
        painter = getattr(self, "_paint_" + self.kind, None)
        if painter is not None:
            painter(p, r, color)
        p.end()

    # --- window chrome ---
    def _paint_close(self, p, r, color):
        c, d = r.center(), 3.6
        pen = QtGui.QPen(color, 1.4)
        pen.setCapStyle(QtCore.Qt.RoundCap)
        p.setPen(pen)
        p.drawLine(QtCore.QPointF(c.x() - d, c.y() - d),
                   QtCore.QPointF(c.x() + d, c.y() + d))
        p.drawLine(QtCore.QPointF(c.x() - d, c.y() + d),
                   QtCore.QPointF(c.x() + d, c.y() - d))

    def _paint_minimize(self, p, r, color):
        c, d = r.center(), 4.0
        pen = QtGui.QPen(color, 1.4)
        pen.setCapStyle(QtCore.Qt.RoundCap)
        p.setPen(pen)
        p.drawLine(QtCore.QPointF(c.x() - d, c.y() + 0.5),
                   QtCore.QPointF(c.x() + d, c.y() + 0.5))

    # --- formatting ---
    def _letter(self, p, r, color, letter, bold=False, italic=False,
                underline=False, strike=False):
        f = QtGui.QFont()
        f.setPointSize(9)
        f.setBold(bold)
        f.setItalic(italic)
        f.setUnderline(underline)
        f.setStrikeOut(strike)
        if not bold:
            f.setWeight(QtGui.QFont.Medium)
        p.setFont(f)
        p.setPen(color)
        p.drawText(r, QtCore.Qt.AlignCenter, letter)

    def _paint_bold(self, p, r, color):
        self._letter(p, r, color, "B", bold=True)

    def _paint_italic(self, p, r, color):
        self._letter(p, r, color, "I", italic=True)

    def _paint_underline(self, p, r, color):
        self._letter(p, r, color, "U", underline=True)

    def _paint_strike(self, p, r, color):
        # "ab" struck through, the way the reference note marks it — a struck
        # "S" reads as a currency symbol at this size.
        self._letter(p, r, color, "ab", strike=True)

    def _paint_bullets(self, p, r, color):
        c = r.center()
        p.setPen(QtCore.Qt.NoPen)
        p.setBrush(color)
        line_pen = QtGui.QPen(color, 1.3)
        line_pen.setCapStyle(QtCore.Qt.RoundCap)
        for row in (-4.0, 0.0, 4.0):
            p.setBrush(color)
            p.setPen(QtCore.Qt.NoPen)
            p.drawEllipse(QtCore.QPointF(c.x() - 5.5, c.y() + row), 1.2, 1.2)
            p.setPen(line_pen)
            p.drawLine(QtCore.QPointF(c.x() - 2.0, c.y() + row),
                       QtCore.QPointF(c.x() + 5.5, c.y() + row))


class _NoteEdit(QtWidgets.QTextEdit):
    """The note body. A QTextEdit stripped of every frame Qt gives it.

    Rich text (not QPlainTextEdit) because the bottom toolbar exists: bold,
    italic, underline, strikethrough and bullets are character and block
    formats, which plain text cannot carry.
    """

    def __init__(self):
        super().__init__()
        self.setFrameShape(QtWidgets.QFrame.NoFrame)
        self.setPlaceholderText(PLACEHOLDER)
        self.setAcceptRichText(False)      # paste arrives as plain text (below)
        self.setTabChangesFocus(False)
        self.setVerticalScrollBarPolicy(QtCore.Qt.ScrollBarAsNeeded)
        self.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)
        f = self.font()
        f.setPointSize(10)
        self.setFont(f)
        # Qt indents a list by indentWidth (40px by default) per level, which on
        # a ~300px note pushes every bullet a third of the way across the page.
        # The reference note keeps its bullets nearly flush with the text above
        # them; this is what gets them there.
        self.document().setIndentWidth(14)
        self.setStyleSheet(f"""
            QTextEdit {{
                background: transparent;
                border: none;
                color: {_TEXT.name()};
                selection-background-color: rgba(255, 255, 255, 40);
                selection-color: {_TEXT.name()};
            }}
            QScrollBar:vertical {{ background: transparent; width: 8px; margin: 0; }}
            QScrollBar::handle:vertical {{ background: rgba(255,255,255,26);
                border-radius: 4px; min-height: 24px; }}
            QScrollBar::handle:vertical:hover {{ background: rgba(255,255,255,52); }}
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
            QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{
                background: transparent; }}
        """)

    def insertFromMimeData(self, source):
        """Paste as plain text, taking the caret's formatting.

        ``setAcceptRichText(False)`` already refuses foreign HTML, but routing
        the paste through insertPlainText as well means pasted text picks up
        whatever the user currently has switched on in the toolbar instead of
        arriving as an unstyled island.
        """
        if source.hasText():
            self.textCursor().insertText(source.text(), self.currentCharFormat())


# ================================================================ the pad
class Scratchpad(QtWidgets.QWidget):
    """The sticky note. One instance, created at startup, shown on demand.

    Thread-safety follows ``ui/overlay.py``: the public entry points are Qt
    signals, so the audio/worker threads can call them directly and Qt queues
    the work onto the GUI thread.
    """

    # Public, thread-safe entry points.
    _append_sig = QtCore.Signal(str)
    _cmd = QtCore.Signal(str)   # "open"|"hide"|"enable"|"disable"|"clear"

    # How long after the last keystroke (or move/resize) the note is written.
    SAVE_DELAY_MS = 700
    CHROME_FADE_MS = 130
    # The toolbar never disappears — it is part of the note's furniture, and the
    # reference note keeps it plainly readable at all times — it just sits back
    # a little until the pointer arrives. Only close/minimize hide completely.
    TOOLBAR_REST_OPACITY = 0.75

    def __init__(self, store=None, parent=None):
        super().__init__(parent, QtCore.Qt.Window | QtCore.Qt.FramelessWindowHint)
        self.setAttribute(QtCore.Qt.WA_TranslucentBackground)
        self.setWindowTitle("Rekounts Scratchpad")
        self.setMinimumSize(MIN_W + SHADOW * 2, MIN_H + SHADOW * 2)
        self.setMouseTracking(True)

        self.store = store if store is not None else ScratchpadStore()

        # --- state ---
        self._enabled = True
        # Mirrors of Qt window state, maintained on the GUI thread so
        # wants_dictation() can be answered from a worker thread by reading
        # plain attributes instead of touching Qt from the wrong thread.
        self._active = False
        self._shown = False
        self._loading = False
        self._chrome = 0.0
        self._drag_offset = None
        self._resize_edge = ""
        self._resize_origin = None      # (QRect at press, global QPoint at press)

        self._build()
        self._load()

        self._save_timer = QtCore.QTimer(self)
        self._save_timer.setSingleShot(True)
        self._save_timer.setInterval(self.SAVE_DELAY_MS)
        self._save_timer.timeout.connect(self.flush)

        self._fade = QtCore.QPropertyAnimation(self, b"chrome", self)
        self._fade.setDuration(self.CHROME_FADE_MS)
        self._fade.setEasingCurve(QtCore.QEasingCurve.OutCubic)

        self._append_sig.connect(self._do_append)
        self._cmd.connect(self._apply_cmd)
        self._apply_chrome()

    # --------------------------------------------------------------- building
    def _build(self):
        outer = QtWidgets.QVBoxLayout(self)
        outer.setContentsMargins(SHADOW + PAD, SHADOW, SHADOW + PAD, SHADOW)
        outer.setSpacing(0)

        # --- top strip: no bar, just space, with the chrome at its right ---
        top = QtWidgets.QHBoxLayout()
        top.setContentsMargins(0, 6, 0, 0)
        top.setSpacing(2)
        top.addStretch(1)
        self.minimize_button = _GlyphButton("minimize", CHROME_BTN, "Minimize")
        self.minimize_button.clicked.connect(self.showMinimized)
        self.close_button = _GlyphButton("close", CHROME_BTN, "Close (your note is kept)")
        self.close_button.clicked.connect(self.hide)
        top.addWidget(self.minimize_button)
        top.addWidget(self.close_button)
        # The strip's leftover space to the left of the two glyphs is a drag
        # handle — with no title bar it is the closest thing the pad has to one.
        top.setContentsMargins(0, 6, 0, max(0, TOP_ZONE - CHROME_BTN - 6))
        outer.addLayout(top)

        # --- the note ---
        self.edit = _NoteEdit()
        self.edit.setViewportMargins(0, 2, 0, 0)
        outer.addWidget(self.edit, 1)

        # --- bottom formatting toolbar ---
        self.toolbar = QtWidgets.QWidget()
        self.toolbar.setFixedHeight(TOOLBAR_H)
        self.toolbar.setAttribute(QtCore.Qt.WA_TransparentForMouseEvents, False)
        bar = QtWidgets.QHBoxLayout(self.toolbar)
        bar.setContentsMargins(0, 4, 0, 2)
        bar.setSpacing(2)
        self.format_buttons = {}
        # Text only. There is deliberately no image button: the pad is where
        # dictation lands, and dictation produces words.
        for kind, tip in (("bold", "Bold"), ("italic", "Italic"),
                          ("underline", "Underline"), ("strike", "Strikethrough"),
                          ("bullets", "Bullet list")):
            btn = _GlyphButton(kind, FORMAT_BTN, tip, checkable=True)
            bar.addWidget(btn)
            self.format_buttons[kind] = btn
        bar.addStretch(1)
        outer.addWidget(self.toolbar)

        self.format_buttons["bold"].toggled.connect(self._apply_bold)
        self.format_buttons["italic"].toggled.connect(self._apply_italic)
        self.format_buttons["underline"].toggled.connect(self._apply_underline)
        self.format_buttons["strike"].toggled.connect(self._apply_strike)
        self.format_buttons["bullets"].toggled.connect(self._apply_bullets)

        self.edit.textChanged.connect(self._schedule_save)
        self.edit.currentCharFormatChanged.connect(lambda _f: self._sync_buttons())
        self.edit.cursorPositionChanged.connect(self._sync_buttons)

        # The toolbar's empty space drags the window, like the top strip.
        self.toolbar.installEventFilter(self)

        self.resize(DEFAULT_W + SHADOW * 2, DEFAULT_H + SHADOW * 2)

    # ------------------------------------------------------- public interface
    @QtCore.Slot(str)
    def append_dictation(self, text):
        """Add a finished dictation to the note. Thread-safe."""
        self._append_sig.emit(text or "")

    @QtCore.Slot()
    def open_and_raise(self):
        """Show the pad, bring it forward and put the caret in it. Thread-safe."""
        self._cmd.emit("open")

    @QtCore.Slot(bool)
    def set_enabled(self, enabled):
        """Live-apply the "Scratchpad" setting. Thread-safe.

        Switching it off hides an open pad but never touches the saved note:
        turning a feature off is not a request to delete what you wrote.
        """
        self._cmd.emit("enable" if enabled else "disable")

    def is_enabled(self) -> bool:
        return self._enabled

    @QtCore.Slot()
    def clear_note(self):
        """Throw the note away, on screen and on disk. Thread-safe.

        This is what Settings → Data & Privacy → **Clear note** calls. It has to
        go through the pad rather than deleting scratchpad.json underneath it:
        an open pad autosaves on a pause in typing, so a file cleared behind its
        back would be written straight back out with the text still in it.

        Deliberately separate from the Scratchpad on/off switch. That switch
        hides a feature; this one deletes what you wrote. Only one of them
        should be able to lose your words, and only when you asked it to.
        """
        self._cmd.emit("clear")

    def wants_dictation(self) -> bool:
        """Should the next dictation land here rather than in the focused app?

        Safe to call from any thread: every term is a plain attribute kept up to
        date by GUI-thread event handlers, so this never touches Qt off-thread.
        """
        return bool(self._enabled and self._shown and self._active)

    # ------------------------------------------------------------- persistence
    def _load(self):
        data = self.store.load()
        self._loading = True
        try:
            html = data.get("html") or ""
            if html:
                self.edit.setHtml(html)
                cursor = self.edit.textCursor()
                cursor.movePosition(QtGui.QTextCursor.End)
                self.edit.setTextCursor(cursor)
        finally:
            self._loading = False
        self._pending_geometry = data.get("geometry")

    def _restore_geometry(self):
        """Apply the saved rect, once, the first time the pad is shown.

        Deferred to first show rather than done in __init__ because the screen
        list is what decides whether the saved position is still reachable, and
        clamping against it at construction time would use a screen layout that
        may have changed by the time anyone opens the pad.
        """
        geometry, self._pending_geometry = getattr(
            self, "_pending_geometry", None), None
        if not geometry:
            return
        screens = QtGui.QGuiApplication.screens()
        rects = [(s.availableGeometry().x(), s.availableGeometry().y(),
                  s.availableGeometry().width(), s.availableGeometry().height())
                 for s in screens]
        clamped = clamp_to_screens(geometry, rects,
                                   MIN_W + SHADOW * 2, MIN_H + SHADOW * 2)
        if clamped:
            x, y, w, h = clamped
            self.move(x, y)
            self.resize(w, h)

    def _schedule_save(self):
        if self._loading:
            return
        self._save_timer.start()

    @QtCore.Slot()
    def flush(self):
        """Write the note now. Called on a pause in typing, and on hide/close."""
        self._save_timer.stop()
        try:
            g = self.geometry()
            self.store.save(self.edit.toHtml(), [g.x(), g.y(), g.width(), g.height()])
        except Exception:
            # A failed save must never propagate into Qt's event loop; the store
            # already logs the reason.
            log.exception("saving the scratchpad failed")

    # ------------------------------------------------------------- formatting
    def _merge(self, fmt):
        """Apply a character format to the selection, or to what is typed next.

        With no selection ``mergeCurrentCharFormat`` sets the *typing* format,
        which is what a toolbar button should do in a note — Bold means "what I
        say next is bold", not "reformat the word I happen to be standing in".
        """
        self.edit.mergeCurrentCharFormat(fmt)
        self.edit.setFocus()

    def _apply_bold(self, on):
        fmt = QtGui.QTextCharFormat()
        fmt.setFontWeight(QtGui.QFont.Bold if on else QtGui.QFont.Normal)
        self._merge(fmt)

    def _apply_italic(self, on):
        fmt = QtGui.QTextCharFormat()
        fmt.setFontItalic(bool(on))
        self._merge(fmt)

    def _apply_underline(self, on):
        fmt = QtGui.QTextCharFormat()
        fmt.setFontUnderline(bool(on))
        self._merge(fmt)

    def _apply_strike(self, on):
        fmt = QtGui.QTextCharFormat()
        fmt.setFontStrikeOut(bool(on))
        self._merge(fmt)

    def _apply_bullets(self, on):
        cursor = self.edit.textCursor()
        cursor.beginEditBlock()
        try:
            if on:
                fmt = QtGui.QTextListFormat()
                fmt.setStyle(QtGui.QTextListFormat.ListDisc)
                fmt.setIndent(1)
                cursor.createList(fmt)
            else:
                current = cursor.currentList()
                if current is not None:
                    block = cursor.block()
                    current.remove(block)
                    block_format = block.blockFormat()
                    block_format.setIndent(0)
                    cursor.setBlockFormat(block_format)
        finally:
            cursor.endEditBlock()
        self.edit.setFocus()

    def _sync_buttons(self):
        """Reflect the caret's formatting in the toolbar, without re-applying it."""
        fmt = self.edit.currentCharFormat()
        state = {
            "bold": fmt.fontWeight() >= QtGui.QFont.Bold,
            "italic": fmt.fontItalic(),
            "underline": fmt.fontUnderline(),
            "strike": fmt.fontStrikeOut(),
            "bullets": self.edit.textCursor().currentList() is not None,
        }
        for kind, checked in state.items():
            self.format_buttons[kind].set_checked_silently(checked)

    # ---------------------------------------------------------------- commands
    @QtCore.Slot(str)
    def _apply_cmd(self, cmd):
        if cmd == "enable":
            self._enabled = True
            return
        if cmd == "disable":
            self._enabled = False
            if self.isVisible():
                self.flush()
                self.hide()
            return
        if cmd == "hide":
            self.hide()
            return
        if cmd == "clear":
            # The timer first: a pending autosave from before the clear would
            # otherwise fire afterwards and write the old note back.
            self._save_timer.stop()
            self._loading = True          # emptying the editor is not an edit
            try:
                self.edit.clear()
            finally:
                self._loading = False
            self.flush()                  # persist the empty note now, not in 700ms
            return
        if cmd == "open":
            if not self._enabled:
                return
            if self.isMinimized():
                self.showNormal()
            else:
                self.show()
            self.raise_()
            self.activateWindow()
            self.edit.setFocus()

    @QtCore.Slot(str)
    def _do_append(self, text):
        """Insert a dictation at the caret, in the caret's current formatting."""
        if not text:
            return
        cursor = self.edit.textCursor()
        probe = QtGui.QTextCursor(cursor)
        probe.movePosition(QtGui.QTextCursor.Left, QtGui.QTextCursor.KeepAnchor)
        before = probe.selectedText()
        # insertText with an explicit format is what makes dictation inherit
        # whatever the toolbar currently has switched on, instead of arriving in
        # the document's default style.
        cursor.insertText(spaced_append(before, text), self.edit.currentCharFormat())
        self.edit.setTextCursor(cursor)
        self.edit.ensureCursorVisible()

    # --------------------------------------------------------- hover chrome
    def _get_chrome(self) -> float:
        return self._chrome

    def _set_chrome(self, value: float):
        self._chrome = float(value)
        self._apply_chrome()

    chrome = QtCore.Property(float, _get_chrome, _set_chrome)

    def _apply_chrome(self):
        """Close/minimize fade all the way out; the toolbar only sits back."""
        for button in (self.close_button, self.minimize_button):
            button.set_opacity(self._chrome)
        rest = self.TOOLBAR_REST_OPACITY
        toolbar_opacity = rest + (1.0 - rest) * self._chrome
        for button in self.format_buttons.values():
            button.set_opacity(toolbar_opacity)
        self.update()

    def _fade_chrome(self, target: float):
        self._fade.stop()
        self._fade.setStartValue(self._chrome)
        self._fade.setEndValue(target)
        self._fade.start()

    def enterEvent(self, e):
        self._fade_chrome(1.0)

    def leaveEvent(self, e):
        self._fade_chrome(0.0)
        self.unsetCursor()

    # ------------------------------------------------------ drag & resize
    def _card_rect(self) -> QtCore.QRect:
        return self.rect().adjusted(SHADOW, SHADOW, -SHADOW, -SHADOW)

    def _edge_at(self, pos) -> str:
        """The resize edge under a point, counting the shadow ring as grabbable.

        The ring looks like empty space but is still our window, so clicks there
        would otherwise be swallowed for no benefit. Treating it as part of the
        grab band turns that into a wider, easier target — the note resizes from
        slightly outside its visible edge, which is what it looks like it should
        do anyway.
        """
        return resize_edge(pos.x(), pos.y(), self.width(), self.height(),
                           SHADOW + RESIZE_MARGIN)

    _CURSORS = {
        "l": QtCore.Qt.SizeHorCursor, "r": QtCore.Qt.SizeHorCursor,
        "t": QtCore.Qt.SizeVerCursor, "b": QtCore.Qt.SizeVerCursor,
        "tl": QtCore.Qt.SizeFDiagCursor, "br": QtCore.Qt.SizeFDiagCursor,
        "tr": QtCore.Qt.SizeBDiagCursor, "bl": QtCore.Qt.SizeBDiagCursor,
    }

    def _is_drag_zone(self, pos) -> bool:
        """Empty note surface — the top strip and the card's padding ring."""
        card = self._card_rect()
        if not card.contains(pos):
            return False
        if self.childAt(pos) is not None:
            return False              # a real control; let it have the click
        return True

    def mousePressEvent(self, e):
        if e.button() != QtCore.Qt.LeftButton:
            return
        pos = e.position().toPoint() if hasattr(e, "position") else e.pos()
        edge = self._edge_at(pos)
        if edge:
            self._resize_edge = edge
            self._resize_origin = (QtCore.QRect(self.geometry()),
                                   e.globalPosition().toPoint())
            e.accept()
            return
        if self._is_drag_zone(pos):
            self._drag_offset = (e.globalPosition().toPoint()
                                 - self.frameGeometry().topLeft())
            e.accept()

    def mouseMoveEvent(self, e):
        pos = e.position().toPoint() if hasattr(e, "position") else e.pos()
        if self._resize_edge and self._resize_origin:
            self._perform_resize(e.globalPosition().toPoint())
            return
        if self._drag_offset is not None:
            self.move(e.globalPosition().toPoint() - self._drag_offset)
            return
        edge = self._edge_at(pos)
        if edge:
            self.setCursor(self._CURSORS[edge])
        elif self._is_drag_zone(pos):
            self.setCursor(QtCore.Qt.OpenHandCursor)
        else:
            self.unsetCursor()

    def mouseReleaseEvent(self, e):
        if self._drag_offset is not None or self._resize_edge:
            self._schedule_save()      # geometry changed; persist it
        self._drag_offset = None
        self._resize_edge = ""
        self._resize_origin = None

    def _perform_resize(self, global_pos):
        start_rect, start_pos = self._resize_origin
        delta = global_pos - start_pos
        rect = QtCore.QRect(start_rect)
        if "l" in self._resize_edge:
            rect.setLeft(rect.left() + delta.x())
        if "r" in self._resize_edge:
            rect.setRight(rect.right() + delta.x())
        if "t" in self._resize_edge:
            rect.setTop(rect.top() + delta.y())
        if "b" in self._resize_edge:
            rect.setBottom(rect.bottom() + delta.y())
        # Clamp against the minimum by moving the edge being dragged, never the
        # opposite one — otherwise shrinking past the minimum from the left
        # walks the whole window across the screen.
        # (QRect's right/bottom are inclusive, hence the -1 when pinning to an
        # edge; setWidth/setHeight keep left/top fixed and need no adjustment.)
        min_w, min_h = self.minimumWidth(), self.minimumHeight()
        if rect.width() < min_w:
            if "l" in self._resize_edge:
                rect.setLeft(rect.right() - min_w + 1)
            else:
                rect.setWidth(min_w)
        if rect.height() < min_h:
            if "t" in self._resize_edge:
                rect.setTop(rect.bottom() - min_h + 1)
            else:
                rect.setHeight(min_h)
        self.setGeometry(rect)

    def eventFilter(self, obj, event):
        """Let the toolbar's empty space drag the window too.

        The buttons are children of the toolbar, so a press that reaches the
        toolbar itself is by definition on the strip's blank part.
        """
        if obj is self.toolbar:
            kind = event.type()
            if kind == QtCore.QEvent.MouseButtonPress and \
                    event.button() == QtCore.Qt.LeftButton:
                self._drag_offset = (event.globalPosition().toPoint()
                                     - self.frameGeometry().topLeft())
                return True
            if kind == QtCore.QEvent.MouseMove and self._drag_offset is not None:
                self.move(event.globalPosition().toPoint() - self._drag_offset)
                return True
            if kind == QtCore.QEvent.MouseButtonRelease and \
                    self._drag_offset is not None:
                self._drag_offset = None
                self._schedule_save()
                return True
        return super().eventFilter(obj, event)

    # ------------------------------------------------------- window lifecycle
    def showEvent(self, e):
        super().showEvent(e)
        if not self._shown:
            self._restore_geometry()
        self._shown = True
        self._sync_buttons()

    def hideEvent(self, e):
        super().hideEvent(e)
        self._shown = False
        self._active = False
        if self._save_timer.isActive():
            self.flush()

    def closeEvent(self, e):
        """Closing hides; it never quits the app and never discards the note.

        The pad is a tray-opened accessory, not a document window — and the app
        runs with quitOnLastWindowClosed(False), so a real close here would just
        destroy the widget the tray still holds a reference to.
        """
        self.flush()
        e.ignore()
        self.hide()

    def changeEvent(self, e):
        super().changeEvent(e)
        if e.type() == QtCore.QEvent.ActivationChange:
            self._active = self.isActiveWindow()
        elif e.type() == QtCore.QEvent.WindowStateChange:
            # A minimized pad is not somewhere dictation should land.
            if self.isMinimized():
                self._active = False

    def moveEvent(self, e):
        super().moveEvent(e)
        if self._shown:
            self._schedule_save()

    def resizeEvent(self, e):
        super().resizeEvent(e)
        if self._shown:
            self._schedule_save()

    # ------------------------------------------------------------------ paint
    def paintEvent(self, _):
        p = QtGui.QPainter(self)
        p.setRenderHint(QtGui.QPainter.Antialiasing)
        card = QtCore.QRectF(self._card_rect())

        # Soft drop shadow: concentric rounded rects with a quadratic alpha
        # ramp. Cheap (one pass, only on repaint) and — unlike a
        # QGraphicsDropShadowEffect — it survives QWidget.render(), which is how
        # the pad is photographed for the docs.
        p.setPen(QtCore.Qt.NoPen)
        for i in range(SHADOW, 0, -1):
            t = i / SHADOW
            alpha = int(_SHADOW_COLOR.alpha() * (1.0 - t) ** 2.2)
            if alpha <= 0:
                continue
            color = QtGui.QColor(_SHADOW_COLOR)
            color.setAlpha(alpha)
            p.setBrush(color)
            # Offset downward: light comes from above, as it does everywhere
            # else in the app.
            p.drawRoundedRect(card.adjusted(-i, -i + 2, i, i + 2),
                              RADIUS + i, RADIUS + i)

        # One flat sheet. No gradient and no rule above the toolbar — the note
        # is a single surface, and every line drawn on it is a line that makes
        # it look like a dialog.
        p.setBrush(_PAPER)
        p.setPen(QtCore.Qt.NoPen)
        p.drawRoundedRect(card, RADIUS, RADIUS)

        p.setBrush(QtCore.Qt.NoBrush)
        p.setPen(QtGui.QPen(_EDGE, 1))
        p.drawRoundedRect(card.adjusted(0.5, 0.5, -0.5, -0.5), RADIUS, RADIUS)


# ================================================================== routing
class ScratchpadRouter:
    """Sends a finished dictation to the pad when the pad is focused.

    Wraps the app's :class:`~rekounts.text_inserter.TextInserter` and exposes
    the same one-method interface (``insert(text) -> outcome``), so the
    controller and the live-typing loop need no knowledge of the pad at all.

    Why divert here rather than let the ordinary paste land in the focused pad
    by itself: the insertion path exists to get text into *another process* —
    it backs up and restores the clipboard, waits for the user's modifier keys
    to lift, and checks for an elevated target. None of that applies to a widget
    in this very process, and all of it can fail. Writing straight into the
    document is both more reliable and leaves the user's clipboard untouched.
    """

    # Not one of controller._INSERT_FAILURE_TOKENS, so the dictation is recorded
    # in history as delivered — which it is.
    OUTCOME = "scratchpad"

    def __init__(self, pad, inserter):
        self.pad = pad
        self.inserter = inserter

    def insert(self, text):
        try:
            wanted = self.pad.wants_dictation()
        except Exception:
            # A broken pad must never cost the user their dictation.
            log.exception("scratchpad routing check failed; inserting normally")
            wanted = False
        if not wanted:
            return self.inserter.insert(text)
        self.pad.append_dictation(text)
        return self.OUTCOME
