"""Tests for the REAL Windows input-synthesis path.

Until now ``test_text_inserter.py`` covered only policy, through a fake
backend — the actual ctypes/SendInput code that corrupted people's dictations
had no coverage at all. These tests drive the genuine :class:`_Win32Backend`
(real structs, real event construction) and intercept only the final
``_send`` call, so everything up to the syscall is exercised without moving
the user's keyboard.

What they pin down, and why each one matters:

  * one SendInput array per chunk, not one per character — the shipped bug was
    ~2700 separate injections spread over seconds,
  * a UTF-16 surrogate pair is never torn across two arrays — the shipped code
    sent the two halves as two independent calls, so a mid-burst interruption
    could deliver a lone surrogate,
  * chunk boundaries never split a character,
  * the between-chunk predicate is honoured, so a focus change stops delivery
    instead of spraying the tail into another app,
  * newlines are real Return keypresses and ``\\r`` is dropped.

See ``tools/injection_harness.py`` for the end-to-end reproduction these
guarantees were derived from.
"""

import sys

import pytest

from rekounts.text_inserter import (
    InsertResult,
    TextInserter,
    VK_RETURN,
    _KEYSTROKE_SAFE_CHARS,
    _WIN_ATOMIC_CHUNK_CHARS,
)

pytestmark = pytest.mark.skipif(
    sys.platform != "win32", reason="exercises the Win32 ctypes input path")


@pytest.fixture
def backend():
    """A real _Win32Backend whose SendInput is intercepted, not suppressed.

    Every struct, flag and code path below the interception point is the real
    one; only the syscall itself is replaced, so these tests cannot type into
    the developer's desktop.
    """
    from rekounts.text_inserter import _Win32Backend

    be = _Win32Backend()
    be.sent = []
    be._send = lambda events: be.sent.append(list(events))
    return be


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------
KEYEVENTF_KEYUP = 0x0002
KEYEVENTF_UNICODE = 0x0004


def scans(array):
    """The wScan values of the UNICODE key-DOWN events in one SendInput array."""
    return [e.ki.wScan for e in array
            if e.ki.dwFlags == KEYEVENTF_UNICODE]


def text_of(sent):
    """Reassemble the UTF-16 the backend actually put on the wire."""
    units = []
    for array in sent:
        units.extend(scans(array))
    return "".join(chr(u) for u in units).encode(
        "utf-16-le", "surrogatepass").decode("utf-16-le")


# ---------------------------------------------------------------------------
# Atomicity
# ---------------------------------------------------------------------------
def test_short_text_is_one_single_sendinput_call(backend):
    backend.type_unicode("hello")
    assert len(backend.sent) == 1


def test_one_call_carries_down_and_up_for_every_character(backend):
    backend.type_unicode("abc")
    assert len(backend.sent[0]) == 6      # 3 chars x (down + up)


