"""Global hotkey handling for Rekounts.

One physical hotkey drives every dictation gesture (Wispr Flow style):

  * HOLD  — press and keep held; release ends the recording (push-to-talk).
  * DOUBLE-TAP — two quick taps latch hands-free recording (stays on).
  * TAP while hands-free — a single tap stops it.
  * lone TAP while idle — no dictation; the tiny clip is discarded by the
    controller's min-duration guard and an optional hint is surfaced.

The tap/hold/double-tap classification lives in :class:`TapHoldGesture`, which
takes an injectable clock + scheduler so its timing can be unit-tested with a
fake clock. Combo detection lives in :class:`_Combo`, which fires clean
down/up edges and only reacts to keys that are actually part of the hotkey
(so releasing an unrelated key never ends a hold).

Platform note: pynput calls the Windows/Command key ``Key.cmd`` on every OS, so
the human token ``win`` (and ``super``/``meta``/``windows``) maps to ``<cmd>``.

Threading note: the OS delivers every key event on the thread that services the
low-level keyboard hook, and Windows silently *removes* a hook whose callback
runs long (past ``LowLevelHooksTimeout``, ~200-300 ms). So ``_on_press`` /
``_on_release`` do the bare minimum — canonicalize the key and hand it to a
:class:`_ThreadedDispatcher` — and everything expensive (combo matching, the
gesture machine, and above all opening the microphone stream) runs on a
dedicated worker thread. A :class:`HotkeyWatchdog` polls OS ground truth and
rebuilds the listener if the hook is ever lost anyway, so a dead hook no longer
means a dead hotkey for the rest of the session.
"""

import ctypes
import logging
import queue
import threading
import time

from pynput import keyboard

log = logging.getLogger(__name__)

# Default unified hotkey. Ctrl+Win matches Wispr Flow. Kept in sync with
# config.DEFAULTS["hotkey"].
DEFAULT_HOTKEY = "ctrl+win"

# Human token -> pynput modifier name. pynput uses `cmd` for the Windows key on
# Windows (and Command on macOS), so every "windows key" alias resolves to cmd.
_MODIFIER_ALIASES = {
    "ctrl": "ctrl", "control": "ctrl",
    "alt": "alt", "option": "alt", "opt": "alt",
    "shift": "shift",
    "cmd": "cmd", "command": "cmd",
    "win": "cmd", "windows": "cmd", "super": "cmd", "meta": "cmd",
}

# Human aliases for named (non-character) keys whose pynput Key name differs.
_NAMED_ALIASES = {
    "escape": "esc",
    "return": "enter",
    "del": "delete",
    "ins": "insert",
    "pgup": "page_up",
    "pgdn": "page_down",
    "capslock": "caps_lock",
    "spacebar": "space",
}


def _token_to_spec(token: str) -> str:
    """Convert one human key token to a pynput HotKey spec token.

    Raises ValueError for anything pynput could not parse (so callers can
    validate before saving instead of crashing at listener-start time).
    """
    token = token.strip().lower()
    if not token:
        raise ValueError("empty key token")
    if token in _MODIFIER_ALIASES:
        return f"<{_MODIFIER_ALIASES[token]}>"
    if token in _NAMED_ALIASES:
        return f"<{_NAMED_ALIASES[token]}>"
    if len(token) == 1:
        return token
    # A bare pynput Key name like "space", "f8", "enter".
    if hasattr(keyboard.Key, token):
        return f"<{token}>"
    raise ValueError(f"unknown key: {token!r}")


def parse_hotkey(hotkey: str):
    """Parse a human hotkey string ("ctrl+win", "f8") into canonical pynput keys.

    Returns a list of pynput Key/KeyCode objects (already in the canonical space
    the listener normalizes raw events into). Raises ValueError if invalid.
    """
    if not hotkey or not hotkey.strip():
        raise ValueError("empty hotkey")
    spec = "+".join(_token_to_spec(t) for t in hotkey.split("+"))
    keys = keyboard.HotKey.parse(spec)  # may raise ValueError itself
    if not keys:
        raise ValueError(f"no keys parsed from {hotkey!r}")
    return keys


def is_valid_hotkey(hotkey: str) -> bool:
    try:
        parse_hotkey(hotkey)
        return True
    except Exception:
        return False


