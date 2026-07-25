"""The Settings page — a first-class page inside the Hub, not a second window.

Layout follows the rest of the Hub: sections (General / Audio / Behavior /
System / Data & Privacy), each a card of aligned rows. A row is a title, an
optional one-line explanation, and one control in a fixed right-hand column.

Apply model: **instant apply**. Every control persists on change (config.set →
config.save) and then asks the app to live-apply, coalesced through a short
timer so dragging a spinbox doesn't rebuild the hotkey listener twenty times.
There is no Save button and no restart path — the setting you changed is the
setting that is running.
"""

import logging

from PySide6 import QtCore, QtGui, QtWidgets

from rekounts import paths, sounds
from rekounts.config import default_config_path
from rekounts.device_utils import classify_level, resolve_input_device
from rekounts.hotkey_manager import DEFAULT_HOTKEY, is_valid_hotkey
from rekounts.languages import LANGUAGES
from rekounts.network_facts import statement as network_statement
from rekounts.scratchpad_store import ScratchpadStore
from rekounts.ui import platform_text, theme
from rekounts.ui.wheel_guard import guard_wheel

log = logging.getLogger(__name__)

_LEVEL_MESSAGES = {
    "loud": "Heard you clearly.",
    "quiet": "Very quiet — boosted, may still work.",
    "silent": "Silent — wrong microphone, or muted.",
}

def _nearest_volume(value):
    """Snap a stored cue volume to the closest level the dropdown offers.

    config.json holds the raw amplitude, so it can be hand-edited to anything.
    Rather than silently showing "Soft" for a hand-set 0.15, pick the entry that
    is actually closest — the control then never misreports what is playing.
    """
    try:
        value = float(value)
    except (TypeError, ValueError):
        return sounds.VOLUME_NORMAL
    return min(sounds.VOLUME_LEVELS, key=lambda level: abs(level - value))


# Generated from rekounts/network_facts.py rather than written out here. This
# sentence, docs/privacy.md and SECURITY.md had drifted to three different
# counts of the same two requests; the list is now the single source and
# tests/test_network_claims.py holds all three to it.
NETWORK_STATEMENT = network_statement()


# ===================================================== hotkey capture (wave 1)
# Migrated unchanged from the old settings window: press-keys-to-capture with
# validation, so a typo can never reach config.json and brick startup.
_QT_MODIFIERS = {
    QtCore.Qt.Key_Control: "ctrl",
    QtCore.Qt.Key_Shift: "shift",
    QtCore.Qt.Key_Alt: "alt",
    QtCore.Qt.Key_Meta: "win",
}
_QT_NAMED = {
    QtCore.Qt.Key_Space: "space",
    QtCore.Qt.Key_Return: "enter",
    QtCore.Qt.Key_Enter: "enter",
    QtCore.Qt.Key_Tab: "tab",
    QtCore.Qt.Key_Backspace: "backspace",
    QtCore.Qt.Key_Delete: "delete",
    QtCore.Qt.Key_Insert: "insert",
    QtCore.Qt.Key_Home: "home",
    QtCore.Qt.Key_End: "end",
    QtCore.Qt.Key_PageUp: "page_up",
    QtCore.Qt.Key_PageDown: "page_down",
    QtCore.Qt.Key_Up: "up",
    QtCore.Qt.Key_Down: "down",
    QtCore.Qt.Key_Left: "left",
    QtCore.Qt.Key_Right: "right",
}
_MOD_ORDER = {"ctrl": 0, "alt": 1, "shift": 2, "win": 3}


def _qt_event_to_token(event) -> str | None:
    """Map a Qt key event to a hotkey token, or None if unsupported."""
    key = event.key()
    if key in _QT_MODIFIERS:
        return _QT_MODIFIERS[key]
    if key in _QT_NAMED:
        return _QT_NAMED[key]
    if QtCore.Qt.Key_F1 <= key <= QtCore.Qt.Key_F35:
        return f"f{key - QtCore.Qt.Key_F1 + 1}"
    if QtCore.Qt.Key_A <= key <= QtCore.Qt.Key_Z:
        return chr(ord("a") + key - QtCore.Qt.Key_A)
    if QtCore.Qt.Key_0 <= key <= QtCore.Qt.Key_9:
        return chr(ord("0") + key - QtCore.Qt.Key_0)
    return None


def _compose(tokens) -> str:
    """Canonical 'ctrl+alt+shift+win+<key>' ordering from a set of tokens."""
    mods = sorted((t for t in tokens if t in _MOD_ORDER), key=lambda t: _MOD_ORDER[t])
    keys = [t for t in tokens if t not in _MOD_ORDER]
    return "+".join(mods + keys)


def pretty_hotkey(value: str) -> str:
    """'ctrl+win' -> 'Ctrl + Win'. Display only — config keeps the canonical form.

    The modifier names are per-platform (``Win`` vs ``Cmd``), so the table lives
    in :mod:`rekounts.ui.platform_text`; this stays as the name the Hub and its
    tests already import.
    """
    return platform_text.pretty_hotkey(value)


