"""End-to-end gesture -> controller wiring, with a fake clock and recorder.

This is the regression guard for the reviewed blocker: a lone idle tap must
never reach the transcriber. The eager recording started on key-down runs for
tap-duration + the double-tap window (~0.4-0.65s), which CLEARS the controller's
0.3s min-duration guard — so ending it with stop_recording() would transcribe and
paste ambient audio. The gesture must cancel (discard) instead.
"""
import numpy as np

from rekounts.controller import AppController
from rekounts.hotkey_manager import TapHoldGesture
from rekounts.state_machine import DictationState
from rekounts.text_cleaner import TextCleaner

TAP_MAX = 0.35
DOUBLE_GAP = 0.30
SAMPLE_RATE = 16000


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
    def __init__(self):
        self.job = None

    def after(self, delay, fn):
        self.job = FakeJob(fn)
        return self.job

    def fire(self):
        assert self.job is not None, "no timeout was armed"
        if not self.job.cancelled:
            self.job.fn()


class FakeRecorder:
    """Returns a clip LONGER than min_seconds — the condition that made the
    lone-tap bug reachable."""

    def __init__(self, seconds=0.5):
        self._audio = np.ones(int(seconds * SAMPLE_RATE), dtype="float32")
        self.started = False
        self.stops = 0

    def start(self):
        self.started = True

    def stop(self):
        self.started = False
        self.stops += 1
        return self._audio

    def duration(self, a):
        return len(a) / SAMPLE_RATE


class FakeTranscriber:
    def __init__(self, text="ambient noise"):
        self._text = text
        self.calls = 0

    def transcribe(self, audio):
        self.calls += 1
        return self._text


def wire(clip_seconds=0.5):
    """Real TapHoldGesture -> real AppController, fake I/O and clock."""
    rec = FakeRecorder(clip_seconds)
    trans = FakeTranscriber()
    inserted = []
    ctrl = AppController(
        recorder=rec, transcriber=trans, cleaner=TextCleaner(),
        inserter=type("I", (), {"insert": lambda self, t: inserted.append(t)})(),
        min_seconds=0.3,          # production default
        run_async=None,           # process synchronously in tests
    )
    clock, sched = FakeClock(), FakeScheduler()
    gesture = TapHoldGesture(
        on_start=ctrl.start_recording,
        on_stop=ctrl.stop_recording,
        on_cancel=ctrl.cancel_recording,
        tap_max=TAP_MAX, double_gap=DOUBLE_GAP,
        clock=clock, scheduler=sched,
    )
    return gesture, ctrl, rec, trans, inserted, clock, sched


def test_lone_tap_never_reaches_the_transcriber():
    gesture, ctrl, rec, trans, inserted, clock, sched = wire(clip_seconds=0.5)

    # Precondition that makes this bug real: the clip a lone tap produces is
    # long enough to pass the min-duration guard.
    assert rec.duration(rec._audio) > ctrl.min_seconds

    gesture.key_down()                     # eager start on key-down
    assert ctrl.sm.state == DictationState.RECORDING
    clock.advance(0.12)                    # a quick tap
    gesture.key_up()
    assert ctrl.sm.state == DictationState.RECORDING   # still eager-recording
    clock.advance(DOUBLE_GAP + 0.01)
    sched.fire()                           # no second tap -> lone tap

    assert trans.calls == 0, "lone tap must never be transcribed"
    assert inserted == [], "lone tap must never insert text"
    assert rec.stops == 1, "the mic must still be released"
    assert ctrl.sm.state == DictationState.IDLE


def test_hold_still_transcribes_and_inserts():
    # The cancel path must not break normal push-to-talk.
    gesture, ctrl, rec, trans, inserted, clock, sched = wire()
    gesture.key_down()
    clock.advance(1.0)                     # a real hold
    gesture.key_up()
    assert trans.calls == 1
    assert inserted == ["Ambient noise"]   # cleaned + capitalized
    assert ctrl.sm.state == DictationState.IDLE


def wire_deferred(clip_seconds=0.5):
    """Same wiring, but transcription is queued instead of run inline — so the
    controller sits in PROCESSING exactly as it does in production while the
    model works."""
    rec = FakeRecorder(clip_seconds)
    trans = FakeTranscriber()
    inserted, pending = [], []
    ctrl = AppController(
        recorder=rec, transcriber=trans, cleaner=TextCleaner(),
        inserter=type("I", (), {"insert": lambda self, t: inserted.append(t)})(),
        min_seconds=0.3,
        run_async=pending.append,
    )
    clock, sched = FakeClock(), FakeScheduler()
    gesture = TapHoldGesture(
        on_start=ctrl.start_recording,
        on_stop=ctrl.stop_recording,
        on_cancel=ctrl.cancel_recording,
        tap_max=TAP_MAX, double_gap=DOUBLE_GAP,
        clock=clock, scheduler=sched,
    )
    return gesture, ctrl, rec, trans, inserted, pending, clock, sched