def hotkey_warning(hotkey):
    """Return a human warning if ``hotkey`` is *legal but a bad idea*, else None.

    We deliberately do not suppress key events — suppressing a global hotkey
    system-wide would break that key for every other application. The
    consequence is that a hotkey which doubles as a common editing shortcut
    still fires that shortcut: holding Ctrl+A to push-to-talk also runs "select
    all" in the focused window, and the dictated text then REPLACES the
    selection. One modifier plus a single letter/digit is the whole family of
    combos where this bites (Ctrl+A/C/V/Z/S, Alt+F, ...), so that is what we
    warn about. Two-modifier combos (Ctrl+Shift+A) and the Ctrl+Win default
    collide with almost nothing and pass silently.

    Exposed as a plain function so the Hub's hotkey-capture widget can call it
    to warn at capture time without importing any of the listener machinery.
    """
    tokens = [t.strip().lower() for t in (hotkey or "").split("+") if t.strip()]
    if len(tokens) != 2:
        return None
    mods = [t for t in tokens if t in _MODIFIER_ALIASES]
    plain = [t for t in tokens if t not in _MODIFIER_ALIASES]
    if len(mods) != 1 or len(plain) != 1:
        return None
    key = plain[0]
    if len(key) != 1 or not (key.isascii() and key.isalnum()):
        return None
    combo = f"{mods[0].title()}+{key.upper()}"
    return (f"Heads-up: {combo} is also a common app shortcut. Rekounts does "
            f"not block it, so using it to dictate will ALSO trigger "
            f"{combo} in whatever window has focus. An F-key or Ctrl+Win is safer.")


# --- key identity --------------------------------------------------------
# Windows reports ctrl+<letter> as a C0 control character (ctrl+a arrives as
# '\x01'). pynput's win32 canonical() normally maps that back to 'a' via the
# event's scan code, but events that carry no scan code — injected input from
# remote-desktop clients, on-screen keyboards and macro tools all arrive as
# VK_PACKET — fall through to the generic path and stay '\x01', so a configured
# ctrl+a would silently never match. We therefore identify a key by a SET of
# tokens (named key / character / virtual-key code) and treat two keys as the
# same when their token sets intersect. Matching on the vk as well as the
# character also makes the combo independent of the character round-trip, which
# is the layout-sensitive part.
_C0_TO_LETTER = 0x60          # '\x01' + 0x60 == 'a'


def _key_tokens(key, raw=None) -> frozenset:
    """Every identity ``key`` may legitimately be recognised by.

    ``key`` is the canonical form; ``raw`` is the original event when there is
    one — canonical() discards the virtual-key code for character keys, so the
    vk has to be read off the raw event.
    """
    tokens = set()
    if isinstance(key, keyboard.Key):
        # Modifiers (and any other bare Key) are identified by name; canonical()
        # has already folded the left/right variants together.
        tokens.add(("key", key.name))
        # A Key keeps its vk on .value. Carrying it means a named key matches
        # whether or not the event went through canonical() — which turns a
        # non-modifier Key (f8, space) into a vk-only KeyCode.
        value_vk = getattr(key.value, "vk", None)
        if value_vk is not None:
            tokens.add(("vk", value_vk))

    chars = set()
    char = getattr(key, "char", None)
    if char:
        chars.add(char.lower())
        if len(char) == 1 and 0x01 <= ord(char) <= 0x1A:
            chars.add(chr(ord(char) + _C0_TO_LETTER))   # '\x01' -> 'a'
    for c in chars:
        tokens.add(("char", c))
        # ASCII letters and digits have a stable Windows virtual-key code
        # (VK_A == ord('A'), VK_0 == ord('0')), so the physical key matches too.
        if len(c) == 1 and c.isascii() and c.isalnum():
            tokens.add(("vk", ord(c.upper())))

    for source in (key, raw):
        # Key enum members have no .vk (it lives on .value), so this only picks
        # up KeyCodes — exactly what we want: a modifier must match by name, not
        # by a left/right-specific vk.
        vk = getattr(source, "vk", None)
        if vk is not None:
            tokens.add(("vk", vk))
    return frozenset(tokens)


