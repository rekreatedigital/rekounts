"""Unit tests for TextInserter policy, using a fully mocked platform backend.

The Win32 layer is never exercised here; instead a FakeBackend records calls and
lets each test drive the conditions (modifiers held, elevated target, focus
change, clipboard sequence, exceptions) so the policy is tested in isolation.
Two small tests do touch the real Win32 backend on Windows to sanity-check it
constructs and reports a plausible outcome.
"""

import sys
import time

import pytest

from rekounts.text_inserter import (
    InsertResult,
    TextInserter,
    _NullBackend,
    _WaitBudget,
)


class FakeBackend:
    """Records calls and returns scripted values so policy can be tested alone."""

    def __init__(self, *, hwnd=100, no_target=False, blocked=False,
                 modifier_sequence=None, seq_values=None,
                 fail_set_text=False, foreground_sequence=None):
        # foreground_sequence: successive values returned by foreground_window()
        self._fg = list(foreground_sequence) if foreground_sequence else None
        self._hwnd = hwnd
        self.no_target = no_target
        self.blocked = blocked
        # modifier_sequence: successive bools for modifiers_down() (drains, then False)
        self._mods = list(modifier_sequence) if modifier_sequence else []
        # seq_values: successive clipboard_sequence() returns
        self._seq = list(seq_values) if seq_values else None
        self.fail_set_text = fail_set_text

        self.type_complete = True   # flip to False to simulate a focus change
        self.should_continue = None
        # How many SendInput-style chunks type_unicode should pretend to send.
        # >1 makes it consult should_continue BETWEEN chunks, exactly as the
        # real Win32/mac backends do (never before the first one).
        self.chunks = 1
        self.gate_calls = 0
        # True keeps modifiers_down() True forever, whatever modifier_sequence
        # says — a finger resting on Alt.
        self.modifiers_stuck = False
        self.calls = []
        self.set_text = None
        self.restored = "UNSET"
        self.backup_returns = {13: "prior clipboard text"}
        self.pastes = 0
        self.typed = []

    # window / focus
    def foreground_window(self):
        if self._fg is not None:
            return self._fg.pop(0) if len(self._fg) > 1 else self._fg[0]
        return self._hwnd

    def is_no_target(self, hwnd):
        return self.no_target

    def is_blocked(self, hwnd):
        return self.blocked

    # modifiers
    def modifiers_down(self):
        if self.modifiers_stuck:
            return True
        if self._mods:
            return self._mods.pop(0)
        return False

    # clipboard
    def clipboard_sequence(self):
        if self._seq:
            return self._seq.pop(0)
        return 42

    def backup_clipboard(self):
        self.calls.append("backup")
        return self.backup_returns

    def restore_clipboard(self, snapshot):
        self.calls.append("restore")
        self.restored = snapshot

    def set_clipboard_text(self, text):
        self.calls.append("set_text")
        if self.fail_set_text:
            raise RuntimeError("clipboard busy")
        self.set_text = text

    # input
    def send_paste(self):
        self.calls.append("paste")
        self.pastes += 1

    def type_unicode(self, text, delay=0.0, should_continue=None):
        self.calls.append("type")
        self.typed.append(text)
        # Real backends report whether the whole message got delivered; the
        # policy layer turns False into an undelivered outcome + a clipboard
        # fallback.
        self.should_continue = should_continue
        if should_continue is not None:
            for _ in range(self.chunks - 1):
                self.gate_calls += 1
                if not should_continue():
                    return False
        return self.type_complete


def make(mode="paste", **backend_kwargs):
    be = FakeBackend(**backend_kwargs)
    ins = TextInserter(mode=mode, restore_delay=0, modifier_timeout=0.2, backend=be)
    return ins, be


# --------------------------------------------------------------------------
# Return-value contract
# --------------------------------------------------------------------------
def test_empty_text_returns_skipped_and_does_nothing():
    ins, be = make()
    assert ins.insert("") == InsertResult.SKIPPED
    assert be.calls == []


def test_paste_returns_pasted():
    ins, be = make()
    assert ins.insert("hello") == InsertResult.PASTED
    assert be.set_text == "hello"
    assert be.pastes == 1


def test_result_is_plain_string():
    # history layer can store the outcome as a bare string
    ins, be = make()
    r = ins.insert("hi")
    assert r == "pasted"
    assert isinstance(r, str)
    assert str(r) == "pasted"


