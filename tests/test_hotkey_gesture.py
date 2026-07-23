"""Tap / hold / double-tap classification — the heart of the app's feel.

Driven by a fake clock + fake scheduler so timing is deterministic. The gesture
machine sees only abstract combo edges (key_down / key_up); combo detection is
tested separately.
"""
from rekounts.hotkey_manager import TapHoldGesture

TAP_MAX = 0.35
DOUBLE_GAP = 0.30


class FakeClock:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t

    def advance(self, dt):
        self.t += dt


class FakeJob:
    def __init__(self, fn):
        self.fn = fn
        self.cancelled = False

    def cancel(self):
        self.cancelled = True


class FakeScheduler:
    """Records the single armed timeout; the test fires it explicitly."""

    def __init__(self):
        self.job = None
        self.last_delay = None

    def after(self, delay, fn):
        self.job = FakeJob(fn)
        self.last_delay = delay
        return self.job

    def fire(self):
        assert self.job is not None, "no timeout was armed"
        if not self.job.cancelled:
            self.job.fn()


def make():
    clock = FakeClock()
    sched = FakeScheduler()
    events = []
    g = TapHoldGesture(
        on_start=lambda: events.append("start"),
        on_stop=lambda: events.append("stop"),
        on_hint=lambda: events.append("hint"),
        on_cancel=lambda: events.append("cancel"),
        tap_max=TAP_MAX, double_gap=DOUBLE_GAP,
        clock=clock, scheduler=sched,
    )
    return g, clock, sched, events


# --- HOLD (push-to-talk) ---
def test_hold_starts_on_press_and_stops_on_release():
    g, clock, sched, events = make()
    g.key_down()
    assert events == ["start"]        # eager start on key-down
    assert g.is_recording()
    clock.advance(1.0)                # held well past tap threshold
    g.key_up()
    assert events == ["start", "stop"]
    assert g.state == "IDLE"


def test_hold_exactly_at_threshold_is_a_hold():
    g, clock, sched, events = make()
    g.key_down()
    clock.advance(TAP_MAX)            # >= threshold counts as hold
    g.key_up()
    assert events == ["start", "stop"]
    assert g.state == "IDLE"


# --- lone single tap while idle ---
def test_lone_tap_cancels_rather_than_stops():
    # Must CANCEL (discard audio), not stop: by expiry the clip is
    # tap-duration + double_gap, which clears the controller's 0.3s
    # min-duration guard, so a stop would transcribe ambient audio.
    g, clock, sched, events = make()
    g.key_down()
    clock.advance(0.1)               # quick tap (< threshold)
    g.key_up()
    assert events == ["start"]       # still recording, awaiting a second tap
    assert g.state == "TAP_WAIT"
    assert sched.last_delay == DOUBLE_GAP
    clock.advance(DOUBLE_GAP + 0.01)
    sched.fire()                     # double-tap window elapsed, no second tap
    assert events == ["start", "cancel", "hint"]
    assert "stop" not in events
    assert g.state == "IDLE"


def test_cancel_falls_back_to_stop_when_not_supplied():
    # Back-compat: without an on_cancel the machine still ends the recording.
    clock, sched = FakeClock(), FakeScheduler()
    events = []
    g = TapHoldGesture(
        on_start=lambda: events.append("start"),
        on_stop=lambda: events.append("stop"),
        tap_max=TAP_MAX, double_gap=DOUBLE_GAP, clock=clock, scheduler=sched)
    g.key_down()
    clock.advance(0.1)
    g.key_up()
    sched.fire()
    assert events == ["start", "stop"]


# --- DOUBLE-TAP (hands-free) ---
def test_double_tap_latches_hands_free():
    g, clock, sched, events = make()
    # first tap
    g.key_down()
    clock.advance(0.1)
    g.key_up()
    assert g.state == "TAP_WAIT"
    # second tap within the window
    clock.advance(0.1)
    g.key_down()
    assert g.state == "HF_ARMING"
    assert sched.job.cancelled       # pending discard timeout was cancelled
    clock.advance(0.1)
    g.key_up()
    assert g.state == "HANDS_FREE"
    # never stopped: exactly one start, still recording
    assert events == ["start"]
    assert g.is_recording()


def test_single_tap_stops_hands_free():
    g, clock, sched, events = make()
    # enter hands-free via double-tap
    g.key_down(); clock.advance(0.1); g.key_up()
    clock.advance(0.1); g.key_down(); clock.advance(0.1); g.key_up()
    assert g.state == "HANDS_FREE"
    events.clear()
    # a single tap now stops it
    g.key_down()
    assert events == ["stop"]        # stops immediately on the tap's press
    assert g.state == "STOP_WAIT"
    g.key_up()
    assert g.state == "IDLE"
    assert not g.is_recording()