# --- OS ground-truth key state (self-heal + watchdog) --------------------
# GetAsyncKeyState reads the *physical* key state below our hook, so it still
# tells the truth after Windows has removed the hook. We poll the combo's own
# keys with it — not GetLastInputInfo — so ordinary mouse activity never looks
# like hotkey input. A modifier can arrive as any of its left/right/generic
# virtual-key codes (pynput reports Shift as VK_LSHIFT, and the Windows key has
# no generic vk at all), so each modifier expands to its whole family: any one
# being down means the modifier is down.
_MODIFIER_VK_GROUPS = (
    frozenset({0x11, 0xA2, 0xA3}),   # ctrl  (VK_CONTROL / L / R)
    frozenset({0x12, 0xA4, 0xA5}),   # alt   (VK_MENU / L / R)
    frozenset({0x10, 0xA0, 0xA1}),   # shift (VK_SHIFT / L / R)
    frozenset({0x5B, 0x5C}),         # win   (VK_LWIN / VK_RWIN — no generic)
)


def _pollable_vks(req_tokens) -> frozenset:
    """Virtual-key codes to poll for one required combo key (see _key_tokens).

    Any one of them being physically down means that key is down. Modifier
    variants are all included so a right-hand modifier is never read as 'up'.
    """
    vks = {v for (t, v) in req_tokens if t == "vk"}
    out = set(vks)
    for v in vks:
        for group in _MODIFIER_VK_GROUPS:
            if v in group:
                out |= group
    return frozenset(out)


def _win_key_down(vk) -> bool:
    """True if key ``vk`` is physically down right now, per the OS.

    Best-effort: any failure (non-Windows, ctypes error) reads as 'not down'.
    The watchdog only acts on *sustained* readings, so a one-off glitch here
    cannot trigger a spurious rebuild or heal.
    """
    try:
        return bool(ctypes.windll.user32.GetAsyncKeyState(int(vk)) & 0x8000)
    except Exception:
        return False


# --- dispatch (get the slow work off the hook thread) --------------------
_STOP = object()   # sentinel: tell a dispatch worker to exit


class _ThreadedDispatcher:
    """Runs submitted callables in FIFO order on ONE dedicated daemon thread.

    This is the fix for the reported dead-hotkey: the start-recording path opens
    the microphone stream synchronously (tens to hundreds of ms), and running it
    inline on the hook thread is exactly what makes Windows drop chronically slow
    events and, on Win8+, remove the hook outright — silently, for the rest of
    the session. Here the hook thread only canonicalizes + ``submit``s
    (microseconds); the combo -> gesture -> controller work runs on this worker.
    A single worker preserves strict press/release ordering.
    """

    def __init__(self):
        self._q = queue.Queue()
        self._thread = None

    def start(self):
        if self._thread is not None:
            return
        self._thread = threading.Thread(
            target=self._run, name="rekounts-hotkey-dispatch", daemon=True)
        self._thread.start()

    def submit(self, fn):
        self._q.put(fn)

    def _run(self):
        while True:
            fn = self._q.get()
            if fn is _STOP:
                return
            try:
                fn()
            except Exception:
                log.exception("hotkey dispatch: event handler raised")

    def stop(self):
        if self._thread is None:
            return
        self._q.put(_STOP)
        self._thread = None


class _InlineDispatcher:
    """Runs each submission immediately on the calling thread.

    For unit tests (deterministic, no worker thread) and as a safe fallback.
    Production uses :class:`_ThreadedDispatcher` so the hook thread never blocks.
    """

    def start(self):
        pass

    def stop(self):
        pass

    def submit(self, fn):
        fn()


