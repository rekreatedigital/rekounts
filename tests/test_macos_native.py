"""The macOS port against the REAL pyobjc frameworks — no fakes.

Why this file exists
--------------------
Every other mac test in this suite drives the port through fakes
(``tests/test_text_inserter_macos.py``, ``test_permissions.py``,
``test_startup_macos.py``, ``test_overlay_macos.py``, ``test_sounds_macos.py``).
That is the right way to test *policy*, and it runs anywhere. But it means the
green ``macos-latest`` CI leg proved something much narrower than it looked:
``requirements-test.txt`` contains **no pyobjc at all**, so CI had never once
executed a real Quartz, AppKit, ApplicationServices or AVFoundation call. A
misspelled symbol, a wrong argument count, a framework that no longer ships the
function we name — none of that could fail.

This module closes that gap without a Mac in the room. It runs on the
``pytest-macos-runtime`` CI leg, which installs the full ``requirements.txt``
(pyobjc included), and it:

  * imports the four frameworks the port names;
  * builds the real :class:`_MacBackend` against them;
  * round-trips the NSPasteboard backup/restore path, which until now was pure
    inference;
  * creates the real CGEvents for a paste and for unicode typing — and asserts
    they are NOT posted, because a test that injects keystrokes into a CI runner
    is a test that breaks the runner.

What it deliberately does NOT prove: anything gated on TCC consent. A CI runner
has no Accessibility or Input Monitoring grant, and nothing here asks for one.
The probes are asserted to *answer* (True/False/None, never an exception), not
to answer yes. Whether a granted permission then makes CGEventPost actually
deliver is the hardware question, and it stays in MACOS-TESTING.md.

The env-var guard is the point of the whole file
-------------------------------------------------
``REKOUNTS_REQUIRE_MACOS_NATIVE=1`` (set by the new CI leg, and by anyone
running it deliberately on a Mac) turns "pyobjc is missing" from a **skip** into
a **failure**. Without that, the leg could install a broken dependency set, skip
every test in this file, and report green — which is exactly the trap the
existing macos leg fell into.
"""
from __future__ import annotations

import os
import sys

import pytest

REQUIRED = os.environ.get("REKOUNTS_REQUIRE_MACOS_NATIVE") == "1"

# The frameworks, and the app module that needs each one.
FRAMEWORKS = {
    "Quartz": "text_inserter events, permissions preflight, hotkey key-state poll",
    "AppKit": "NSPasteboard clipboard, NSWorkspace frontmost app",
    "ApplicationServices": "AXIsProcessTrusted (Accessibility preflight)",
    "AVFoundation": "microphone consent state",
    "objc": "overlay NSPanel behavior (objc.objc_object on winId())",
}


def _missing_frameworks() -> list[str]:
    missing = []
    for name in FRAMEWORKS:
        try:
            __import__(name)
        except Exception:
            missing.append(name)
    return missing


if sys.platform != "darwin":
    if REQUIRED:
        raise RuntimeError(
            "REKOUNTS_REQUIRE_MACOS_NATIVE=1 on a non-darwin platform "
            f"({sys.platform}). This leg only means anything on macOS.")
    pytest.skip("the real mac frameworks only exist on darwin",
                allow_module_level=True)

_MISSING = _missing_frameworks()
if _MISSING:
    detail = ", ".join(f"{n} ({FRAMEWORKS[n]})" for n in _MISSING)
    if REQUIRED:
        # A hard failure on purpose: see the module docstring.
        raise RuntimeError(
            "REKOUNTS_REQUIRE_MACOS_NATIVE=1 but pyobjc is not importable: "
            f"{detail}. Install the runtime set (pip install -r "
            "requirements.txt) — a skip here would let CI report green while "
            "proving nothing about the mac code paths.")
    pytest.skip(f"pyobjc not installed: {detail}", allow_module_level=True)


# --- the frameworks themselves ---------------------------------------------
@pytest.mark.parametrize("name", sorted(FRAMEWORKS))
def test_the_framework_imports(name):
    __import__(name)