def test_long_text_uses_far_fewer_calls_than_characters(backend):
    # The regression under test: the shipped code made one call per character.
    text = "x" * 600
    backend.type_unicode(text)
    assert len(backend.sent) < len(text) / 10
    assert len(backend.sent) == -(-600 // _WIN_ATOMIC_CHUNK_CHARS)


def test_round_trips_the_exact_text(backend):
    text = "Hello, world — naïve café? 123."
    backend.type_unicode(text)
    assert text_of(backend.sent) == text


def test_long_text_round_trips_exactly(backend):
    text = "".join("sentence %d. " % i for i in range(200))
    backend.type_unicode(text)
    assert text_of(backend.sent) == text


# ---------------------------------------------------------------------------
# Surrogate pairs (the latent astral-character bug)
# ---------------------------------------------------------------------------
def test_astral_char_is_one_indivisible_group(backend):
    backend.type_unicode("\U0001F600")     # emoji, outside the BMP
    assert len(backend.sent) == 1
    units = scans(backend.sent[0])
    assert len(units) == 2
    assert 0xD800 <= units[0] <= 0xDBFF    # high surrogate
    assert 0xDC00 <= units[1] <= 0xDFFF    # low surrogate


def test_astral_char_round_trips(backend):
    backend.type_unicode("ok \U0001F600 done")
    assert text_of(backend.sent) == "ok \U0001F600 done"


def test_surrogate_pair_never_straddles_a_chunk_boundary(backend):
    # Put an astral char exactly where a naive length-based split would cut.
    text = "a" * (_WIN_ATOMIC_CHUNK_CHARS - 1) + "\U0001F600" + "b" * 10
    backend.type_unicode(text)
    for array in backend.sent:
        units = scans(array)
        highs = [u for u in units if 0xD800 <= u <= 0xDBFF]
        lows = [u for u in units if 0xDC00 <= u <= 0xDFFF]
        assert len(highs) == len(lows)     # never a half pair in one call
    assert text_of(backend.sent) == text


# ---------------------------------------------------------------------------
# Newlines
# ---------------------------------------------------------------------------
def test_newline_is_a_real_return_keypress(backend):
    backend.type_unicode("\n")
    events = backend.sent[0]
    assert [e.ki.wVk for e in events] == [VK_RETURN, VK_RETURN]
    assert events[1].ki.dwFlags & KEYEVENTF_KEYUP


def test_carriage_return_is_dropped(backend):
    backend.type_unicode("a\r\nb")
    assert text_of(backend.sent) == "ab"   # \r contributes no unicode event


# ---------------------------------------------------------------------------
# The between-chunk gate
# ---------------------------------------------------------------------------
def test_predicate_not_consulted_when_text_fits_one_call(backend):
    calls = []
    backend.type_unicode("short", should_continue=lambda: calls.append(1) or True)
    assert calls == []


def test_delivery_stops_when_the_predicate_goes_false(backend):
    text = "y" * (_WIN_ATOMIC_CHUNK_CHARS * 5)
    complete = backend.type_unicode(text, should_continue=lambda: False)
    assert complete is False
    # exactly the first chunk went out; the rest was withheld
    assert len(backend.sent) == 1
    assert len(text_of(backend.sent)) == _WIN_ATOMIC_CHUNK_CHARS


def test_full_delivery_reports_true(backend):
    assert backend.type_unicode("z" * 400, should_continue=lambda: True) is True


def test_paced_mode_stops_on_the_predicate_too(backend):
    complete = backend.type_unicode("abcdef", delay=0.0001,
                                    should_continue=lambda: False)
    assert complete is False
    assert len(backend.sent) == 1          # one character, then it stopped


# ---------------------------------------------------------------------------
# End-to-end through the policy layer, still without real injection
# ---------------------------------------------------------------------------
class _StubClipboard:
    """Just enough of the clipboard surface for the policy layer."""

    def __init__(self):
        self.text = None

    def install(self, backend):
        backend.set_clipboard_text = self._set
        backend.backup_clipboard = lambda: {}
        backend.restore_clipboard = lambda snap: None
        backend.clipboard_sequence = lambda: 1
        backend.send_paste = lambda: None
        backend.foreground_window = lambda: 4242
        backend.is_no_target = lambda hwnd: False
        backend.is_blocked = lambda hwnd: False
        backend.modifiers_down = lambda: False
        return backend

    def _set(self, text):
        self.text = text


def test_policy_types_short_text_through_the_real_backend(backend):
    # Reaching the typing path takes BOTH config keys now — keystroke mode
    # alone pastes, because _KEYSTROKE_SAFE_CHARS is 0.
    clip = _StubClipboard().install(backend)
    ins = TextInserter(mode="keystroke", restore_delay=0, backend=clip,
                       long_text_via_paste=False)
    assert ins.insert("a short one") == InsertResult.TYPED
    assert text_of(backend.sent) == "a short one"


def test_policy_diverts_text_away_from_keystrokes(backend):
    # Was "long text": the diversion used to start above 100 characters. It
    # starts at one character now — typing corrupts text in modern Windows
    # apps at any length, so nothing is short enough to be worth typing.
    stub = _StubClipboard()
    ins = TextInserter(mode="keystroke", restore_delay=0,
                       backend=stub.install(backend))
    text = "w" * (_KEYSTROKE_SAFE_CHARS + 1)
    assert ins.insert(text) == InsertResult.PASTED
    assert backend.sent == []              # nothing was typed at all
    assert stub.text == text
