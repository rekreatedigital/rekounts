"""HotkeyManager wiring: bad-config resilience and combo -> gesture flow.

These exercise the manager without starting a real OS listener (no .start()).
"""
from pynput import keyboard

from rekounts.hotkey_manager import (DEFAULT_HOTKEY, HotkeyManager,
                                        _InlineDispatcher, hotkey_warning)


class FakeJob:
    def __init__(self, fn):
        self.fn = fn
        self.cancelled = False

    def cancel(self):
        self.cancelled = True


class FakeScheduler:
    def __init__(self):
        self.job = None

    def after(self, delay, fn):
        self.job = FakeJob(fn)
        return self.job

    def fire(self):
        if self.job and not self.job.cancelled:
            self.job.fn()


class FakeClock:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t

    def advance(self, dt):
        self.t += dt


def test_invalid_hotkey_falls_back_to_default_without_raising():
    errors = []
    m = HotkeyManager("f88", on_start=lambda: None, on_stop=lambda: None,
                      on_config_error=lambda msg: errors.append(msg))
    assert m.hotkey == DEFAULT_HOTKEY
    assert errors and "f88" in errors[0]


def test_empty_hotkey_falls_back():
    m = HotkeyManager("", on_start=lambda: None, on_stop=lambda: None)
    assert m.hotkey == DEFAULT_HOTKEY


def test_valid_hotkey_kept():
    m = HotkeyManager("f8", on_start=lambda: None, on_stop=lambda: None)
    assert m.hotkey == "f8"


def test_combo_drives_gesture_hold():
    clock, sched = FakeClock(), FakeScheduler()
    events = []
    m = HotkeyManager(
        "ctrl+win",
        on_start=lambda: events.append("start"),
        on_stop=lambda: events.append("stop"),
        clock=clock, scheduler=sched)
    # feed the combo through the manager's combo tracker (canonical keys)
    m._combo.press(keyboard.Key.ctrl)
    m._combo.press(keyboard.Key.cmd)
    assert events == ["start"]
    clock.advance(1.0)
    m._combo.release(keyboard.Key.ctrl)   # releasing one combo key ends the hold
    assert events == ["start", "stop"]


def test_releasing_noncombo_key_does_not_stop_hold():
    clock, sched = FakeClock(), FakeScheduler()
    events = []
    m = HotkeyManager(
        "ctrl+win",
        on_start=lambda: events.append("start"),
        on_stop=lambda: events.append("stop"),
        clock=clock, scheduler=sched)
    m._combo.press(keyboard.Key.ctrl)
    m._combo.press(keyboard.Key.cmd)
    m._combo.release(keyboard.KeyCode.from_char("x"))  # unrelated key
    assert events == ["start"]   # hold survives


# --- finding 4: listener torn down while a callback is still queued -------
class FakeListener:
    """Stands in for pynput's listener.

    canonical() returns the key unchanged, which is exactly what pynput does on
    the generic path — the path taken when an event carries no scan code.
    """

    def __init__(self):
        self.stopped = False

    def canonical(self, key):
        return key

    def stop(self):
        self.stopped = True


def make(hotkey="ctrl+win"):
    clock, sched = FakeClock(), FakeScheduler()
    events = []
    m = HotkeyManager(
        hotkey,
        on_start=lambda: events.append("start"),
        on_stop=lambda: events.append("stop"),
        clock=clock, scheduler=sched,
        # Run dispatched events inline so _on_press is synchronous and
        # deterministic here; the threaded dispatcher is exercised separately.
        dispatcher=_InlineDispatcher())
    return m, events, clock


def test_queued_callback_after_stop_is_ignored_not_an_error():
    # apply_settings swaps the listener on every Save. stop() nulls
    # self._listener while pynput can still deliver already-queued callbacks on
    # the dying hook thread — which used to raise AttributeError there.
    m, events, _ = make()
    m._listener = FakeListener()
    m.stop()
    m._on_press(keyboard.Key.ctrl)      # queued callback arrives late
    m._on_release(keyboard.Key.ctrl)
    assert events == []                 # and drives nothing