def test_every_quartz_symbol_the_port_names_exists():
    """Names, not behavior. A typo'd CoreGraphics function is a startup crash on
    a user's Mac and is invisible to a faked test — the fake defines the name."""
    import Quartz
    for symbol in ("CGPreflightListenEventAccess",
                   "CGEventSourceKeyState",
                   "CGEventCreateKeyboardEvent",
                   "CGEventKeyboardSetUnicodeString",
                   "CGEventSetFlags",
                   "CGEventPost",
                   "kCGHIDEventTap",
                   "kCGEventFlagMaskCommand",
                   "kCGEventSourceStateHIDSystemState"):
        assert hasattr(Quartz, symbol), f"Quartz has no {symbol}"


def test_every_appkit_symbol_the_port_names_exists():
    import AppKit
    for symbol in ("NSPasteboard", "NSPasteboardItem", "NSPasteboardTypeString",
                   "NSWorkspace"):
        assert hasattr(AppKit, symbol), f"AppKit has no {symbol}"


def test_the_accessibility_and_microphone_entry_points_exist():
    from ApplicationServices import AXIsProcessTrusted
    assert callable(AXIsProcessTrusted)
    import AVFoundation
    assert hasattr(AVFoundation.AVCaptureDevice,
                   "authorizationStatusForMediaType_")
    assert hasattr(AVFoundation, "AVMediaTypeAudio")


# --- every mac-touching app module actually imports -------------------------
def test_the_whole_app_imports_with_pyobjc_present():
    """Not a tautology: several of these import pyobjc lazily inside functions,
    so a bad import there only shows up when the function runs."""
    import importlib
    for module in ("rekounts.permissions", "rekounts.text_inserter",
                   "rekounts.hotkey_manager", "rekounts.startup",
                   "rekounts.sounds", "rekounts.paths", "rekounts.__main__",
                   "rekounts.ui.overlay", "rekounts.ui.scratchpad",
                   "rekounts.ui.settings_page", "rekounts.ui.platform_text"):
        importlib.import_module(module)


# --- permissions: the real TCC probes --------------------------------------
def test_the_real_permission_probes_answer_instead_of_raising():
    """Each probe must return True/False/None on a machine with no grants.

    ``None`` (unreadable / not yet determined) is a legitimate answer and is
    deliberately NOT reported to the user as a denial — see
    rekounts/permissions.py. What must never happen is an exception, because the
    check runs during startup.
    """
    from rekounts.permissions import (
        _probe_accessibility,
        _probe_input_monitoring,
        _probe_microphone,
    )
    for probe in (_probe_input_monitoring, _probe_accessibility,
                  _probe_microphone):
        assert probe() in (True, False, None)


def test_check_permissions_returns_the_three_real_states():
    from rekounts.permissions import check_permissions, missing_permission_messages
    states = check_permissions()          # real probes, no injection
    assert [s.name for s in states] == ["Input Monitoring", "Accessibility",
                                        "Microphone"]
    for state in states:
        assert state.granted in (True, False, None)
        assert "System Settings" in state.guidance
    # Whatever the runner's TCC state, this must not raise and must only ever
    # return guidance for definite denials.
    for message in missing_permission_messages(states):
        assert message in [s.guidance for s in states]


def test_the_hotkey_watchdog_gate_is_derived_from_the_real_preflight():
    """The watchdog is only built when the key-state poll is TRUSTED, and on
    darwin that means ``CGPreflightListenEventAccess`` said yes.

    ### A finding, recorded here because it cost a red CI run to learn

    This test first asserted ``trusted is False`` on the reasoning that a CI
    runner cannot have been granted Input Monitoring. **On the GitHub
    macos-latest (arm64) runner, the real ``CGPreflightListenEventAccess()``
    returns True.** Nobody clicked anything.

    Whatever the cause — a runner image with the TCC database pre-authorised, or
    a preflight that is simply more permissive than its name suggests — the
    consequence for Rekounts is the same and it is not reassuring: **the gate
    will happily open on a machine where no human granted anything.** The design
    comment on ``_key_state_poll`` treats a passing preflight as evidence that
    the poll can be believed, and this is one concrete environment where that
    inference does not hold.

    That does not make the gate useless (it still closes when the preflight says
    no), but it does mean the "long hold self-releases" failure it was built to
    prevent is NOT ruled out by the gate alone. It stays the first thing to check
    on real hardware — MACOS-TESTING.md §2, docs/macos-one-hour.md Q1.

    So the assertion here is the one that is true in every environment and still
    worth making: the answer is *read from the API*, not hardcoded, in both
    directions.
    """
    from rekounts.hotkey_manager import _darwin_key_down, _key_state_poll

    poll, trusted = _key_state_poll()
    assert poll is _darwin_key_down
    assert isinstance(trusted, bool)

    # Swap the module rather than setattr-ing on the pyobjc one: _key_state_poll
    # does `import Quartz` at call time, so sys.modules is the seam, and poking
    # attributes on a lazily-populated framework module is not a promise pyobjc
    # makes.
    class _Preflight:
        def __init__(self, answer):
            self._answer = answer

        def CGPreflightListenEventAccess(self):
            return self._answer

    mp = pytest.MonkeyPatch()
    try:
        for answer in (False, True):
            mp.setitem(sys.modules, "Quartz", _Preflight(answer))
            assert _key_state_poll()[1] is answer, (
                "the watchdog trust gate is not reading "
                "CGPreflightListenEventAccess")
    finally:
        mp.undo()

    # Back on the real framework, and the poll itself must answer (whether it
    # answers TRUTHFULLY under TCC is the open hardware question).
    assert _darwin_key_down(59) in (True, False)   # left Control