class _Combo:
    """Tracks whether the full hotkey combo is pressed, firing edge callbacks.

    Only keys that belong to the combo affect its state, so releasing an
    unrelated key while the combo is held does NOT fire ``on_up`` (the old bug
    where releasing any key ended a push-to-talk hold). Duplicate presses from
    OS key-repeat are idempotent.

    Required keys are stored as token sets (see :func:`_key_tokens`) rather than
    as pynput key objects, so a key still matches when the OS hands us a control
    character instead of a letter.
    """

    def __init__(self, keys, on_down, on_up):
        self._required = [_key_tokens(k) for k in keys]
        self._required_vks = [_pollable_vks(req) for req in self._required]
        self._pressed = set()          # indices into _required
        self._active = False
        self._on_down = on_down
        self._on_up = on_up
        # press/release run on the dispatch worker; reconcile()/active run on the
        # watchdog thread. The lock keeps _pressed/_active consistent between
        # them. Callbacks fire OUTSIDE the lock so a slow on_down (mic open) can
        # never block the watchdog's poll.
        self._lock = threading.RLock()

    @property
    def active(self) -> bool:
        with self._lock:
            return self._active

    def _match(self, key, raw):
        """Indices of the required keys this event satisfies."""
        tokens = _key_tokens(key, raw)
        return {i for i, req in enumerate(self._required) if req & tokens}

    def press(self, key, raw=None, now=None):
        with self._lock:
            hit = self._match(key, raw)
            if not hit:
                return
            self._pressed |= hit
            fire = not self._active and len(self._pressed) >= len(self._required)
            if fire:
                self._active = True
        if fire:
            if log.isEnabledFor(logging.DEBUG):
                log.debug("combo: down")
            self._on_down(now)

    def release(self, key, raw=None, now=None):
        with self._lock:
            hit = self._match(key, raw)
            if not hit:
                return
            self._pressed -= hit
            fire = self._active and len(self._pressed) < len(self._required)
            if fire:
                self._active = False
        if fire:
            if log.isEnabledFor(logging.DEBUG):
                log.debug("combo: up")
            self._on_up(now)

    def all_required_down(self, key_state) -> bool:
        """True iff every required key has at least one of its virtual-key codes
        physically down, per ``key_state(vk) -> bool`` (OS ground truth)."""
        for vks in self._required_vks:
            if not any(key_state(vk) for vk in vks):
                return False
        return True

    def reconcile(self, key_state) -> bool:
        """Self-heal a stuck ``active`` after a lost key-up.

        A dropped key-up event (focus change, a missed hook callback) leaves the
        combo believing it is still held, so a push-to-talk recording never ends
        and the next press is swallowed as idempotent. If we think the combo is
        held but the OS says the keys are up, fire the up edge to unwedge it.
        Returns True if it healed. Runs on the watchdog thread.
        """
        with self._lock:
            if not self._active:
                return False
            if self.all_required_down(key_state):
                return False          # genuinely still held
            self._pressed.clear()
            self._active = False
        log.warning("hotkey: healing a stuck combo (a key-up was lost)")
        self._on_up(None)
        return True


class _RealScheduler:
    """Fires ``fn`` after ``delay`` seconds on a daemon timer thread."""

    def after(self, delay, fn):
        t = threading.Timer(delay, fn)
        t.daemon = True
        t.start()
        return t  # threading.Timer has .cancel()