def test_hands_free_survives_second_key_release():
    # The release of the confirming second tap must NOT be read as a stop.
    g, clock, sched, events = make()
    g.key_down(); clock.advance(0.1); g.key_up()        # tap 1
    clock.advance(0.1); g.key_down()                    # tap 2 press
    g.key_up()                                          # tap 2 release
    assert events == ["start"]                          # no stop
    assert g.state == "HANDS_FREE"


def test_second_tap_after_window_is_a_fresh_recording():
    # If the timeout already fired, a later press starts over rather than
    # latching hands-free.
    g, clock, sched, events = make()
    g.key_down(); clock.advance(0.1); g.key_up()
    sched.fire()                                        # window elapsed
    assert g.state == "IDLE"
    assert events == ["start", "cancel", "hint"]
    g.key_down()                                        # brand new press
    assert g.state == "HOLD_PENDING"
    assert events == ["start", "cancel", "hint", "start"]


# --- refused starts (controller busy PROCESSING) ---
def make_refusing():
    """on_start returns False, the way AppController does when it is still
    PROCESSING the previous clip and its state machine refuses the transition."""
    clock, sched = FakeClock(), FakeScheduler()
    events = []

    def refuse():
        events.append("start-refused")
        return False

    g = TapHoldGesture(
        on_start=refuse,
        on_stop=lambda: events.append("stop"),
        on_hint=lambda: events.append("hint"),
        on_cancel=lambda: events.append("cancel"),
        tap_max=TAP_MAX, double_gap=DOUBLE_GAP, clock=clock, scheduler=sched)
    return g, clock, sched, events


def test_refused_start_does_not_latch_the_gesture():
    g, clock, sched, events = make_refusing()
    g.key_down()
    assert not g.is_recording(), "nothing is recording, so the gesture must agree"
    assert g.state == "STOP_WAIT"      # parked, waiting only for the release
    g.key_up()
    assert g.state == "IDLE"           # back immediately, no timer, no gesture burnt
    assert events == ["start-refused"]


def test_refused_start_cannot_reach_hands_free():
    # The reported symptom: tapping while PROCESSING latched HANDS_FREE with no
    # recording behind it, so the NEXT tap was swallowed "stopping" it.
    g, clock, sched, events = make_refusing()
    g.key_down(); clock.advance(0.1); g.key_up()          # tap 1
    clock.advance(0.1)
    g.key_down(); clock.advance(0.1); g.key_up()          # tap 2
    assert g.state == "IDLE"
    assert not g.is_recording()
    assert "stop" not in events


def test_refused_start_arms_no_discard_timer():
    g, clock, sched, events = make_refusing()
    g.key_down()
    clock.advance(0.1)
    g.key_up()
    assert sched.job is None, "no recording was started, so nothing to discard"


def test_gesture_recovers_once_the_controller_frees_up():
    clock, sched = FakeClock(), FakeScheduler()
    events = []
    busy = [True]

    def maybe_start():
        events.append("start")
        return not busy[0]

    g = TapHoldGesture(
        on_start=maybe_start, on_stop=lambda: events.append("stop"),
        tap_max=TAP_MAX, double_gap=DOUBLE_GAP, clock=clock, scheduler=sched)

    g.key_down(); g.key_up()          # refused while busy
    assert g.state == "IDLE"
    busy[0] = False                   # processing finished
    g.key_down()
    assert g.state == "HOLD_PENDING"  # the very next press works normally
    clock.advance(1.0)
    g.key_up()
    assert events == ["start", "start", "stop"]


def test_start_returning_none_still_counts_as_started():
    # Back-compat: the older callback shape returns None and must be treated as
    # a successful start, not a refusal.
    clock, sched = FakeClock(), FakeScheduler()
    g = TapHoldGesture(on_start=lambda: None, on_stop=lambda: None,
                       tap_max=TAP_MAX, double_gap=DOUBLE_GAP,
                       clock=clock, scheduler=sched)
    g.key_down()
    assert g.state == "HOLD_PENDING"
    assert g.is_recording()


def test_expired_timer_after_double_tap_is_noop():
    # A late/duplicate timer firing after hands-free latched must do nothing.
    g, clock, sched, events = make()
    g.key_down(); clock.advance(0.1); g.key_up()
    clock.advance(0.1); g.key_down()                    # latches -> cancels job
    sched.fire()                                        # cancelled -> no-op
    assert g.state == "HF_ARMING"
    assert events == ["start"]


# --- event-timestamp classification (the worker may lag behind the hook) ----
# Events carry the timestamp they were OBSERVED at (captured on the hook thread,
# threaded through the dispatcher). tap-vs-hold uses THAT, not whenever the
# worker got round to the event — so a slow on_start (mic open) delaying the
# worker between a quick tap's press and release can't turn the tap into a hold.
def test_key_up_uses_the_event_timestamp_not_the_processing_clock():
    g, clock, sched, events = make()
    g.key_down(now=0.0)
    clock.advance(0.5)                 # worker was busy 0.5s opening the mic
    g.key_up(now=0.12)                 # but the release was observed at 0.12s
    assert g.state == "TAP_WAIT"       # a tap, not a hold
    assert events == ["start"]