# --- the insertion backend against real Quartz/AppKit ----------------------
@pytest.fixture
def backend():
    from rekounts.text_inserter import _MacBackend
    return _MacBackend()


def test_the_app_picks_the_mac_backend_on_a_mac():
    from rekounts.text_inserter import _MacBackend, _make_backend
    assert isinstance(_make_backend(), _MacBackend)


def test_the_backend_constructs_against_the_real_general_pasteboard(backend):
    assert backend.available is True
    # changeCount is how the restore-skip gate knows the user copied something
    # of their own between our paste and our restore. A None here would silently
    # disable that gate.
    assert isinstance(backend.clipboard_sequence(), int)


def test_modifiers_down_reads_the_real_key_state(backend):
    """CGEventSourceKeyState needs no TCC grant to *answer* (whether it answers
    TRUTHFULLY under TCC is the open hardware question — MACOS-TESTING.md §2).
    Here we only prove the call shape is right and it returns a bool."""
    assert backend.modifiers_down() in (True, False)


def test_foreground_window_reads_the_real_frontmost_app(backend):
    hwnd = backend.foreground_window()
    assert hwnd is None or isinstance(hwnd, int)
    # is_no_target's only clear-cut case is "no frontmost app at all".
    assert backend.is_no_target(hwnd) is (not hwnd)
    # macOS has no UIPI equivalent, so nothing is ever "blocked".
    assert backend.is_blocked(hwnd) is False


def test_the_clipboard_round_trips_through_real_nspasteboard(backend):
    """The backup/restore path — write items, snapshot, clobber, restore — has
    never been executed against a real NSPasteboard. It is what stops a
    dictation from eating whatever the user had copied."""
    original = backend.backup_clipboard()
    try:
        backend.set_clipboard_text("rekounts-native-test-α")
        first = backend.clipboard_sequence()
        assert isinstance(first, int)

        snapshot = backend.backup_clipboard()
        assert snapshot, "a pasteboard holding text must snapshot to something"

        backend.set_clipboard_text("clobbered")
        # clearContents bumps changeCount; the restore-skip gate depends on it.
        assert backend.clipboard_sequence() > first

        backend.restore_clipboard(snapshot)
        import AppKit
        restored = AppKit.NSPasteboard.generalPasteboard().stringForType_(
            AppKit.NSPasteboardTypeString)
        assert restored == "rekounts-native-test-α"
    finally:
        # Leave the runner's pasteboard as we found it. restore_clipboard is a
        # no-op on an empty snapshot (nothing to put back), so an empty
        # pasteboard has to be cleared by hand or our test string lingers.
        if original:
            backend.restore_clipboard(original)
        else:
            import AppKit
            AppKit.NSPasteboard.generalPasteboard().clearContents()


# --- real CGEvents, created but never posted -------------------------------
class _Recorder:
    """Swaps out _MacBackend._post so real events are created and dropped.

    Everything up to the post is genuine Quartz: CGEventCreateKeyboardEvent,
    CGEventSetFlags, CGEventKeyboardSetUnicodeString. Only delivery is stubbed,
    because posting synthetic keystrokes on a CI runner types into whatever has
    focus there.
    """

    def __init__(self, backend):
        self.events = []
        backend._post = self.events.append