class TapHoldGesture:
    """Classifies combo down/up edges into start/stop/hint dictation actions.

    States:
      IDLE          not recording, key up
      HOLD_PENDING  recording, key down, tap-vs-hold not yet decided
      TAP_WAIT      recording, key up, awaiting a possible second tap
      HF_ARMING     recording (hands-free just confirmed), key still down
      HANDS_FREE    recording (hands-free latched), key up, armed to stop
      STOP_WAIT     not recording, key down, waiting for release to reset

    ``on_start`` / ``on_stop`` are the same callbacks the controller uses for
    every recording. ``on_hint`` fires on a lone idle tap (nothing dictated).

    ``on_start`` may return ``False`` to REFUSE the start — the controller does
    this when it is still PROCESSING the previous clip, since its state machine
    only allows IDLE -> RECORDING. A refused start must not leave a gesture
    latched around a recording that does not exist (a double-tap would reach
    HANDS_FREE with the mic closed, and the next tap would be swallowed
    "stopping" it), so the machine drops straight to STOP_WAIT and is back at
    IDLE the moment the key comes up. Any other return value — including the
    ``None`` of the older callback shape — counts as a successful start.

    ``on_cancel`` ends a recording by DISCARDING it (controller.cancel_recording:
    stop the mic, throw the audio away, never transcribe). It is fired instead of
    ``on_stop`` for a lone idle tap: that clip runs tap-duration + the double-tap
    window (~0.4-0.65s), which clears the controller's 0.3s min-duration guard, so
    stopping it normally would transcribe and paste ambient audio. Falls back to
    ``on_stop`` only if no cancel callback was supplied.
    """

    def __init__(self, on_start, on_stop, on_hint=None, on_cancel=None,
                 is_recording=None, tap_max=0.35, double_gap=0.30,
                 clock=None, scheduler=None):
        self._on_start = on_start
        self._on_stop = on_stop
        self._on_hint = on_hint or (lambda: None)
        self._on_cancel = on_cancel or on_stop
        # is_recording() reports whether a recording the controller owns is live.
        # It disambiguates a refused start: PROCESSING (nothing to stop) vs an
        # already-RECORDING clip this gesture never started (toggle it off).
        # Defaults to "never recording" so a gesture built without it behaves
        # exactly as before (no toggle fallback).
        self._is_recording_external = is_recording or (lambda: False)
        self.tap_max = tap_max
        self.double_gap = double_gap
        self._clock = clock or time.monotonic
        self._scheduler = scheduler or _RealScheduler()
        self._state = "IDLE"
        self._press_time = 0.0
        self._timer = None
        self._lock = threading.RLock()

    @property
    def state(self) -> str:
        return self._state

    def _goto(self, state):
        """Set the state, logging the edge at DEBUG (zero cost when off)."""
        prev = self._state
        if state != prev:
            self._state = state
            if log.isEnabledFor(logging.DEBUG):
                log.debug("gesture: %s -> %s", prev, state)

    def is_recording(self) -> bool:
        return self._state in ("HOLD_PENDING", "TAP_WAIT", "HF_ARMING", "HANDS_FREE")

    # --- edge handlers (called by _Combo) ---
    # ``now`` is the timestamp the event was OBSERVED at (captured on the hook
    # thread and threaded through the dispatcher). Using it — rather than reading
    # the clock when the worker gets around to the event — keeps tap-vs-hold
    # classification correct even when a slow on_start (mic open) delays the
    # worker between a quick tap's press and release. None -> read the clock now
    # (direct/test calls).
    def key_down(self, now=None):
        with self._lock:
            st = self._state
            if st == "IDLE":
                self._press_time = self._clock() if now is None else now
                self._goto("HOLD_PENDING")
                if self._on_start() is False:
                    # Start refused. Park in STOP_WAIT and reset on release. Two
                    # reasons the controller refuses:
                    #  * it is still PROCESSING the previous clip — nothing is
                    #    recording, so there is nothing to stop; just wait.
                    #  * it is already RECORDING a clip this gesture never
                    #    started (the gesture was rebuilt or otherwise desynced
                    #    mid-recording). Swallowing the press would strand that
                    #    recording, so TOGGLE it off instead.
                    self._goto("STOP_WAIT")
                    if self._is_recording_external():
                        self._on_stop()
            elif st == "TAP_WAIT":
                # Second press inside the double-tap window -> latch hands-free.
                self._cancel_timer()
                self._goto("HF_ARMING")
            elif st == "HANDS_FREE":
                # A tap while hands-free stops recording.
                self._goto("STOP_WAIT")
                self._on_stop()
            # HOLD_PENDING / HF_ARMING / STOP_WAIT: key already down
            # (OS key-repeat or spurious) -> ignore.

    def key_up(self, now=None):
        with self._lock:
            st = self._state
            if st == "HOLD_PENDING":
                t = self._clock() if now is None else now
                held = t - self._press_time
                if held >= self.tap_max:
                    # A hold -> release ends push-to-talk.
                    self._goto("IDLE")
                    self._on_stop()
                else:
                    # A tap -> keep recording briefly to see if a second tap
                    # turns it into a hands-free double-tap.
                    self._goto("TAP_WAIT")
                    self._arm_timer(self.double_gap, self._tap_wait_expired)
            elif st == "HF_ARMING":
                # Release of the confirming second tap -> now armed to stop.
                self._goto("HANDS_FREE")
            elif st == "STOP_WAIT":
                self._goto("IDLE")
            # IDLE / TAP_WAIT / HANDS_FREE: no tracked key was down -> ignore.

    def external_stop(self):
        """Recording ended by something other than this gesture — the overlay
        ✓/✕ buttons, the auto-stop timer, or a listener rebuild.

        Drop any latch so the NEXT hotkey press starts a fresh recording instead
        of being swallowed "stopping" a recording that is already gone (the
        reported bug after every ✓-icon stop). Idempotent and safe from any
        thread: when this gesture stopped the recording itself it is already in
        STOP_WAIT/IDLE, so this is a no-op.
        """
        with self._lock:
            st = self._state
            if st in ("HOLD_PENDING", "HF_ARMING"):
                # A combo key is still physically down; wait for its release so
                # that release is not read as a fresh gesture edge.
                self._cancel_timer()
                self._goto("STOP_WAIT")
            elif st in ("TAP_WAIT", "HANDS_FREE"):
                self._cancel_timer()
                self._goto("IDLE")
            # IDLE / STOP_WAIT: not latched -> nothing to do.

    def _tap_wait_expired(self):
        with self._lock:
            if self._state != "TAP_WAIT":
                return  # a second tap (or reset) already handled it
            # Lone idle tap: nothing meant to be dictated. CANCEL (discard the
            # audio) rather than stop — by now the eager recording is long enough
            # to clear the min-duration guard, so stopping it would transcribe
            # and paste whatever ambient sound was captured.
            self._goto("IDLE")
            self._on_cancel()
        # Hint outside the lock so a slow callback can't wedge the machine.
        self._on_hint()

    # --- timer helpers ---
    def _arm_timer(self, delay, fn):
        self._cancel_timer()
        self._timer = self._scheduler.after(delay, fn)

    def _cancel_timer(self):
        if self._timer is not None:
            try:
                self._timer.cancel()
            except Exception:
                pass
            self._timer = None