def test_tap_while_processing_does_not_latch_hands_free():
    # Reviewed desync: a tap that lands while the previous clip is still being
    # transcribed was refused by the state machine, but the gesture latched
    # anyway — a double-tap reached HANDS_FREE with the mic closed, so the next
    # tap was swallowed "stopping" a recording that never existed.
    gesture, ctrl, rec, trans, inserted, pending, clock, sched = wire_deferred()

    gesture.key_down(); clock.advance(1.0); gesture.key_up()   # a real hold
    assert ctrl.sm.state == DictationState.PROCESSING          # model is busy

    # User double-taps while it is still processing.
    gesture.key_down(); clock.advance(0.1); gesture.key_up()
    clock.advance(0.1)
    gesture.key_down(); clock.advance(0.1); gesture.key_up()

    assert gesture.state == "IDLE"
    assert not gesture.is_recording()
    assert ctrl.sm.state == DictationState.PROCESSING          # untouched

    # Once the model finishes, the very next gesture records normally.
    pending.pop(0)()
    assert ctrl.sm.state == DictationState.IDLE
    gesture.key_down()
    assert ctrl.sm.state == DictationState.RECORDING
    clock.advance(1.0)
    gesture.key_up()
    assert len(pending) == 1


def test_double_tap_hands_free_then_tap_transcribes():
    gesture, ctrl, rec, trans, inserted, clock, sched = wire()
    gesture.key_down(); clock.advance(0.1); gesture.key_up()   # tap 1
    clock.advance(0.1); gesture.key_down(); gesture.key_up()   # tap 2 -> hands-free
    assert ctrl.sm.state == DictationState.RECORDING
    assert trans.calls == 0                                    # still recording
    clock.advance(3.0)
    gesture.key_down()                                         # single tap -> stop
    assert trans.calls == 1
    assert inserted == ["Ambient noise"]
    assert ctrl.sm.state == DictationState.IDLE


def test_lone_tap_leaves_controller_reusable():
    # After a discarded tap the next real dictation must work normally.
    gesture, ctrl, rec, trans, inserted, clock, sched = wire()
    gesture.key_down(); clock.advance(0.1); gesture.key_up()
    sched.fire()                                               # discarded
    assert trans.calls == 0
    gesture.key_down(); clock.advance(1.0); gesture.key_up()   # real hold
    assert trans.calls == 1
    assert inserted == ["Ambient noise"]


# --- bug: an overlay/auto stop left the gesture latched --------------------
def test_external_stop_then_next_press_records_again():
    # __main__ wires controller.on_recording_ended -> gesture.external_stop.
    # After the overlay ✓ (a direct controller.stop_recording) the gesture must
    # NOT stay latched in hands-free swallowing the next press.
    gesture, ctrl, rec, trans, inserted, clock, sched = wire()
    ctrl.on_recording_ended = gesture.external_stop
    # go hands-free
    gesture.key_down(); clock.advance(0.1); gesture.key_up()
    clock.advance(0.1); gesture.key_down(); gesture.key_up()
    assert ctrl.sm.state == DictationState.RECORDING
    assert gesture.state == "HANDS_FREE"
    # user clicks the overlay ✓ (an external stop)
    ctrl.stop_recording()
    assert ctrl.sm.state == DictationState.IDLE
    assert gesture.state == "IDLE"                 # latch cleared
    # the very next hotkey press starts a fresh recording
    gesture.key_down()
    assert ctrl.sm.state == DictationState.RECORDING
    assert gesture.state == "HOLD_PENDING"


def test_external_stop_during_a_hold_then_release_is_clean():
    gesture, ctrl, rec, trans, inserted, clock, sched = wire()
    ctrl.on_recording_ended = gesture.external_stop
    gesture.key_down()                             # holding push-to-talk
    assert ctrl.sm.state == DictationState.RECORDING
    ctrl.stop_recording()                          # overlay ✓ while still held
    assert gesture.state == "STOP_WAIT"
    clock.advance(1.0)
    gesture.key_up()                               # the physical release
    assert gesture.state == "IDLE"
    assert trans.calls == 1                        # stopped exactly once
    # reusable
    gesture.key_down()
    assert ctrl.sm.state == DictationState.RECORDING


# --- bug: a gesture rebuilt mid-recording could never stop it --------------
def test_fresh_gesture_can_stop_a_recording_it_never_started():
    # After a hotkey change mid-recording the app builds a NEW gesture (IDLE) in
    # front of a live recording. is_recording lets its next press toggle that
    # recording off instead of being swallowed as a refused start.
    gesture, ctrl, rec, trans, inserted, clock, sched = wire()
    gesture.key_down(); clock.advance(0.1); gesture.key_up()
    clock.advance(0.1); gesture.key_down(); gesture.key_up()   # hands-free
    assert ctrl.sm.state == DictationState.RECORDING

    fresh = TapHoldGesture(
        on_start=ctrl.start_recording, on_stop=ctrl.stop_recording,
        on_cancel=ctrl.cancel_recording, is_recording=ctrl.is_recording,
        tap_max=TAP_MAX, double_gap=DOUBLE_GAP, clock=clock, scheduler=sched)
    assert fresh.state == "IDLE"

    fresh.key_down()                               # a press on the fresh gesture
    assert ctrl.sm.state == DictationState.IDLE    # stopped (processed inline)
    assert trans.calls == 1                        # the recording was finished
    fresh.key_up()
    assert fresh.state == "IDLE"                    # reusable