def test_key_down_uses_the_event_timestamp_for_press_time():
    g, clock, sched, events = make()
    g.key_down(now=1.0)
    g.key_up(now=1.5)                  # held 0.5s by observed time -> a hold
    assert events == ["start", "stop"]
    assert g.state == "IDLE"


def test_omitting_the_timestamp_falls_back_to_the_clock():
    # Direct/test callers pass no timestamp -> the injected clock is used, so all
    # the existing gesture tests keep working unchanged.
    g, clock, sched, events = make()
    g.key_down()
    clock.advance(1.0)
    g.key_up()
    assert events == ["start", "stop"]


# --- external stop: a latch left by the overlay ✓/✕ or auto-stop -----------
# Reported bug: stopping via the overlay ✓ left the gesture latched in
# HANDS_FREE, so the next hotkey press was swallowed "stopping" a recording that
# was already gone — the user had to press twice to start again.
def test_external_stop_clears_the_hands_free_latch():
    g, clock, sched, events = make()
    g.key_down(); clock.advance(0.1); g.key_up()
    clock.advance(0.1); g.key_down(); clock.advance(0.1); g.key_up()
    assert g.state == "HANDS_FREE"
    events.clear()
    g.external_stop()                  # overlay ✓ / auto-stop ended it
    assert g.state == "IDLE"
    g.key_down()                       # the NEXT press starts fresh
    assert g.state == "HOLD_PENDING"
    assert events == ["start"]


def test_external_stop_during_a_hold_waits_for_release():
    g, clock, sched, events = make()
    g.key_down()                       # holding push-to-talk
    assert g.state == "HOLD_PENDING"
    g.external_stop()                  # ✓ pressed while the key is still down
    assert g.state == "STOP_WAIT"      # don't reset until it comes up...
    g.key_up()
    assert g.state == "IDLE"           # ...then it does
    assert events == ["start"]         # and that release fired no extra stop


def test_external_stop_is_a_noop_when_idle():
    g, clock, sched, events = make()
    g.external_stop()
    assert g.state == "IDLE"
    assert events == []


def test_external_stop_after_a_gesture_stop_is_harmless():
    # A gesture that stopped its own recording is already in IDLE, so the
    # on_recording_ended -> external_stop that follows must add nothing.
    g, clock, sched, events = make()
    g.key_down(); clock.advance(1.0); g.key_up()   # hold -> stop
    assert (g.state, events) == ("IDLE", ["start", "stop"])
    g.external_stop()
    assert (g.state, events) == ("IDLE", ["start", "stop"])


def test_external_stop_cancels_a_pending_tap_timer():
    g, clock, sched, events = make()
    g.key_down(); clock.advance(0.1); g.key_up()   # tap -> TAP_WAIT, timer armed
    assert g.state == "TAP_WAIT"
    g.external_stop()
    assert g.state == "IDLE"
    assert sched.job.cancelled                     # discard timer cancelled
    sched.fire()                                   # and firing it does nothing
    assert events == ["start"]


# --- toggle fallback: a refused start while RECORDING stops instead ---------
def make_recording_refuser():
    """on_start refuses AND is_recording() reports RECORDING — the state after a
    gesture is rebuilt in front of a live recording it never started (e.g. the
    hotkey was changed mid-recording)."""
    clock, sched = FakeClock(), FakeScheduler()
    events = []
    recording = [True]

    def refuse():
        events.append("start-refused")
        return False

    def stop():
        events.append("stop")
        recording[0] = False

    g = TapHoldGesture(
        on_start=refuse, on_stop=stop, is_recording=lambda: recording[0],
        tap_max=TAP_MAX, double_gap=DOUBLE_GAP, clock=clock, scheduler=sched)
    return g, clock, sched, events, recording


def test_refused_start_while_recording_toggles_a_stop():
    g, clock, sched, events, recording = make_recording_refuser()
    g.key_down()                       # a fresh gesture; the press should STOP
    assert events == ["start-refused", "stop"]     # routed to stop, not swallowed
    assert g.state == "STOP_WAIT"
    g.key_up()
    assert g.state == "IDLE"           # reusable immediately


def test_refused_start_while_processing_does_not_toggle():
    # is_recording() False (PROCESSING) -> park only, never a stop. This is the
    # long-standing behavior; the toggle must be gated on an actual recording.
    g, clock, sched, events = make_refusing()   # is_recording defaults to False
    g.key_down()
    assert events == ["start-refused"]           # no stop
    assert g.state == "STOP_WAIT"
    g.key_up()
    assert g.state == "IDLE"