class HotkeyCaptureEdit(QtWidgets.QLineEdit):
    """Press-keys-to-capture field. Only ever commits a valid hotkey, so a typo
    can never reach config.json and brick startup (the old free-text failure).

    Emits ``hotkeyChanged(str)`` when a new valid combo is committed — that is
    what drives instant-apply.
    """

    hotkeyChanged = QtCore.Signal(str)

    def __init__(self, initial=""):
        super().__init__()
        self.setObjectName("HotkeyEdit")
        self.setReadOnly(True)
        self.setPlaceholderText("Click, then press your keys…")
        self._hotkey = initial or DEFAULT_HOTKEY
        self._held = {}       # Qt key code -> token, currently down
        self._preview = ""
        self.setText(pretty_hotkey(self._hotkey))

    def hotkey(self) -> str:
        return self._hotkey

    def set_hotkey(self, value: str):
        changed = value != self._hotkey
        self._hotkey = value
        self._held.clear()
        self._preview = ""
        self.setText(pretty_hotkey(value))
        if changed:
            self.hotkeyChanged.emit(value)

    def focusInEvent(self, e):
        super().focusInEvent(e)
        self._held.clear()
        self._preview = ""
        self.setText("Press your keys…")

    def focusOutEvent(self, e):
        super().focusOutEvent(e)
        # discard any half-typed combo
        self.setText(pretty_hotkey(self._hotkey))

    def keyPressEvent(self, e):
        if e.isAutoRepeat():
            return
        token = _qt_event_to_token(e)
        if token is None:
            return
        self._held[e.key()] = token
        self._preview = _compose(self._held.values())
        self.setText(pretty_hotkey(self._preview) or "…")
        e.accept()

    def keyReleaseEvent(self, e):
        if e.isAutoRepeat():
            return
        if e.key() not in self._held:
            return
        # Commit when the first key of the chord lifts (combo at its maximum).
        combo = self._preview
        self._held.clear()
        if combo and is_valid_hotkey(combo):
            changed = combo != self._hotkey
            self._hotkey = combo
            self.setText(pretty_hotkey(combo))
            if changed:
                self.hotkeyChanged.emit(combo)
        else:
            self.setText("Unsupported combo — try again")
        e.accept()


# ================================================================== switch
def _lerp_color(c1: str, c2: str, t: float) -> QtGui.QColor:
    a, b = QtGui.QColor(c1), QtGui.QColor(c2)
    return QtGui.QColor(
        round(a.red() + (b.red() - a.red()) * t),
        round(a.green() + (b.green() - a.green()) * t),
        round(a.blue() + (b.blue() - a.blue()) * t))


class ToggleSwitch(QtWidgets.QCheckBox):
    """A monochrome switch. It is a QCheckBox underneath, so isChecked(),
    setChecked() and toggled() behave exactly as any caller expects — only the
    painting differs (a stock checkbox in a settings row reads as a form, not
    as an app)."""

    W, H = 38, 22

    def __init__(self, checked=False):
        super().__init__()
        self.setFixedSize(self.W, self.H)
        self.setCursor(QtCore.Qt.PointingHandCursor)
        self.setChecked(bool(checked))
        self._knob = 1.0 if self.isChecked() else 0.0
        self._anim = QtCore.QPropertyAnimation(self, b"knob", self)
        self._anim.setDuration(130)
        self._anim.setEasingCurve(QtCore.QEasingCurve.OutCubic)
        self.toggled.connect(self._animate)

    # animated knob position, 0.0 (off) .. 1.0 (on)
    def _get_knob(self) -> float:
        return self._knob

    def _set_knob(self, value: float):
        self._knob = float(value)
        self.update()

    knob = QtCore.Property(float, _get_knob, _set_knob)

    def _animate(self, on: bool):
        self._anim.stop()
        self._anim.setStartValue(self._knob)
        self._anim.setEndValue(1.0 if on else 0.0)
        self._anim.start()

    def set_state_silently(self, checked: bool):
        """Set the switch WITHOUT emitting toggled (and snap the knob to match),
        for reconciling the UI to a state that changed outside the app (e.g. a
        launch-at-login toggle flipped in Task Manager)."""
        checked = bool(checked)
        self.blockSignals(True)
        self.setChecked(checked)
        self.blockSignals(False)
        self._knob = 1.0 if checked else 0.0
        self.update()

    def enterEvent(self, e):
        super().enterEvent(e)
        self.update()

    def leaveEvent(self, e):
        super().leaveEvent(e)
        self.update()

    def paintEvent(self, _):
        p = QtGui.QPainter(self)
        p.setRenderHint(QtGui.QPainter.Antialiasing)
        t = max(0.0, min(1.0, self._knob))
        radius = self.H / 2 - 0.5

        highlight = self.hasFocus() or self.underMouse()
        p.setPen(QtGui.QPen(QtGui.QColor(
            theme.TEXT_2 if highlight else theme.BORDER), 1))
        p.setBrush(_lerp_color(theme.CARD, theme.ACCENT, t))
        p.drawRoundedRect(QtCore.QRectF(0.5, 0.5, self.W - 1, self.H - 1),
                          radius, radius)

        d = self.H - 8
        x = 4 + t * (self.W - d - 8)
        p.setPen(QtCore.Qt.NoPen)
        p.setBrush(_lerp_color(theme.TEXT_2, theme.BG, t))
        p.drawEllipse(QtCore.QRectF(x, 4, d, d))