def test_keystroke_mode_returns_typed():
    ins, be = make(mode="keystroke")
    assert ins.insert("hello") == InsertResult.TYPED
    assert be.typed == ["hello"]
    assert be.pastes == 0


# --------------------------------------------------------------------------
# Clipboard backup/restore + sequence guard
# --------------------------------------------------------------------------
def test_paste_backs_up_and_restores_full_snapshot():
    ins, be = make()
    ins.insert("new text")
    assert be.calls == ["backup", "set_text", "paste", "restore"]
    # restored the ENTIRE backup snapshot (all formats), not just text
    assert be.restored == be.backup_returns


def test_restore_skipped_when_clipboard_changed_after_paste():
    # seq returned after set_text = 10; seq after paste = 11 -> someone else copied
    ins, be = make(seq_values=[10, 11])
    ins.insert("x")
    assert "restore" not in be.calls  # do NOT clobber the user's newer clipboard


def test_restore_happens_when_sequence_unchanged():
    ins, be = make(seq_values=[10, 10])
    ins.insert("x")
    assert "restore" in be.calls


def test_clipboard_is_given_back_even_when_the_paste_raises():
    """A borrowed clipboard is always returned, including down the failure path.

    SendInput can genuinely raise on Windows (UIPI, a stuck low-level hook).
    Without this, insert() swallows the error and falls back to typing, so the
    user is never told — and their clipboard silently keeps the transcript
    instead of whatever they had copied.
    """
    ins, be = make()
    be.send_paste = _raising(be, "paste", OSError("SendInput refused"))

    assert ins.insert("new text") == InsertResult.TYPED   # fell back to typing
    # restore lands BEFORE the fallback typing: the clipboard is given back the
    # moment the paste fails, not left dangling for the rest of the delivery.
    assert be.calls == ["backup", "set_text", "paste", "restore", "type"]
    assert be.restored == be.backup_returns


def test_a_failed_restore_does_not_mask_the_paste_failure():
    """If giving the clipboard back also fails, the caller still gets to fall back."""
    ins, be = make()
    be.send_paste = _raising(be, "paste", OSError("SendInput refused"))
    be.restore_clipboard = _raising(be, "restore", RuntimeError("clipboard locked"))

    assert ins.insert("new text") == InsertResult.TYPED
    assert be.calls == ["backup", "set_text", "paste", "restore", "type"]


def _raising(be, label, exc):
    """A backend method that records it was called, then raises."""
    def fail(*args, **kwargs):
        be.calls.append(label)
        raise exc
    return fail


# --------------------------------------------------------------------------
# Guards: no target / elevation / focus change
# --------------------------------------------------------------------------
def test_no_target_returns_no_target_without_pasting():
    ins, be = make(no_target=True)
    assert ins.insert("hello") == InsertResult.NO_TARGET
    assert be.pastes == 0
    assert be.typed == []          # nothing was sprayed at the non-target


def test_no_target_leaves_the_clipboard_untouched():
    be = FakeBackend(no_target=True)
    ins = TextInserter(restore_delay=0, modifier_timeout=0.05, backend=be)
    assert ins.insert("hello") == InsertResult.NO_TARGET
    assert "set_text" not in be.calls


def test_elevated_window_returns_blocked():
    ins, be = make(blocked=True)
    assert ins.insert("hello") == InsertResult.BLOCKED
    assert be.pastes == 0


def test_focus_change_aborts_with_no_target():
    # target captured = 500, but current foreground is 999 -> focus moved
    ins, be = make(hwnd=999)
    assert ins.insert("hello", target=500) == InsertResult.NO_TARGET
    assert be.pastes == 0


def test_focus_unchanged_pastes_normally():
    ins, be = make(hwnd=500)
    assert ins.insert("hello", target=500) == InsertResult.PASTED
    assert be.pastes == 1


def test_captured_target_is_current_foreground_when_not_passed():
    # no explicit target -> uses foreground at insert() entry; a later change is
    # detected because _guard re-reads the (same, here) foreground.
    ins, be = make(hwnd=700)
    assert ins.insert("hello") == InsertResult.PASTED