class HotkeyManager:
    """Listens for the configured hotkey and drives dictation gestures.

    Public callbacks (all optional except start/stop):
        on_start  — begin a recording (controller.start_recording)
        on_stop   — end a recording   (controller.stop_recording)
        on_cancel — discard a recording without transcribing
                    (controller.cancel_recording); used for a lone idle tap
        on_hint   — user tapped once while idle (nothing dictated)
        is_recording — () -> bool; whether the controller currently owns a live
                    recording. Enables the toggle fallback (see TapHoldGesture).

    The hook callbacks only canonicalize + enqueue; a :class:`_ThreadedDispatcher`
    runs the combo/gesture/controller work off the hook thread so slow work
    (the mic open) can never get the low-level hook removed by Windows. A
    :class:`HotkeyWatchdog` rebuilds the listener if the hook dies anyway.

    Never raises on a bad configured hotkey: a hand-edited / invalid value
    falls back to :data:`DEFAULT_HOTKEY` and reports via ``on_config_error``
    instead of crashing startup.
    """

    def __init__(self, hotkey, on_start, on_stop, on_hint=None, on_cancel=None,
                 on_config_error=None, is_recording=None, tap_max=0.35,
                 double_gap=0.30, clock=None, scheduler=None, dispatcher=None,
                 watchdog=True, key_state=None):
        self.hotkey = hotkey or DEFAULT_HOTKEY
        try:
            keys = parse_hotkey(self.hotkey)
        except Exception as e:
            msg = f"Invalid hotkey {hotkey!r} ({e}); using default {DEFAULT_HOTKEY}."
            log.error(msg)
            if on_config_error:
                on_config_error(msg)
            self.hotkey = DEFAULT_HOTKEY
            keys = parse_hotkey(DEFAULT_HOTKEY)

        self.gesture = TapHoldGesture(
            on_start, on_stop, on_hint, on_cancel, is_recording=is_recording,
            tap_max=tap_max, double_gap=double_gap,
            clock=clock, scheduler=scheduler)
        self._combo = _Combo(keys, self.gesture.key_down, self.gesture.key_up)
        self._listener = None
        self._stopped = False
        # A single mutex serializes the two places that swap self._listener
        # (stop() and restart_listener()); readers just take an atomic snapshot.
        self._listener_lock = threading.Lock()
        self._dispatcher = dispatcher if dispatcher is not None else _ThreadedDispatcher()
        self._clock = clock or time.monotonic
        self._key_state = key_state or _win_key_down
        self._want_watchdog = watchdog
        self._watchdog = None

    def _on_press(self, key):
        # Do the ABSOLUTE minimum on the hook thread: snapshot the listener,
        # canonicalize, stamp the event time, hand off. Everything else runs on
        # the dispatch worker. Wrapped so a raising callback can never make
        # pynput tear the listener down invisibly (it does that on any unhandled
        # callback exception, and our stop() never join()s to surface it).
        try:
            listener = self._listener        # atomic snapshot; stop() nulls it
            if listener is None:
                return
            ck = listener.canonical(key)
            now = self._clock()
            self._dispatcher.submit(lambda: self._combo.press(ck, key, now))
        except Exception:
            log.exception("hotkey on_press failed")

    def _on_release(self, key):
        try:
            listener = self._listener
            if listener is None:
                return
            ck = listener.canonical(key)
            now = self._clock()
            self._dispatcher.submit(lambda: self._combo.release(ck, key, now))
        except Exception:
            log.exception("hotkey on_release failed")

    def _new_listener(self):
        return keyboard.Listener(
            on_press=self._on_press, on_release=self._on_release)

    def start(self):
        self._stopped = False
        self._dispatcher.start()
        listener = self._new_listener()
        with self._listener_lock:
            self._listener = listener
        listener.start()
        if self._want_watchdog:
            self._watchdog = HotkeyWatchdog(
                is_alive=self.listener_alive,
                combo_down=lambda: self._combo.all_required_down(self._key_state),
                combo_active=lambda: self._combo.active,
                rebuild=self.restart_listener,
                reconcile=lambda: self._combo.reconcile(self._key_state),
                clock=self._clock)
            self._watchdog.start()

    def listener_alive(self) -> bool:
        """Whether the pynput listener thread is still running. A callback that
        raised makes pynput stop the thread; the watchdog rebuilds on that."""
        listener = self._listener
        if listener is None:
            return True   # stopped/not started — nothing to repair
        try:
            return bool(listener.is_alive()) and getattr(listener, "running", True)
        except Exception:
            return True

    def restart_listener(self):
        """Swap ONLY the pynput listener, keeping the combo/gesture/dispatcher.

        The watchdog calls this to recover a silently-removed hook without
        disturbing an in-progress gesture: because the combo/gesture state is
        preserved, a latched hands-free recording stays stoppable across the
        rebuild. The new listener is started BEFORE the old one is stopped, so
        there is never a gap with no hook — at worst an event is delivered to
        both, which the combo handles idempotently.
        """
        if self._stopped:
            return   # a late watchdog tick after stop(): don't build a hook
        new = self._new_listener()
        new.start()
        with self._listener_lock:
            if self._stopped:
                old = None
            else:
                old, self._listener = self._listener, new
        if self._stopped:
            try:
                new.stop()          # torn down while we were building; don't resurrect
            except Exception:
                pass
            return
        if old is not None:
            try:
                old.stop()
            except Exception:
                log.exception("stopping the old hotkey listener during rebuild failed")

    def stop(self):
        # Order matters: stop the watchdog first (so it can't rebuild while we
        # tear down), then detach+stop the listener, then drain the dispatcher.
        # Detaching first means any callback that slips through sees None.
        self._stopped = True
        watchdog, self._watchdog = self._watchdog, None
        if watchdog is not None:
            try:
                watchdog.stop()
            except Exception:
                log.exception("stopping the hotkey watchdog failed")
        with self._listener_lock:
            listener, self._listener = self._listener, None
        if listener is not None:
            try:
                listener.stop()
            except Exception:
                log.exception("stopping the hotkey listener failed")
        try:
            self._dispatcher.stop()
        except Exception:
            log.exception("stopping the hotkey dispatcher failed")