def test_the_paste_event_pair_is_real_quartz_with_the_command_flag(backend):
    import Quartz

    from rekounts.text_inserter import _KVK_ANSI_V
    rec = _Recorder(backend)
    backend.send_paste()
    assert len(rec.events) == 2, "a Cmd+V is one key-down and one key-up"
    for event in rec.events:
        assert event is not None, "CGEventCreateKeyboardEvent returned NULL"
        flags = Quartz.CGEventGetFlags(event)
        assert flags & Quartz.kCGEventFlagMaskCommand, \
            "the Command flag must ride on the V events themselves"
        assert Quartz.CGEventGetIntegerValueField(
            event, Quartz.kCGKeyboardEventKeycode) == _KVK_ANSI_V


def test_unicode_typing_builds_real_events_and_a_real_return_key(backend):
    """Chunking is measured in UTF-16 units, which only the real API can check:
    an astral-plane character counts as two, and getting it wrong truncates."""
    import Quartz
    from rekounts.text_inserter import _KVK_RETURN, _MAC_UNICODE_CHUNK

    rec = _Recorder(backend)
    text = "héllo wörld " + ("x" * (_MAC_UNICODE_CHUNK + 3)) + "\nsecond line 😀"
    assert backend.type_unicode(text) is True
    assert rec.events, "nothing was built"
    for event in rec.events:
        assert event is not None

    keycodes = [Quartz.CGEventGetIntegerValueField(
        e, Quartz.kCGKeyboardEventKeycode) for e in rec.events]
    # A real Return keycode for the newline, not a typed "\n" character.
    assert _KVK_RETURN in keycodes
    # Every other event is a keycode-0 unicode carrier.
    assert set(keycodes) <= {0, _KVK_RETURN}


def test_typing_stops_between_chunks_when_the_target_goes_away(backend):
    """The should_continue hook is what keeps a long dictation from spraying
    into another app; prove it aborts against the real event path too."""
    rec = _Recorder(backend)
    seen = []

    def should_continue():
        seen.append(1)
        return len(seen) < 2

    assert backend.type_unicode("a" * 200, should_continue=should_continue) is False
    assert len(rec.events) < 200, "it kept going after the target went away"


def test_delivery_funnels_through_the_one_method_the_tests_can_stub():
    """Guard rail for the recorder pattern above.

    Stubbing ``_post`` is what keeps this file from typing into whatever has
    focus on the CI runner. That only works while ``CGEventPost`` is called from
    exactly one place, so assert it in the source rather than trusting it: a
    future edit that posts directly would silently start injecting keystrokes
    into CI, and the symptom would be a mysteriously flaky unrelated job.
    """
    import inspect

    from rekounts.text_inserter import _MacBackend
    source = inspect.getsource(_MacBackend)
    assert source.count("CGEventPost") == 1
    assert "CGEventPost" in inspect.getsource(_MacBackend._post)


# --- the overlay's native panel tweaks -------------------------------------
def test_the_overlay_panel_tweak_is_inert_without_a_cocoa_qt_platform():
    """``_apply_mac_panel_behavior`` wraps winId() as an NSView, which is a
    SEGFAULT (not an exception) under the offscreen platform. The guard that
    stops that is the only thing making the Qt tests safe on a Mac, so assert it
    with pyobjc actually present — the case where the guard matters."""
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6 import QtGui, QtWidgets

    from rekounts.ui.overlay import _apply_mac_panel_behavior, _mac_native_enabled

    assert _mac_native_enabled({}) is True          # default ON
    assert _mac_native_enabled({"REKOUNTS_MAC_OVERLAY_NATIVE": "0"}) is False

    QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    if QtGui.QGuiApplication.platformName() == "cocoa":
        # A real window server turned up (a logged-in Mac rather than the
        # offscreen CI session). Calling the tweak here WOULD be the real thing,
        # which is a hardware check, not this file's job — MACOS-TESTING.md §4.
        pytest.skip("Qt is driving Cocoa; the guard under test is not the "
                    "code path taken")
    widget = QtWidgets.QWidget()
    # Must return without touching the native window at all.
    assert _apply_mac_panel_behavior(widget) is None