# --------------------------------------------------------------------------
# Modifier-release wait
# --------------------------------------------------------------------------
def test_waits_for_modifiers_then_pastes():
    # modifiers down for two polls, then released
    ins, be = make(modifier_sequence=[True, True, False])
    assert ins.insert("hello") == InsertResult.PASTED
    assert be.pastes == 1


def test_modifier_timeout_still_proceeds():
    # modifiers never release; with a 0.2s timeout we proceed (best effort)
    be = FakeBackend()
    be.modifiers_down = lambda: True  # always held
    ins = TextInserter(restore_delay=0, modifier_timeout=0.05, backend=be)
    assert ins.insert("hello") == InsertResult.PASTED


# --------------------------------------------------------------------------
# Fallback + failure paths
# --------------------------------------------------------------------------
def test_paste_failure_falls_back_to_typing():
    ins, be = make(fail_set_text=True)
    assert ins.insert("hello") == InsertResult.TYPED
    assert be.typed == ["hello"]


def test_total_failure_returns_failed():
    ins, be = make(fail_set_text=True)
    # break the fallback too
    def boom(text, delay=0.0, should_continue=None):
        raise RuntimeError("no input")
    be.type_unicode = boom
    assert ins.insert("hello") == InsertResult.FAILED


# --------------------------------------------------------------------------
# on_notice callback
# --------------------------------------------------------------------------
def test_on_notice_fires_for_no_target():
    notices = []
    be = FakeBackend(no_target=True)
    ins = TextInserter(restore_delay=0, modifier_timeout=0.05,
                       on_notice=notices.append, backend=be)
    assert ins.insert("hello") == InsertResult.NO_TARGET
    assert len(notices) == 1
    assert "text field" in notices[0].lower()


def test_on_notice_fires_for_blocked():
    notices = []
    be = FakeBackend(blocked=True)
    ins = TextInserter(restore_delay=0, modifier_timeout=0.05,
                       on_notice=notices.append, backend=be)
    assert ins.insert("hello") == InsertResult.BLOCKED
    assert "admin" in notices[0].lower()


def test_on_notice_silent_on_success():
    notices = []
    be = FakeBackend()
    ins = TextInserter(restore_delay=0, modifier_timeout=0.05,
                       on_notice=notices.append, backend=be)
    ins.insert("hello")
    assert notices == []


# --------------------------------------------------------------------------
# Long text in keystroke mode goes via the clipboard
#
# Synthesized keystrokes cannot deliver a long transcript intact: SendInput
# queues events far ahead of the app consuming them, so anything the user does
# mid-delivery corrupts the tail and cannot be retracted (measured in
# tools/injection_harness.py). Long text therefore takes the paste path, which
# hands the whole string over in one operation.
# --------------------------------------------------------------------------
LONG = "word " * 60          # 300 chars, well past _KEYSTROKE_SAFE_CHARS
SHORT = "just a few words"   # comfortably under it


def test_keystroke_mode_types_short_text_literally():
    ins, be = make(mode="keystroke")
    assert ins.insert(SHORT) == InsertResult.TYPED
    assert be.typed == [SHORT]
    assert be.pastes == 0


def test_keystroke_mode_sends_long_text_via_clipboard():
    ins, be = make(mode="keystroke")
    assert ins.insert(LONG) == InsertResult.PASTED
    assert be.pastes == 1
    assert be.typed == []
    assert be.set_text == LONG


def test_keystroke_long_text_falls_back_to_typing_when_paste_fails():
    # The reason people choose keystroke mode is an app that refuses Ctrl+V,
    # so the escalation must never strand them.
    ins, be = make(mode="keystroke", fail_set_text=True)
    assert ins.insert(LONG) == InsertResult.TYPED
    assert be.typed == [LONG]


def test_keystroke_long_text_can_be_forced_to_type():
    be = FakeBackend()
    ins = TextInserter(mode="keystroke", restore_delay=0, modifier_timeout=0.05,
                       backend=be, long_text_via_paste=False)
    assert ins.insert(LONG) == InsertResult.TYPED
    assert be.pastes == 0


def test_partial_typing_reports_no_target():
    # backend abandoned the message mid-way because focus left the target
    be = FakeBackend()
    be.type_complete = False
    ins = TextInserter(mode="keystroke", restore_delay=0, modifier_timeout=0.05,
                       backend=be)
    assert ins.insert(SHORT) == InsertResult.NO_TARGET