# ============================================================ rows & sections
class SettingsRow(QtWidgets.QWidget):
    """Title (+ optional tag and hint) on the left, one control on the right."""

    def __init__(self, title, control, hint="", tag=""):
        super().__init__()
        self.setObjectName("Row")
        lay = QtWidgets.QHBoxLayout(self)
        lay.setContentsMargins(12, 11, 12, 11)
        lay.setSpacing(16)

        left = QtWidgets.QVBoxLayout()
        left.setContentsMargins(0, 0, 0, 0)
        left.setSpacing(3)
        title_row = QtWidgets.QHBoxLayout()
        title_row.setContentsMargins(0, 0, 0, 0)
        title_row.setSpacing(7)
        label = QtWidgets.QLabel(title)
        label.setProperty("role", "row-title")
        title_row.addWidget(label)
        if tag:
            chip = QtWidgets.QLabel(tag.upper())
            chip.setProperty("role", "tag")
            title_row.addWidget(chip)
        title_row.addStretch(1)
        left.addLayout(title_row)

        self.hint = QtWidgets.QLabel(hint)
        self.hint.setProperty("role", "row-hint")
        self.hint.setWordWrap(True)
        self.hint.setVisible(bool(hint))
        left.addWidget(self.hint)
        lay.addLayout(left, 1)

        if isinstance(control, QtWidgets.QLayout):
            lay.addLayout(control)
        else:
            lay.addWidget(control, 0, QtCore.Qt.AlignVCenter)

        # Every control on this page arrives through a row, so guarding here is
        # what makes a new dropdown safe by default: the wheel scrolls the page
        # instead of silently editing whatever the pointer happens to rest on.
        # Runs after the control is parented in, so a row given a whole layout
        # is covered as thoroughly as a row given a single widget.
        guard_wheel(self)

    def set_hint(self, text):
        self.hint.setText(text)
        self.hint.setVisible(bool(text))


class Section(QtWidgets.QWidget):
    """A titled card of rows, separated by hairlines."""

    def __init__(self, title):
        super().__init__()
        outer = QtWidgets.QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(9)

        head = QtWidgets.QLabel(title.upper())
        head.setProperty("role", "section")
        outer.addWidget(head)

        card = QtWidgets.QWidget()
        card.setObjectName("Card")
        # A 6px inset means a row's hover fill never pokes out of the card's
        # rounded corners.
        self._rows = QtWidgets.QVBoxLayout(card)
        self._rows.setContentsMargins(6, 6, 6, 6)
        self._rows.setSpacing(0)
        outer.addWidget(card)

    def add(self, row):
        if self._rows.count():
            sep = QtWidgets.QFrame()
            sep.setObjectName("RowSep")
            sep.setFixedHeight(1)
            self._rows.addWidget(sep)
        self._rows.addWidget(row)
        return row


# ============================================================== microphones
def _fallback_microphones() -> list[tuple[str, str]]:
    """Deduped input-capable devices straight from sounddevice."""
    try:
        import sounddevice as sd
    except Exception as e:
        log.warning("sounddevice unavailable, no microphone list: %s", e)
        return []
    try:
        devices = sd.query_devices()
    except Exception as e:
        log.warning("could not query audio devices: %s", e)
        return []
    seen, out = set(), []
    for d in devices:
        name = d.get("name") if isinstance(d, dict) else None
        channels = d.get("max_input_channels", 0) if isinstance(d, dict) else 0
        if name and channels > 0 and name not in seen:
            seen.add(name)
            out.append((name, name))
    return out


def _normalize_mic_entries(entries) -> list[tuple[str, str]]:
    """Accept whatever shape list_microphones() returns and make it (label, name).

    The sibling contract is being written in a parallel branch, so this takes
    plain names, (label, name) pairs, or dicts rather than assuming one.
    """
    out = []
    for entry in entries or []:
        if isinstance(entry, str):
            out.append((entry, entry))
        elif isinstance(entry, dict):
            name = entry.get("name") or entry.get("device")
            if name:
                out.append((entry.get("label") or name, name))
        elif isinstance(entry, (tuple, list)) and entry:
            label = str(entry[0])
            name = entry[1] if len(entry) > 1 and isinstance(entry[1], str) else label
            out.append((label, name))
    return out


def microphone_options() -> list[tuple[str, str]]:
    """[(label, device name)] for the dropdown — one entry per real microphone.

    Prefers ``device_utils.list_microphones()`` (a parallel session's contract,
    which filters Windows pseudo-devices). Falls back to a deduped sounddevice
    scan when that function isn't on this branch yet.
    """
    try:
        from rekounts import device_utils
        lister = getattr(device_utils, "list_microphones", None)
        if callable(lister):
            return _normalize_mic_entries(lister())
    except Exception:
        log.exception("list_microphones() failed; falling back to raw device scan")
    return _fallback_microphones()


