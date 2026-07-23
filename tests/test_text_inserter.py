"""Unit tests for TextInserter policy, using a fully mocked platform backend.

The Win32 layer is never exercised here; instead a FakeBackend records calls and
lets each test drive the conditions (modifiers held, elevated target, focus
change, clipboard sequence, exceptions) so the policy is tested in isolation.
Two small tests do touch the real Win32 backend on Windows to sanity-check it
constructs and reports a plausible outcome.
"""

import sys

import pytest

from rekounts.text_inserter import (
    InsertResult,
    TextInserter,
    _NullBackend,
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

    def type_unicode(self, text, delay=0.0):
        self.calls.append("type")
        self.typed.append(text)


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


# --------------------------------------------------------------------------
# Guards: no target / elevation / focus change
# --------------------------------------------------------------------------
def test_no_target_returns_no_target_without_pasting():
    ins, be = make(no_target=True)
    assert ins.insert("hello") == InsertResult.NO_TARGET
    assert be.pastes == 0
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
    def boom(text, delay=0.0):
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