def test_typing_is_given_a_continue_predicate():
    ins, be = make(mode="keystroke")
    ins.insert(SHORT)
    assert callable(be.should_continue)


# --------------------------------------------------------------------------
# An undelivered dictation goes to History — the clipboard is never touched
#
# Parking the transcript on the clipboard overwrote whatever the user had
# copied, and with on_notice=None in the app it did so silently. The dashboard
# already has the text; the clipboard is not ours to take.
# --------------------------------------------------------------------------
def _clipboard_calls(be):
    return [c for c in be.calls if c in ("set_text", "backup", "restore", "paste")]


def test_no_target_leaves_the_clipboard_alone():
    ins, be = make(no_target=True)
    assert ins.insert("hello") == InsertResult.NO_TARGET
    assert _clipboard_calls(be) == []
    assert be.set_text is None


def test_blocked_leaves_the_clipboard_alone():
    ins, be = make(blocked=True)
    assert ins.insert("hello") == InsertResult.BLOCKED
    assert _clipboard_calls(be) == []


def test_a_failed_injection_leaves_the_clipboard_alone():
    be = FakeBackend()

    def boom(text, delay=0.0, should_continue=None):
        raise RuntimeError("SendInput refused")

    be.type_unicode = boom
    ins = TextInserter(mode="keystroke", restore_delay=0, modifier_timeout=0.05,
                       backend=be)
    assert ins.insert("hello") == InsertResult.FAILED
    assert _clipboard_calls(be) == []


def test_an_undelivered_keystroke_dictation_leaves_the_clipboard_alone():
    be = FakeBackend(no_target=True)
    ins = TextInserter(mode="keystroke", restore_delay=0, modifier_timeout=0.05,
                       backend=be)
    assert ins.insert(LONG) == InsertResult.NO_TARGET
    assert _clipboard_calls(be) == []


def test_the_notice_points_at_history_not_the_clipboard():
    notices = []
    be = FakeBackend(no_target=True)
    ins = TextInserter(restore_delay=0, modifier_timeout=0.05,
                       on_notice=notices.append, backend=be)
    ins.insert("hello")
    assert "history" in notices[0].lower()
    assert "clipboard" not in notices[0].lower()


def test_the_inserter_notice_comes_from_the_shared_table():
    from rekounts.text_inserter import undelivered_message

    notices = []
    be = FakeBackend(no_target=True)
    ins = TextInserter(restore_delay=0, modifier_timeout=0.05,
                       on_notice=notices.append, backend=be)
    ins.insert("hello")
    assert notices == [undelivered_message(InsertResult.NO_TARGET)]


def test_every_undelivered_outcome_has_its_own_wording():
    from rekounts.text_inserter import _UNDELIVERED, undelivered_message

    messages = {o: undelivered_message(o) for o in _UNDELIVERED}
    assert len(set(messages.values())) == len(_UNDELIVERED)
    # Only the genuinely-no-target case may claim there was no text field.
    for outcome, msg in messages.items():
        if outcome is not InsertResult.NO_TARGET:
            assert "no text field" not in msg.lower(), outcome


def test_insert_takes_no_required_keyword_arguments():
    # Callers wrap this object (the scratchpad router delegates with a bare
    # insert(text)); a required keyword here would break them.
    import inspect

    params = list(inspect.signature(TextInserter.insert).parameters.values())
    assert [p.name for p in params] == ["self", "text", "target"]
    assert all(p.kind is not p.KEYWORD_ONLY for p in params)


# --------------------------------------------------------------------------
# Held modifiers stop the delivery instead of corrupting it
# --------------------------------------------------------------------------
def test_modifier_timeout_between_chunks_stops_the_delivery():
    be = FakeBackend()
    be.chunks = 4
    be.modifiers_stuck = True
    ins = TextInserter(mode="keystroke", restore_delay=0, modifier_timeout=0.05,
                       backend=be)
    assert ins.insert(SHORT) == InsertResult.INTERRUPTED


def test_an_interrupted_delivery_says_so_without_touching_the_clipboard():
    notices = []
    be = FakeBackend()
    be.chunks = 4
    be.modifiers_stuck = True
    ins = TextInserter(mode="keystroke", restore_delay=0, modifier_timeout=0.05,
                       on_notice=notices.append, backend=be)
    ins.insert(SHORT)
    assert _clipboard_calls(be) == []
    assert notices and "clipboard" not in notices[0].lower()


