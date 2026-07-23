"""The hook thread must do almost nothing.

Root cause of the reported dead-hotkey: pynput runs every key callback on the
thread that services the low-level keyboard hook, and Windows silently REMOVES a
hook whose callback runs long (the start-recording path opens the mic stream
synchronously — tens to hundreds of ms). The fix moves all of that off the hook
thread: ``_on_press`` / ``_on_release`` only canonicalize + hand off to a
dispatcher; a single worker runs the combo -> gesture -> controller chain.
"""
import threading
import time

from pynput import keyboard

from rekounts.hotkey_manager import (HotkeyManager, _InlineDispatcher,
                                        _ThreadedDispatcher)


class FakeListener:
    """canonical() returns the key unchanged (the scan-less generic path)."""

    def canonical(self, key):
        return key


# --- the threaded dispatcher itself ---------------------------------------
def test_runs_work_off_the_calling_thread():
    d = _ThreadedDispatcher()
    d.start()
    try:
        caller = threading.get_ident()
        ran_on, done = [], threading.Event()
        d.submit(lambda: (ran_on.append(threading.get_ident()), done.set()))
        assert done.wait(2.0)
        assert ran_on and ran_on[0] != caller
    finally:
        d.stop()


def test_preserves_submission_order():
    d = _ThreadedDispatcher()
    d.start()
    try:
        seen, done = [], threading.Event()
        for i in range(50):
            d.submit(lambda i=i: seen.append(i))
        d.submit(done.set)
        assert done.wait(2.0)
        assert seen == list(range(50))
    finally:
        d.stop()


def test_a_slow_handler_never_blocks_the_submitter():
    # This is the crux: submitting (all the hook thread does) returns at once
    # even while a slow handler (the mic open) is still running on the worker.
    d = _ThreadedDispatcher()
    d.start()
    try:
        started, release = threading.Event(), threading.Event()
        d.submit(lambda: (started.set(), release.wait(2.0)))
        assert started.wait(2.0)
        t0 = time.monotonic()
        d.submit(lambda: None)
        assert time.monotonic() - t0 < 0.2      # did not wait on the slow one
        release.set()
    finally:
        d.stop()


def test_worker_survives_a_raising_handler():
    d = _ThreadedDispatcher()
    d.start()
    try:
        seen, done = [], threading.Event()
        d.submit(lambda: (_ for _ in ()).throw(RuntimeError("boom")))
        d.submit(lambda: (seen.append("after"), done.set()))
        assert done.wait(2.0)
        assert seen == ["after"]
    finally:
        d.stop()


def test_stop_is_safe_before_start():
    _ThreadedDispatcher().stop()        # must not raise


# --- the manager hands off instead of running inline ----------------------
def test_on_press_hands_off_to_the_dispatcher():
    submitted = []

    class RecordingDispatcher:
        def start(self):
            pass

        def stop(self):
            pass

        def submit(self, fn):
            submitted.append(fn)

    events = []
    m = HotkeyManager("ctrl+win",
                      on_start=lambda: events.append("start"),
                      on_stop=lambda: events.append("stop"),
                      dispatcher=RecordingDispatcher(), watchdog=False)
    m._listener = FakeListener()
    m._on_press(keyboard.Key.ctrl)
    m._on_press(keyboard.Key.cmd)
    assert events == []                 # nothing ran on the hook thread
    assert len(submitted) == 2          # both were queued for the worker
    for fn in submitted:
        fn()                            # draining them drives the gesture
    assert events == ["start"]


def test_on_press_after_stop_submits_nothing():
    submitted = []

    class RecordingDispatcher:
        def start(self):
            pass

        def stop(self):
            pass

        def submit(self, fn):
            submitted.append(fn)

    m = HotkeyManager("ctrl+win", on_start=lambda: None, on_stop=lambda: None,
                      dispatcher=RecordingDispatcher(), watchdog=False)
    m._listener = FakeListener()
    m.stop()                            # detaches the listener
    m._on_press(keyboard.Key.ctrl)
    m._on_release(keyboard.Key.ctrl)
    assert submitted == []              # a late/queued callback drives nothing


def test_a_raising_canonical_does_not_escape_the_callback():
    # A callback that raises makes pynput stop the listener thread invisibly
    # (our stop() never join()s to surface it). _on_press must swallow it.
    class AngryListener:
        def canonical(self, key):
            raise RuntimeError("layout gone")

    m = HotkeyManager("ctrl+win", on_start=lambda: None, on_stop=lambda: None,
                      dispatcher=_InlineDispatcher(), watchdog=False)
    m._listener = AngryListener()
    m._on_press(keyboard.Key.ctrl)      # must not raise
    m._on_release(keyboard.Key.ctrl)


def test_manager_dispatches_events_through_a_real_worker():
    # End to end: _on_press on a real threaded worker drives the gesture.
    fired = threading.Event()
    events = []
    m = HotkeyManager(
        "ctrl+win",
        on_start=lambda: (events.append("start"), fired.set()),
        on_stop=lambda: events.append("stop"),
        dispatcher=_ThreadedDispatcher(), watchdog=False)
    m._dispatcher.start()
    try:
        m._listener = FakeListener()
        m._on_press(keyboard.Key.ctrl)
        m._on_press(keyboard.Key.cmd)
        assert fired.wait(2.0)
        assert events == ["start"]
    finally:
        m._dispatcher.stop()


def test_events_are_stamped_with_the_hook_time_clock():
    # The timestamp handed to the combo is read when the event ARRIVES; a quick
    # tap therefore stays a tap even if processing is delayed. Here we drive the
    # whole path with an injected clock and prove the release is classified by
    # the observed time.
    now = [100.0]
    events = []
    m = HotkeyManager("ctrl+win",
                      on_start=lambda: events.append("start"),
                      on_stop=lambda: events.append("stop"),
                      clock=lambda: now[0], dispatcher=_InlineDispatcher(),
                      watchdog=False)
    m._listener = FakeListener()
    m._on_press(keyboard.Key.ctrl)
    m._on_press(keyboard.Key.cmd)       # combo completes -> start (press at 100)
    now[0] = 100.10                     # 0.1s later
    m._on_release(keyboard.Key.ctrl)    # release observed at 100.10 -> a tap
    assert events == ["start"]
    assert m.gesture.state == "TAP_WAIT"