class HotkeyWatchdog:
    """Repairs a silently-dead keyboard hook and a stuck combo, on a timer.

    Windows removes a low-level keyboard hook whose callback is chronically slow
    (``LowLevelHooksTimeout``), and pynput stops the listener thread on any
    unhandled callback exception — both leave the hotkey dead for the whole
    session with no signal and, until now, no recovery. The dispatcher offload
    makes the slow-callback case very unlikely; this is the belt-and-braces net.

    Each tick, using OS ground truth (``GetAsyncKeyState`` reads input BELOW our
    hook, so it still works once the hook is gone):

      * combo tracker ``active`` but the keys are physically UP for ``heal_ticks``
        consecutive polls -> a key-up was lost -> heal the tracker (``reconcile``)
        so a wedged recording can end. The sustain distinguishes a lost key-up
        from a release merely QUEUED behind a slow handler (which the worker
        clears within a tick), so the heal never steals a real release.
      * listener thread no longer alive                          -> a callback
        raised -> rebuild.
      * combo keys physically DOWN but the tracker never went active, for
        ``miss_ticks`` consecutive polls                         -> the hook
        delivered nothing for a real press -> presume it dead -> rebuild.

    Polling the combo's OWN keys (not ``GetLastInputInfo``) makes detection
    specific to the hotkey, so ordinary mouse-only activity never triggers a
    rebuild, and the combo goes ``active`` the instant a press is seen (before
    the slow mic open), so a live-but-busy hook is never mistaken for a dead one.
    Rebuilds are rate-limited and fire at most once per key-down episode.

    Everything is injected (``clock``/``combo_down``/``combo_active``/``is_alive``
    /``rebuild``/``reconcile``), and ``tick()`` is a pure step the daemon loop
    just calls on ``interval``, so the logic is unit-tested with no real hook,
    no OS calls and no timing.
    """

    def __init__(self, *, is_alive, combo_down, combo_active, rebuild, reconcile,
                 clock=None, interval=0.15, miss_ticks=2, heal_ticks=2,
                 rebuild_cooldown=2.0):
        self._is_alive = is_alive
        self._combo_down = combo_down        # () -> bool  (OS: all combo keys down)
        self._combo_active = combo_active    # () -> bool  (our tracker active)
        self._rebuild = rebuild              # () -> None
        self._reconcile = reconcile          # () -> bool  (heal stuck-active)
        self._clock = clock or time.monotonic
        self._interval = interval
        self._miss_ticks = miss_ticks
        self._heal_ticks = heal_ticks
        self._rebuild_cooldown = rebuild_cooldown
        self._miss_run = 0
        self._up_run = 0
        self._rebuilt_this_press = False
        self._last_rebuild = None
        self._stop = threading.Event()
        self._thread = None

    def start(self):
        self._thread = threading.Thread(
            target=self._loop, name="rekounts-hotkey-watchdog", daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()

    def _loop(self):
        while not self._stop.wait(self._interval):
            try:
                self.tick()
            except Exception:
                log.exception("hotkey watchdog tick failed")

    def _safe(self, fn, what, default=None):
        try:
            return fn()
        except Exception:
            log.exception("hotkey watchdog: %s failed", what)
            return default

    def tick(self):
        # One OS poll per tick, shared by the heal and rebuild checks. These
        # internal reads don't raise; the defaults are pure belt-and-braces.
        alive = self._safe(self._is_alive, "listener liveness", default=True)
        down = self._safe(self._combo_down, "combo-down poll", default=False)
        active = self._safe(self._combo_active, "combo-active read", default=False)

        # (a) Self-heal a stuck-active combo (a lost key-up), but only once the
        # keys have read UP for a sustained run. reconcile() re-checks under the
        # combo lock, so a release that lands in between is never double-fired.
        if active and not down:
            self._up_run += 1
            if self._up_run >= self._heal_ticks:
                self._up_run = 0
                self._safe(self._reconcile, "combo reconcile")
        else:
            self._up_run = 0

        if not down:
            # Keys are up: a fresh down starts a new detection episode.
            self._miss_run = 0
            self._rebuilt_this_press = False
            if not alive:
                self._do_rebuild("listener thread not alive")
            return

        # Keys are physically down.
        if not alive:
            self._do_rebuild("listener thread not alive")
            return
        if active:
            self._miss_run = 0   # the hook saw the press — all healthy
            return
        # Down, thread alive, but our tracker never went active: the hook
        # delivered nothing for a real press -> Windows silently removed it.
        self._miss_run += 1
        if self._miss_run >= self._miss_ticks and not self._rebuilt_this_press:
            self._do_rebuild("combo keys held but no key event seen — hook presumed dead")

    def _do_rebuild(self, reason):
        now = self._clock()
        if (self._last_rebuild is not None
                and (now - self._last_rebuild) < self._rebuild_cooldown):
            return
        log.warning("hotkey watchdog: rebuilding the listener (%s)", reason)
        self._last_rebuild = now
        self._rebuilt_this_press = True   # once per key-down episode
        self._miss_run = 0
        self._safe(self._rebuild, "listener rebuild")