def test_released_modifiers_let_the_delivery_finish():
    # The wait is only fatal when it runs out; a normal press/release resumes.
    be = FakeBackend(modifier_sequence=[True, True, False])
    be.chunks = 4
    ins = TextInserter(mode="keystroke", restore_delay=0, modifier_timeout=1.0,
                       backend=be)
    assert ins.insert(SHORT) == InsertResult.TYPED
    assert be.gate_calls == 3


def test_a_focus_change_between_chunks_still_reports_no_target():
    # capture, then _guard's re-read, then the between-chunk re-read finds 999
    be = FakeBackend(foreground_sequence=[100, 100, 999])
    be.chunks = 4
    ins = TextInserter(mode="keystroke", restore_delay=0, modifier_timeout=0.05,
                       backend=be)
    assert ins.insert(SHORT) == InsertResult.NO_TARGET


def test_guard_still_proceeds_when_modifiers_never_lift():
    # Hold-to-talk means modifiers ARE down when a dictation ends. The initial
    # wait must not refuse to deliver, or the feature stops working.
    be = FakeBackend()
    be.modifiers_stuck = True
    ins = TextInserter(mode="keystroke", restore_delay=0, modifier_timeout=0.05,
                       backend=be)
    assert ins.insert(SHORT) == InsertResult.TYPED


# --------------------------------------------------------------------------
# One delivery cannot stall for timeout x chunk-count
#
# macOS posts 20 UTF-16 units at a time, so a long transcript is dozens of
# chunks; a per-chunk timeout would let a rested finger freeze the app for
# minutes mid-sentence.
# --------------------------------------------------------------------------
def test_modifier_waits_share_one_pool_across_a_delivery():
    be = FakeBackend()
    be.modifiers_stuck = True
    ins = TextInserter(mode="keystroke", restore_delay=0, modifier_timeout=0.1,
                       backend=be)
    budget = _WaitBudget(0.1)
    started = time.monotonic()
    for _ in range(30):
        ins._wait_for_modifiers(budget)
    # 30 waits against ONE 0.1s pool, not 30 x 0.1s.
    assert time.monotonic() - started < 1.0


def test_a_many_chunk_delivery_with_stuck_modifiers_returns_promptly():
    be = FakeBackend()
    be.chunks = 60
    be.modifiers_stuck = True
    ins = TextInserter(mode="keystroke", restore_delay=0, modifier_timeout=0.1,
                       backend=be, long_text_via_paste=False)
    started = time.monotonic()
    assert ins.insert("z" * 1200) == InsertResult.INTERRUPTED
    # _guard's own wait (0.1s) plus the shared between-chunk pool (0.1s),
    # nowhere near 60 x 0.1s.
    assert time.monotonic() - started < 1.5


def test_wait_budget_never_goes_negative():
    b = _WaitBudget(0.05)
    b.spend(10.0)
    assert b.remaining == 0.0


# --------------------------------------------------------------------------
# capture_target passthrough
# --------------------------------------------------------------------------
def test_capture_target_returns_foreground():
    ins, be = make(hwnd=1234)
    assert ins.capture_target() == 1234


# --------------------------------------------------------------------------
# NullBackend degrades safely (no exceptions from the guards)
# --------------------------------------------------------------------------
def test_null_backend_guards_are_noops():
    be = _NullBackend()
    assert be.foreground_window() is None
    assert be.is_no_target(None) is False
    assert be.is_blocked(None) is False
    assert be.modifiers_down() is False
    assert be.clipboard_sequence() is None


# --------------------------------------------------------------------------
# Real Win32 backend smoke tests (Windows only) — construct + honest outcome
# --------------------------------------------------------------------------
@pytest.mark.skipif(sys.platform != "win32", reason="Win32 backend only on Windows")
def test_real_backend_constructs():
    from rekounts.text_inserter import _Win32Backend
    be = _Win32Backend()
    assert be.available is True
    # these must never raise, whatever the desktop state
    be.modifiers_down()
    be.clipboard_sequence()
    hwnd = be.foreground_window()
    be.is_no_target(hwnd)
    be.is_blocked(hwnd)