# ================================================================ the page
class SettingsPage(QtWidgets.QWidget):
    """Every setting the app has, applied the moment you change it.

    ``on_saved`` is called with no arguments after a change has been persisted —
    the same live-apply contract the old settings window had.
    """

    # Coalesce bursts of changes (dragging a spinbox, flipping three switches)
    # into one live-apply. Persistence is never delayed, only the callback.
    APPLY_DELAY_MS = 250

    _MODEL_HINT = ("Bigger models are more accurate and slower — Small is a good "
                   "all-round default. A model downloads once, the first time "
                   "you pick it, and you can keep dictating while it loads.")
    test_done = QtCore.Signal(str)
    # Pending-apply text, emitted so set_status() is safe to call from the
    # worker thread a model reload finishes on.
    _status_changed = QtCore.Signal(str)

    def __init__(self, config, history=None, on_saved=None, startup_setter=None,
                 startup_getter=None, on_send_feedback=None,
                 gpu_choice=None):
        super().__init__()
        self.config = config
        self.history = history
        # Whether to draw the Processing row at all. False in every packaged
        # build and on every Mac, where the choice cannot change what happens —
        # see platform_text.gpu_choice_applies. Injectable so both branches are
        # testable from one machine without freezing anything.
        self._gpu_choice = (platform_text.gpu_choice_applies()
                            if gpu_choice is None else bool(gpu_choice))
        self._on_saved = on_saved or (lambda: None)
        # Optional, like the tray's: the default opens the review dialog, and a
        # caller (or a test) can substitute its own handler.
        self._on_send_feedback = on_send_feedback or self._open_feedback_dialog
        self._startup_setter = startup_setter or _default_startup_setter
        # Reads the REAL launch-at-login state (production wires the registry
        # query in via the Dashboard). Defaults to the stored flag so tests and
        # standalone construction stay hermetic — no registry access.
        self._startup_getter = startup_getter or (
            lambda: bool(self.config.get("launch_on_startup")))
        # Replaced by __main__ with the live pad's own clear; see
        # set_scratchpad_clearer.
        self._scratchpad_clearer = self._clear_scratchpad_file

        self._apply_timer = QtCore.QTimer(self)
        self._apply_timer.setSingleShot(True)
        self._apply_timer.setInterval(self.APPLY_DELAY_MS)
        self._apply_timer.timeout.connect(self._flush_apply)
        self._status_changed.connect(self._apply_status)

        root = QtWidgets.QVBoxLayout(self)
        left, top, right, bottom = theme.PAGE_MARGINS
        root.setContentsMargins(left, top, 0, 0)
        root.setSpacing(14)

        title = QtWidgets.QLabel("Settings")
        title.setProperty("role", "page-title")
        root.addWidget(title)

        # Pending-apply strip. Hidden until something is genuinely deferred (a
        # model reload in flight, a mic change made mid-recording). Deliberately
        # NOT a toast: toasts are gated by the notifications switch, and with
        # that switch off the multi-second model reload was invisible — the
        # user kept dictating on the old model with nothing on screen to say so.
        self.status = QtWidgets.QLabel("")
        self.status.setProperty("role", "row-hint")
        self.status.setWordWrap(True)
        self.status.setVisible(False)
        root.addWidget(self.status)

        scroll = QtWidgets.QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)
        body = QtWidgets.QWidget()
        self._body = QtWidgets.QVBoxLayout(body)
        self._body.setContentsMargins(0, 0, right, bottom)
        self._body.setSpacing(22)
        scroll.setWidget(body)
        root.addWidget(scroll, 1)

        self._build_general()
        self._build_audio()
        self._build_behavior()
        self._build_system()
        self._build_privacy()
        self._body.addStretch(1)

        # Backstop. SettingsRow already guards everything it is handed; this
        # catches a control that ever reaches the page by some other route,
        # because on a page this tall an unguarded dropdown is a live setting
        # wired to the scroll gesture.
        guard_wheel(self)

    # -------------------------------------------------------- pending status
    @QtCore.Slot(str)
    def set_status(self, text):
        """Show (or clear, with "") what has NOT been applied yet.

        Called from the app's live-apply, which can reach here off the GUI
        thread (a model reload finishes on a worker), so it hops through a
        signal like the overlay does.
        """
        self._status_changed.emit(text or "")

    @QtCore.Slot(str)
    def _apply_status(self, text):
        self.status.setText(text)
        self.status.setVisible(bool(text))

    # ----------------------------------------------------------- persistence
    def _persist(self, key, value):
        """Write one setting, then schedule the live-apply."""
        self.config.set(key, value)
        try:
            self.config.save()
        except Exception:
            log.exception("could not write config.json")
            return
        self._schedule_apply()

    def _schedule_apply(self):
        """Coalesce a burst of changes into one apply — but never postpone one.

        QTimer.start() RESTARTS a running timer, so the old code re-armed the
        full delay on every change: working down the page, or dragging a
        spinbox, kept pushing the apply further away for as long as the user
        kept touching settings. That is the "it took a few seconds" the report
        describes. Letting a running timer run out instead bounds the wait at
        APPLY_DELAY_MS from the FIRST unapplied change, and anything changed
        after it fires is picked up by the next one.
        """
        if not self._apply_timer.isActive():
            self._apply_timer.start()

    def _flush_apply(self):
        """Run the app's live-apply now. Never lets a failure escape into Qt."""
        self._apply_timer.stop()
        try:
            self._on_saved()
        except Exception:
            log.exception("live-apply callback failed")

    def hideEvent(self, e):
        # Changing a setting and immediately closing the Hub must still apply.
        super().hideEvent(e)
        if self._apply_timer.isActive():
            self._flush_apply()

    # -------------------------------------------------------- control makers
    def _switch(self, key, on_change=None):
        sw = ToggleSwitch(bool(self.config.get(key)))

        def handler(checked, key=key):
            self._persist(key, bool(checked))
            if on_change:
                on_change(bool(checked))

        sw.toggled.connect(handler)
        return sw

    def _combo(self, items, current, on_change, width=None):
        """items: [(label, value)]. on_change receives the selected value."""
        box = QtWidgets.QComboBox()
        for label, value in items:
            box.addItem(label, value)
        idx = box.findData(current)
        box.setCurrentIndex(idx if idx >= 0 else 0)
        box.setFixedWidth(width or theme.CONTROL_W)
        box.currentIndexChanged.connect(
            lambda _i, b=box: on_change(b.currentData()))
        return box

    @staticmethod
    def _ghost(text, slot):
        btn = QtWidgets.QPushButton(text)
        btn.setObjectName("Ghost")
        btn.clicked.connect(slot)
        return btn

    # ------------------------------------------------------------- General
    def _build_general(self):
        sec = Section("General")

        self.hotkey = HotkeyCaptureEdit(self.config.get("hotkey"))
        self.hotkey.setFixedWidth(theme.CONTROL_W - 78)
        self.hotkey.hotkeyChanged.connect(self._hotkey_changed)
        reset = self._ghost("Reset", lambda: self.hotkey.set_hotkey(DEFAULT_HOTKEY))
        reset.setFixedWidth(70)
        hk = QtWidgets.QHBoxLayout()
        hk.setContentsMargins(0, 0, 0, 0)
        hk.setSpacing(8)
        hk.addWidget(self.hotkey)
        hk.addWidget(reset)
        self.hotkey_row = sec.add(SettingsRow(
            "Dictation hotkey", hk,
            "Hold to talk · double-tap for hands-free · tap again to stop."))

        self.language = self._combo(
            list(LANGUAGES),
            self.config.get("language"),
            lambda v: self._persist("language", v))
        sec.add(SettingsRow("Language", self.language,
                            "Auto-detect costs a little accuracy — pick a "
                            "language if you always dictate in one."))

        # distil-large-v3 / large-v3-turbo return to this list once their files
        # are published to the release-host manifest (rekounts/models.py) —
        # offering a model the host can't serve is a dead dropdown entry.
        self.model = self._combo(
            [("Base — fastest, least accurate", "base"),
             ("Small — balanced (recommended)", "small"),
             ("Medium — more accurate, slower", "medium")],
            self.config.get("model"),
            self._model_changed)
        self.model_row = sec.add(SettingsRow(
            "Speech model", self.model, self._MODEL_HINT))

        # Processing is drawn only where picking Auto could actually change
        # something. In a packaged build the CUDA stack is excluded from the
        # bundle and the probe cannot even run (Rekounts.spec, transcriber.py),
        # and on a Mac the speech engine has no accelerator backend at all — so
        # for everyone who downloaded the app, Auto was CPU and the row was
        # advertising GPU libraries the build could never load.
        self.device = None
        self.device_row = None
        if self._gpu_choice:
            self.device = self._combo(
                [("CPU — works everywhere", "cpu"),
                 ("Auto — use the GPU when it can", "auto")],
                self.config.get("device"),
                lambda v: self._persist("device", v))
            self.device_row = sec.add(SettingsRow(
                "Processing", self.device, platform_text.processing_hint()))

        self._body.addWidget(sec)

    def _hotkey_changed(self, combo):
        # Belt-and-suspenders: the capture widget only ever emits valid combos,
        # but an invalid hotkey in config.json breaks the listener at startup.
        if not is_valid_hotkey(combo):
            self.hotkey_row.set_hint(f"“{combo}” isn’t a usable hotkey — not saved.")
            return
        self.hotkey_row.set_hint(
            "Hold to talk · double-tap for hands-free · tap again to stop.")
        self._persist("hotkey", combo)

    def _model_changed(self, value):
        self._persist("model", value)

    # --------------------------------------------------------------- Audio
    def _build_audio(self):
        sec = Section("Audio")

        self.mic = QtWidgets.QComboBox()
        self.mic.setFixedWidth(theme.CONTROL_W)
        self._populate_mics(self.config.get("microphone"))
        self.mic.currentIndexChanged.connect(
            lambda _i: self._persist("microphone", self.mic.currentData()))

        self.refresh_btn = self._ghost("Refresh", self._refresh_mics)
        self.test_btn = self._ghost("Test", self._test_mic)
        mic_col = QtWidgets.QVBoxLayout()
        mic_col.setContentsMargins(0, 0, 0, 0)
        mic_col.setSpacing(8)
        mic_col.addWidget(self.mic, 0, QtCore.Qt.AlignRight)
        btns = QtWidgets.QHBoxLayout()
        btns.setContentsMargins(0, 0, 0, 0)
        btns.setSpacing(8)
        btns.addStretch(1)
        btns.addWidget(self.refresh_btn)
        btns.addWidget(self.test_btn)
        mic_col.addLayout(btns)

        self.mic_row = sec.add(SettingsRow(
            "Microphone", mic_col, platform_text.mic_default_hint()))
        self.test_done.connect(self._show_test_result)

        # Sound effects live HERE, not under System where they used to sit —
        # "Audio" is where someone hunting for the off switch actually looks,
        # and burying it three sections down is most of why it read as missing.
        self.sound_effects = self._switch(
            "sound_effects", on_change=self._sync_volume_availability)
        sec.add(SettingsRow(
            "Sound effects", self.sound_effects,
            "A short, quiet tone when dictation starts and stops. Off means "
            "completely silent."))

        self.sound_volume = self._combo(
            [("Soft", sounds.VOLUME_SOFT),
             ("Normal", sounds.VOLUME_NORMAL),
             ("Loud", sounds.VOLUME_LOUD)],
            _nearest_volume(self.config.get("sound_volume")),
            lambda v: self._persist("sound_volume", float(v)))
        # No hint while the cues are on. The row used to say "Applies to the
        # next cue — no restart", which answers a question nobody choosing a
        # volume level was asking; it planted the doubt instead of removing one.
        self.volume_row = sec.add(SettingsRow("Volume", self.sound_volume))
        self._sync_volume_availability(bool(self.config.get("sound_effects")))

        self._body.addWidget(sec)

    def _sync_volume_availability(self, sounds_on):
        """Volume is meaningless while the cues are off — grey it out and say so
        rather than leaving a live-looking control that changes nothing."""
        self.sound_volume.setEnabled(bool(sounds_on))
        self.volume_row.set_hint(
            "" if sounds_on else "Turn sound effects on to change the volume.")

    def _populate_mics(self, selected):
        """(Re)fill the dropdown, keeping the current selection if it still exists."""
        self.mic.blockSignals(True)
        self.mic.clear()
        self.mic.addItem("System default", None)
        for label, name in microphone_options():
            self.mic.addItem(label, name)
        idx = self.mic.findData(selected)
        if idx >= 0:
            self.mic.setCurrentIndex(idx)
        self.mic.blockSignals(False)

    def _refresh_mics(self):
        self._populate_mics(self.mic.currentData())
        self.mic_row.set_hint("Microphone list refreshed.")

    def showEvent(self, e):
        # The device list is frozen at construction; re-query each time the page
        # is shown so hot-plugged mics appear without a restart.
        super().showEvent(e)
        self._populate_mics(self.mic.currentData() or self.config.get("microphone"))
        # Likewise re-check launch-at-login, so a Task Manager disable made since
        # the page was built is reflected rather than shown stale.
        self._sync_launch_switch()

    def _test_mic(self):
        self.test_btn.setEnabled(False)
        self.mic_row.set_hint("Listening…")
        import threading
        threading.Thread(target=self._run_test, args=(self.mic.currentData(),),
                         daemon=True).start()

    def _run_test(self, name):
        try:
            import numpy as np
            import sounddevice as sd

            from rekounts.audio_utils import normalize_gain
            index = resolve_input_device(name, sd.query_devices())
            rec = sd.rec(int(2 * 16000), samplerate=16000, channels=1,
                         dtype="float32", device=index)
            sd.wait()
            audio = normalize_gain(rec.flatten())
            rms = float(np.sqrt(np.mean(audio ** 2))) if len(audio) else 0.0
            self.test_done.emit(_LEVEL_MESSAGES[classify_level(rms)])
        except Exception as e:
            self.test_done.emit(f"Microphone error: {e}")

    @QtCore.Slot(str)
    def _show_test_result(self, msg):
        self.mic_row.set_hint(msg)
        self.test_btn.setEnabled(True)

    # ------------------------------------------------------------ Behavior
    def _build_behavior(self):
        sec = Section("Behavior")

        self.insertion = self._combo(
            [("Paste — fastest", "paste"), ("Type keystrokes", "keystroke")],
            self.config.get("insertion_mode"),
            lambda v: self._persist("insertion_mode", v))
        sec.add(SettingsRow(
            "Insert text by", self.insertion,
            "Keystrokes are slower but work in apps that block paste."))

        self.long_text_via_paste = self._switch("long_text_via_paste")
        sec.add(SettingsRow(
            "Paste long dictations", self.long_text_via_paste,
            platform_text.long_text_hint()))

        self.strip_fillers = self._switch("strip_fillers")
        sec.add(SettingsRow("Remove filler words", self.strip_fillers,
                            "Drops “um” and “uh”."))
        self.strip_discourse = self._switch("strip_discourse_fillers")
        sec.add(SettingsRow(
            "Remove hedge phrases", self.strip_discourse,
            "Drops “you know”, “I mean”, “like”, “right” when commas mark "
            "them as asides — “I like it” is never touched."))
        self.auto_cap = self._switch("auto_capitalize")
        sec.add(SettingsRow("Auto-capitalize sentences", self.auto_cap))
        self.fix_punct = self._switch("fix_punctuation_spacing")
        sec.add(SettingsRow("Fix punctuation spacing", self.fix_punct))
        self.collapse_repeats = self._switch("collapse_repeats")
        sec.add(SettingsRow("Remove repeated words", self.collapse_repeats,
                            "Collapses accidental stutters (“the the” → “the”)."))

        # Titled for what it does, not for the technique. "Pre-roll buffer" is
        # the name in the code; nobody scanning Settings for "it clips my first
        # word" was going to recognise it.
        self.preroll = self._switch("preroll_enabled")
        sec.add(SettingsRow(
            "Catch the first word", self.preroll, platform_text.preroll_hint()))

        self.max_minutes = QtWidgets.QSpinBox()
        self.max_minutes.setRange(0, 120)
        self.max_minutes.setSuffix(" min")
        self.max_minutes.setSpecialValueText("No limit")
        self.max_minutes.setFixedWidth(110)
        self.max_minutes.setValue(
            int(round((self.config.get("max_recording_seconds") or 0) / 60)))
        self.max_minutes.valueChanged.connect(
            lambda v: self._persist("max_recording_seconds", int(v) * 60))
        sec.add(SettingsRow(
            "Maximum recording length", self.max_minutes,
            "Safety net for a hands-free recording you forget to stop."))

        self.filter_halluc = self._switch("filter_hallucinations")
        sec.add(SettingsRow(
            "Ignore phantom phrases", self.filter_halluc,
            "Silence sometimes transcribes as “Thanks for watching.” — dropped "
            "when the model itself reports it heard no speech there."))

        self._body.addWidget(sec)

    # -------------------------------------------------------------- System
    def _build_system(self):
        sec = Section("System")

        # Start from the REAL launch-at-login state, not just the stored flag:
        # if the user disabled us in Task Manager's Startup tab, Windows skips us
        # at login and this switch must say so rather than still reading ON.
        # (On macOS the backend is a LaunchAgent plist, and its presence IS the
        # state — rekounts/startup.py; the same getter covers both.)
        try:
            launch_on = bool(self._startup_getter())
        except Exception:
            launch_on = bool(self.config.get("launch_on_startup"))
        self.launch_startup = ToggleSwitch(launch_on)
        self.launch_startup.toggled.connect(self._launch_toggled)
        self.startup_row = sec.add(SettingsRow(
            "Launch at login", self.launch_startup,
            platform_text.launch_at_login_hint()))

        self.show_pill = self._switch("show_pill")
        sec.add(SettingsRow("Show dictation pill", self.show_pill,
                            "The small recording indicator at the bottom of the screen."))

        self.scratchpad = self._switch("scratchpad_enabled")
        sec.add(SettingsRow(
            "Scratchpad", self.scratchpad, platform_text.scratchpad_hint()))

        self.notifications = self._switch("show_notifications")
        sec.add(SettingsRow("Tray notifications", self.notifications,
                            "Messages like “Settings applied.” and error reports."))

        # The app's only optional network access, so the description says
        # plainly what turning it on does — see docs/privacy.md. Takes effect at
        # the next launch: the check is scheduled once, when the tray is built.
        self.auto_updates = self._switch("auto_check_updates")
        sec.add(SettingsRow(
            "Check for updates automatically", self.auto_updates,
            "When on, Rekounts asks GitHub once per launch whether there is a "
            "newer release, and only speaks up if there is."))

        self._body.addWidget(sec)

    def _launch_toggled(self, checked):
        """User flipped the switch: persist intent, then apply it to the registry
        (enable() also clears any Task Manager disable, so ON actually takes)."""
        self._persist("launch_on_startup", bool(checked))
        self._apply_startup(bool(checked))

    def _apply_startup(self, enabled):
        """Write the registry entry too, so the switch is true immediately
        rather than at the next launch."""
        try:
            self._startup_setter(bool(enabled))
        except Exception as e:
            log.warning("could not update launch-at-login entry: %s", e)
            self.startup_row.set_hint(f"Could not update the login entry: {e}")

    def _sync_launch_switch(self):
        """Re-reflect the real launch-at-login state whenever Settings is shown,
        so a Task Manager disable done while the app was running is picked up.
        Does NOT call the setter — flipping the visible switch here must not
        rewrite the registry, only mirror it (and keep config honest so an
        unrelated Save can't re-apply a stale value)."""
        try:
            real = bool(self._startup_getter())
        except Exception:
            return
        if real == self.launch_startup.isChecked():
            return
        self.launch_startup.set_state_silently(real)
        self.config.set("launch_on_startup", real)
        try:
            self.config.save()
        except Exception:
            log.exception("could not persist reconciled launch_on_startup")

    # ------------------------------------------------------- Data & Privacy
    def _build_privacy(self):
        sec = Section("Data & Privacy")

        self.history_enabled = self._switch("history_enabled", self._apply_history)
        sec.add(SettingsRow(
            "Save dictation history", self.history_enabled,
            "Off means no dictation is saved to your history — the Dictation page stays "
            "empty. The Scratchpad keeps its own note either way; clear it "
            "below."))

        self.clear_btn = QtWidgets.QPushButton("Clear all…")
        self.clear_btn.setObjectName("Danger")
        self.clear_btn.clicked.connect(self._clear_history)
        self.clear_row = sec.add(SettingsRow(
            "Clear saved dictations", self.clear_btn, self._history_count_hint()))

        # The Scratchpad autosaves what you write into it, including dictated
        # text, and it does NOT follow the history switch above — see the note on
        # _clear_scratchpad. That makes it the one piece of your text with no way
        # to see it or get rid of it from here, which is what this row fixes.
        self.clear_note_btn = QtWidgets.QPushButton("Clear note…")
        self.clear_note_btn.setObjectName("Danger")
        self.clear_note_btn.clicked.connect(self._clear_scratchpad)
        self.scratchpad_row = sec.add(SettingsRow(
            "Scratchpad note", self.clear_note_btn, self._scratchpad_hint()))

        data_dir = str(default_config_path().parent)
        open_btn = self._ghost("Open folder", lambda: self._open_folder(data_dir))
        sec.add(SettingsRow("Where your data lives", open_btn, data_dir))

        # Someone asked for their log — in an issue, or in a reply to their own
        # feedback — needs to be able to find it without being walked through
        # %APPDATA% over email.
        log_dir = str(paths.logs_dir())
        log_btn = self._ghost("Open folder", self._open_log_folder)
        sec.add(SettingsRow(
            "Diagnostic log", log_btn,
            "Startup, model loading and errors — never your transcripts. "
            f"{log_dir}"))

        # Reachable from the tray menu too; both land in the same dialog, which
        # shows you everything before anything moves.
        feedback_btn = self._ghost("Send feedback…", self._send_feedback)
        sec.add(SettingsRow(
            "Feedback and bug reports", feedback_btn,
            "Opens a prefilled GitHub issue or an email, in your browser or "
            "mail client. Rekounts sends nothing itself."))

        self._body.addWidget(sec)

        note = QtWidgets.QLabel(NETWORK_STATEMENT)
        note.setWordWrap(True)
        note.setProperty("role", "hint")
        self._body.addWidget(note)

    def _history_count_hint(self) -> str:
        try:
            n = self.history.count() if self.history else 0
        except Exception:
            return ""
        if not n:
            return "Nothing saved yet."
        return f"{n} dictation{'' if n == 1 else 's'} saved on this machine."

    def _apply_history(self, enabled):
        # History.enabled is deliberately mutable so the privacy switch takes
        # effect on the very next dictation, with no rebuild and no restart.
        if self.history is not None:
            self.history.enabled = bool(enabled)

    # ------------------------------------------------------- the Scratchpad
    def set_scratchpad_clearer(self, clearer):
        """Point **Clear note** at the live pad instead of at the file.

        Wired by __main__ once the pad exists. It matters which one runs: an
        open pad autosaves on a pause in typing, so deleting scratchpad.json
        underneath it would just get the note written straight back out. Without
        this the page falls back to clearing the file, which is correct in every
        situation where there is no pad to ask — tests, the Hub opened
        standalone, and a build where the feature is off.
        """
        self._scratchpad_clearer = clearer

    def _scratchpad_hint(self) -> str:
        """Say whether there is a note, and that it saved itself. Never raises.

        Names the file rather than the full path — "Where your data lives" is
        the next row down and already has the folder. What the user cannot work
        out for themselves is that the note is written without them asking.
        """
        try:
            if not ScratchpadStore().load().get("html", "").strip():
                return "Nothing written yet."
            return ("Saved automatically to scratchpad.json in your data "
                    "folder, as you type.")
        except Exception:
            return ""

    def _clear_scratchpad(self):
        """Empty the note, after asking.

        Why this is a separate control rather than something the "Save dictation
        history" switch turns off:

        The history is a RECORD the app keeps of what you dictated — passive,
        automatic, and something you can plausibly want never to exist. The
        Scratchpad is a DOCUMENT you are writing. Its text is on screen in front
        of you and you expect it to still be there tomorrow, exactly like an
        unsaved file in an editor. Wiring it to the history switch would mean
        that turning on a privacy setting silently threw away an open note; that
        is data loss wearing a privacy hat, and no user asking for "don't record
        my dictations" is asking for "and delete what I am writing".

        So it gets its own explicit action instead — visible in the same place,
        clearly labelled, and confirmed before anything is deleted. The claim
        docs/privacy.md has to be able to make is "you can see it and you can
        get rid of it", and that is what this satisfies.
        """
        ok = QtWidgets.QMessageBox.question(
            self, "Clear the Scratchpad note",
            "Permanently delete everything in the Scratchpad? This cannot be "
            "undone.",
            QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No,
            QtWidgets.QMessageBox.No)
        if ok != QtWidgets.QMessageBox.Yes:
            return
        try:
            self._scratchpad_clearer()
        except Exception as e:
            log.warning("could not clear the scratchpad: %s", e)
            self.scratchpad_row.set_hint(f"Could not clear the note: {e}")
            return
        self.scratchpad_row.set_hint(self._scratchpad_hint())

    @staticmethod
    def _clear_scratchpad_file():
        """Fallback clearer: empty the note on disk.

        Writes an empty note rather than deleting the file, so the pad's next
        load takes the ordinary "you have a blank note" path instead of the
        missing-file one.
        """
        ScratchpadStore().save("", None)

    def _clear_history(self):
        if self.history is None or not self.history.count():
            return
        ok = QtWidgets.QMessageBox.question(
            self, "Clear all history",
            "Permanently delete every saved dictation? This cannot be undone.",
            QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No,
            QtWidgets.QMessageBox.No)
        if ok == QtWidgets.QMessageBox.Yes:
            self.history.clear_all()
            self.clear_row.set_hint(self._history_count_hint())

    def _open_log_folder(self):
        """Open the log folder, creating it first if logging never got that far.

        setup_logging() degrades to memory-only on a read-only %APPDATA%, which
        is exactly the state someone would be reporting — and an Open folder
        button that does nothing at all is the worst possible answer there.
        """
        log_dir = paths.logs_dir()
        try:
            log_dir.mkdir(parents=True, exist_ok=True)
        except Exception as e:
            log.warning("could not create the log folder: %s", e)
        self._open_folder(str(log_dir))

    def _send_feedback(self):
        """Never let a failure here escape into Qt — this is a help button."""
        try:
            self._on_send_feedback()
        except Exception:
            log.exception("could not open the feedback dialog")

    def _open_feedback_dialog(self):
        from rekounts.ui.feedback_dialog import show_feedback
        show_feedback(self.config, parent=self)

    @staticmethod
    def _open_folder(path):
        QtGui.QDesktopServices.openUrl(QtCore.QUrl.fromLocalFile(path))


def _default_startup_setter(enabled: bool):
    from rekounts import startup
    startup.set_enabled(bool(enabled))