def test_stop_is_idempotent_and_stops_the_real_listener():
    m, _, _ = make()
    listener = FakeListener()
    m._listener = listener
    m.stop()
    assert listener.stopped is True
    m.stop()                            # second Save in a row must be harmless


def test_stop_survives_a_listener_that_raises():
    class AngryListener(FakeListener):
        def stop(self):
            raise RuntimeError("hook already gone")

    m, _, _ = make()
    m._listener = AngryListener()
    m.stop()                            # must not propagate into apply_settings
    assert m._listener is None


# --- finding 7: ctrl+<letter> reliability ---------------------------------
# Windows reports ctrl+a as the C0 control character '\x01'. pynput's win32
# canonical() normally maps it back to 'a' using the event's scan code, but
# events with no scan code (VK_PACKET: remote desktop, on-screen keyboards,
# macro tools) fall through to the generic path and stay '\x01'. Matching on
# the character alone therefore silently never fires.
def test_ctrl_letter_matches_a_control_character():
    m, events, clock = make("ctrl+a")
    m._combo.press(keyboard.Key.ctrl)
    m._combo.press(keyboard.KeyCode.from_char("\x01"))   # ctrl+a as delivered
    assert events == ["start"]
    clock.advance(1.0)
    m._combo.release(keyboard.KeyCode.from_char("\x01"))
    assert events == ["start", "stop"]


def test_ctrl_letter_matches_through_the_scan_less_listener_path():
    # End to end through _on_press, with a listener whose canonical() cannot
    # improve on the raw event — the real VK_PACKET case.
    m, events, _ = make("ctrl+a")
    m._listener = FakeListener()
    m._on_press(keyboard.Key.ctrl)
    m._on_press(keyboard.KeyCode.from_char("\x01"))
    assert events == ["start"]


def test_ctrl_letter_matches_on_virtual_key_code_alone():
    # Some events arrive with no usable character at all; the vk still says
    # which physical key it was (VK_A == ord('A')).
    m, events, _ = make("ctrl+a")
    m._combo.press(keyboard.Key.ctrl)
    m._combo.press(keyboard.KeyCode(char=None, vk=0x41))
    assert events == ["start"]


def test_digit_hotkey_matches_on_virtual_key_code():
    m, events, _ = make("alt+1")
    m._combo.press(keyboard.Key.alt)
    m._combo.press(keyboard.KeyCode(char=None, vk=0x31))   # VK_1
    assert events == ["start"]


def test_plain_letter_still_matches_normally():
    m, events, _ = make("ctrl+a")
    m._combo.press(keyboard.Key.ctrl)
    m._combo.press(keyboard.KeyCode.from_char("a"))
    assert events == ["start"]


def test_a_different_letter_does_not_complete_the_combo():
    # The looser matching must not make unrelated keys trigger dictation.
    m, events, _ = make("ctrl+a")
    m._combo.press(keyboard.Key.ctrl)
    m._combo.press(keyboard.KeyCode.from_char("b"))
    m._combo.press(keyboard.KeyCode.from_char("\x02"))     # ctrl+b
    assert events == []


def test_a_different_modifier_does_not_complete_the_combo():
    m, events, _ = make("ctrl+a")
    m._combo.press(keyboard.Key.shift)
    m._combo.press(keyboard.KeyCode.from_char("a"))
    assert events == []


def test_named_key_hotkeys_are_unaffected():
    # f8 parses to a vk-only KeyCode; it must still match what canonical()
    # produces (regression guard for the token rewrite).
    m, events, clock = make("f8")
    m._combo.press(keyboard.KeyCode.from_vk(keyboard.Key.f8.value.vk))
    assert events == ["start"]
    clock.advance(1.0)
    m._combo.release(keyboard.KeyCode.from_vk(keyboard.Key.f8.value.vk))
    assert events == ["start", "stop"]


def test_named_key_matches_the_raw_key_object_too():
    # ...and also matches the un-canonicalised Key the hook reports, so the
    # combo does not depend on canonical() converting Key.f8 to a vk KeyCode.
    m, events, _ = make("f8")
    m._combo.press(keyboard.Key.f8)
    assert events == ["start"]


