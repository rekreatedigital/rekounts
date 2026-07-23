"""HotkeyWatchdog: recover a silently-dead hook and a stuck combo.

Windows removes a low-level keyboard hook whose callback runs long, and pynput
stops the listener thread on any unhandled callback exception — both leave the
hotkey dead for the session with no signal. The watchdog polls OS ground truth
(the combo's own keys) each tick and rebuilds/heals. Everything is injected, so
the logic is exercised here with no real hook and no OS calls. tick() is driven
directly (the daemon loop just calls it on an interval).
"""
from rekounts.hotkey_manager import HotkeyWatchdog


class Clock:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t

    def advance(self, dt):
        self.t += dt


def make(reconcile=None):
    state = {"alive": True, "down": False, "active": False}
    calls = {"rebuild": 0, "reconcile": 0}
    clock = Clock()

    def _reconcile():
        calls["reconcile"] += 1
        return False

    wd = HotkeyWatchdog(
        is_alive=lambda: state["alive"],
        combo_down=lambda: state["down"],
        combo_active=lambda: state["active"],
        rebuild=lambda: calls.__setitem__("rebuild", calls["rebuild"] + 1),
        reconcile=reconcile or _reconcile,
        clock=clock, miss_ticks=2, rebuild_cooldown=2.0)
    return wd, state, calls, clock


def _tick(wd, clock, n=1):
    for _ in range(n):
        clock.advance(0.15)
        wd.tick()


# --- no false positives ----------------------------------------------------
def test_a_healthy_held_combo_never_rebuilds():
    wd, state, calls, clock = make()
    state["down"] = True
    state["active"] = True              # the hook saw the press
    _tick(wd, clock, 10)
    assert calls["rebuild"] == 0


def test_mouse_only_activity_never_rebuilds():
    # The combo keys are never down, so there is nothing to detect no matter how
    # long the listener is "silent" — this is why we poll the combo keys and not
    # GetLastInputInfo.
    wd, state, calls, clock = make()
    _tick(wd, clock, 50)
    assert calls["rebuild"] == 0


def test_a_fast_tap_does_not_trip_the_miss_detector():
    # One isolated poll catching keys-down-not-yet-active must not rebuild;
    # detection requires miss_ticks consecutive polls.
    wd, state, calls, clock = make()
    state["down"] = True
    state["active"] = False
    _tick(wd, clock, 1)                 # a single miss
    assert calls["rebuild"] == 0


# --- silent hook removal ---------------------------------------------------
def test_silent_hook_removal_is_detected_and_rebuilt():
    wd, state, calls, clock = make()
    state["down"] = True               # keys physically down...
    state["active"] = False            # ...but the tracker never saw the press
    _tick(wd, clock, 1)
    assert calls["rebuild"] == 0       # 1st miss
    _tick(wd, clock, 1)
    assert calls["rebuild"] == 1       # 2nd miss -> rebuild


def test_rebuild_fires_once_per_key_down_episode():
    wd, state, calls, clock = make()
    state["down"] = True
    state["active"] = False
    _tick(wd, clock, 2)                # rebuild #1
    assert calls["rebuild"] == 1
    _tick(wd, clock, 10)               # keys still down -> no repeat rebuilds
    assert calls["rebuild"] == 1
    # keys come up (episode ends), then a fresh dead press after the cooldown
    state["down"] = False
    _tick(wd, clock, 1)
    state["down"] = True
    clock.advance(3.0)                 # past the 2s cooldown
    _tick(wd, clock, 2)
    assert calls["rebuild"] == 2


def test_rebuild_is_rate_limited_by_the_cooldown():
    wd, state, calls, clock = make()
    state["down"] = True
    state["active"] = False
    _tick(wd, clock, 2)                # rebuild #1
    assert calls["rebuild"] == 1
    state["down"] = False              # end the episode...
    _tick(wd, clock, 1)
    state["down"] = True               # ...and immediately present another dead
    _tick(wd, clock, 2)               # press, still within the cooldown window
    assert calls["rebuild"] == 1       # suppressed


# --- dead listener thread (a callback raised) ------------------------------
def test_dead_listener_thread_rebuilds_even_when_idle():
    wd, state, calls, clock = make()
    state["alive"] = False
    _tick(wd, clock, 1)
    assert calls["rebuild"] == 1


def test_dead_listener_thread_rebuilds_with_keys_down():
    wd, state, calls, clock = make()
    state["alive"] = False
    state["down"] = True
    _tick(wd, clock, 1)
    assert calls["rebuild"] == 1


# --- stuck-combo self-heal -------------------------------------------------
def _counting_reconcile():
    healed = {"n": 0}

    def reconcile():
        healed["n"] += 1
        return True

    return reconcile, healed


def test_stuck_combo_is_healed_after_the_sustain():
    # tracker active + keys physically UP (a lost key-up), sustained heal_ticks.
    reconcile, healed = _counting_reconcile()
    wd, state, calls, clock = make(reconcile=reconcile)
    state["active"] = True
    state["down"] = False
    _tick(wd, clock, 1)
    assert healed["n"] == 0            # 1st up-reading (heal_ticks == 2)
    _tick(wd, clock, 1)
    assert healed["n"] == 1            # 2nd -> heal
    assert calls["rebuild"] == 0       # healing is not a rebuild


def test_a_queued_release_is_not_stolen_by_the_heal():
    # active + up for a single tick — a release still queued behind a slow
    # handler — must NOT heal; it clears next tick as the worker catches up.
    reconcile, healed = _counting_reconcile()
    wd, state, calls, clock = make(reconcile=reconcile)
    state["active"] = True
    state["down"] = False
    _tick(wd, clock, 1)               # 1st up-reading
    assert healed["n"] == 0
    state["active"] = False           # worker processed the queued release
    _tick(wd, clock, 1)               # sustain broken
    assert healed["n"] == 0


def test_heal_does_not_fire_while_keys_are_down():
    reconcile, healed = _counting_reconcile()
    wd, state, calls, clock = make(reconcile=reconcile)
    state["active"] = True
    state["down"] = True              # genuinely held
    _tick(wd, clock, 5)
    assert healed["n"] == 0


# --- robustness ------------------------------------------------------------
def test_tick_survives_a_failing_provider():
    def boom():
        raise RuntimeError("nope")

    wd = HotkeyWatchdog(is_alive=boom, combo_down=boom, combo_active=boom,
                        rebuild=boom, reconcile=boom, clock=Clock())
    wd.tick()                          # must not raise


def test_start_and_stop_are_safe():
    wd, state, calls, clock = make()
    wd.start()
    wd.stop()                          # daemon thread exits on the stop event