# --- finding 7 (second half): warn about shortcut-colliding combos --------
def test_single_modifier_plus_letter_is_flagged():
    warning = hotkey_warning("ctrl+a")
    assert warning and "Ctrl+A" in warning


def test_single_modifier_plus_digit_is_flagged():
    assert hotkey_warning("alt+1") is not None


def test_safe_hotkeys_are_not_flagged():
    # The default, F-keys and two-modifier combos collide with essentially
    # nothing, so they must stay silent.
    assert hotkey_warning("ctrl+win") is None
    assert hotkey_warning("f8") is None
    assert hotkey_warning("ctrl+shift+a") is None
    assert hotkey_warning("ctrl+alt+space") is None
    assert hotkey_warning("") is None
    assert hotkey_warning(None) is None


# --- listener lifecycle: rebuild preserves state; stop tears it all down ----
class SpyListener:
    """A stand-in for pynput's listener that never touches the OS. start/stop
    just flip flags and is_alive()/running mirror them."""

    def __init__(self, on_press=None, on_release=None):
        self.on_press, self.on_release = on_press, on_release
        self.started = self.stopped = False
        self._alive = False

    def start(self):
        self.started = True
        self._alive = True

    def stop(self):
        self.stopped = True
        self._alive = False

    def is_alive(self):
        return self._alive

    @property
    def running(self):
        return self._alive

    def canonical(self, key):
        return key


def _make_started(monkeypatch, hotkey="ctrl+win"):
    monkeypatch.setattr("rekounts.hotkey_manager.keyboard.Listener", SpyListener)
    m = HotkeyManager(hotkey, on_start=lambda: None, on_stop=lambda: None,
                      dispatcher=_InlineDispatcher(), watchdog=False)
    m.start()   # SpyListener, inline dispatcher, no watchdog -> zero real threads
    return m


def test_restart_listener_swaps_in_a_fresh_started_listener(monkeypatch):
    m = _make_started(monkeypatch)
    first = m._listener
    assert isinstance(first, SpyListener) and first.started
    m.restart_listener()
    second = m._listener
    assert second is not first
    assert second.started               # new one is live
    assert first.stopped                # old one torn down
    m.stop()


def test_restart_listener_preserves_the_gesture_state(monkeypatch):
    # The whole point of rebuilding only the listener: a latched hands-free
    # recording must survive the swap so it stays stoppable.
    m = _make_started(monkeypatch)
    m.gesture.key_down(); m.gesture.key_up()          # -> TAP_WAIT
    m.gesture.key_down(); m.gesture.key_up()          # -> HANDS_FREE
    assert m.gesture.state == "HANDS_FREE"
    m.restart_listener()
    assert m.gesture.state == "HANDS_FREE"            # untouched
    m.stop()


def test_restart_listener_does_not_resurrect_a_stopped_manager(monkeypatch):
    m = _make_started(monkeypatch)
    m.stop()
    m.restart_listener()                # a watchdog tick that just lost the race
    assert m._listener is None          # stayed stopped


def test_listener_alive_reflects_thread_liveness(monkeypatch):
    m = _make_started(monkeypatch)
    assert m.listener_alive() is True
    m._listener._alive = False          # pynput stopped it on a raising callback
    assert m.listener_alive() is False
    m.stop()


def test_listener_alive_is_true_before_start_and_after_stop(monkeypatch):
    monkeypatch.setattr("rekounts.hotkey_manager.keyboard.Listener", SpyListener)
    m = HotkeyManager("ctrl+win", on_start=lambda: None, on_stop=lambda: None,
                      dispatcher=_InlineDispatcher(), watchdog=False)
    assert m.listener_alive() is True   # nothing to repair yet
    m.start()
    m.stop()
    assert m.listener_alive() is True   # intentionally stopped -> not "dead"


def test_start_wires_a_watchdog_only_when_asked(monkeypatch):
    monkeypatch.setattr("rekounts.hotkey_manager.keyboard.Listener", SpyListener)
    m = HotkeyManager("ctrl+win", on_start=lambda: None, on_stop=lambda: None,
                      dispatcher=_InlineDispatcher(), watchdog=False)
    m.start()
    assert m._watchdog is None
    m.stop()
