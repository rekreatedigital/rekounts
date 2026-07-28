"""The Hub's per-platform wording.

Every one of these strings was hardcoded to Windows and shown verbatim to a Mac
user. The point of the module under test is that the mac wording is assertable
from a Windows box (and vice versa), because nobody can run the Hub on both.

The tests are therefore written the way the bug would have been caught: pin the
Windows strings BYTE-FOR-BYTE (so no edit can change what a Windows user reads
by accident), then assert the mac variants say something different and factually
right.

The module also decides whether the **Processing** row is drawn at all, which
is a per-BUILD fact rather than a per-platform one — the packaged app has no
GPU stack in it. Same testing problem, same answer: an injected ``frozen`` flag,
so both branches are assertable from one machine.
"""
import pytest

from rekounts.ui import platform_text as pt

WIN = "win32"
MAC = "darwin"

# The Windows wording, pinned byte-for-byte. If a future edit rewords a hint,
# this test SHOULD fail — that is a copy change, and it has to be made on
# purpose in both tables.
#
# Three of these were reworded on purpose in the "say only what is true for the
# person reading it" pass, and their old text is kept below in RETIRED so the
# rewrite cannot silently drift back.
PINNED_WINDOWS = {
    "mic": "System default follows whatever Windows is using.",
    "preroll": (
        "The microphone stays open the whole time, so Windows shows the "
        "mic-in-use indicator continuously — the audio stays in memory and is "
        "never written to disk."),
    "launch": "Start Rekounts automatically when you sign in to Windows.",
    "scratchpad": (
        "A floating sticky note you can dictate into — open it from the tray "
        "menu. Dictation lands in the note while it is the focused window, and "
        "goes to whatever app you are in otherwise."),
}

# What each reworded hint used to say, and the reason it stopped saying it.
RETIRED = {
    # The engineering name for the technique; the row title now says what the
    # user gets ("Catch the first word").
    "preroll": "Catches the first syllable.",
}

HINTS = {
    "mic": pt.mic_default_hint,
    "preroll": pt.preroll_hint,
    "launch": pt.launch_at_login_hint,
    "scratchpad": pt.scratchpad_hint,
}


def test_there_is_no_hint_for_a_row_that_no_longer_exists():
    """The "Paste long dictations" row is gone, so its wording is too.

    The row only meant anything in keystroke mode, which is not reachable from
    the UI any more. A hint left behind here would be wording nobody can read,
    quietly re-pinned by the tests above as if a user still saw it.
    """
    assert not hasattr(pt, "long_text_hint")


@pytest.mark.parametrize("key", sorted(PINNED_WINDOWS))
def test_windows_wording_is_pinned(key):
    assert HINTS[key](WIN) == PINNED_WINDOWS[key]


@pytest.mark.parametrize("key", sorted(RETIRED))
def test_retired_wording_does_not_come_back(key):
    for platform in (WIN, MAC):
        assert RETIRED[key] not in HINTS[key](platform)


@pytest.mark.parametrize("key", sorted(PINNED_WINDOWS))
def test_every_hint_has_its_own_mac_wording(key):
    """No hint may fall through to the Windows sentence on a Mac."""
    assert HINTS[key](MAC) != PINNED_WINDOWS[key]


@pytest.mark.parametrize("key", sorted(PINNED_WINDOWS))
def test_no_mac_hint_says_windows(key):
    text = HINTS[key](MAC)
    assert "Windows" not in text
    # "Ctrl+V" is the Windows paste. No hint names a paste shortcut any more —
    # the row that did is gone — so this is now a floor, not a carve-out.
    assert "Ctrl+V" not in text


def test_the_mac_hints_say_the_true_thing():
    assert "macOS" in pt.mic_default_hint(MAC)
    # The mic indicator on macOS 12+ is an orange dot in the menu bar, not
    # Windows' "mic in use" tray icon.
    assert "menu bar" in pt.preroll_hint(MAC)
    assert "Mac" in pt.launch_at_login_hint(MAC)
    assert "menu-bar icon" in pt.scratchpad_hint(MAC)


# --- the Processing row: shown only where it can do something --------------
def test_a_downloaded_build_is_never_offered_the_gpu():
    """Rekounts.spec excludes the whole CUDA stack and transcriber.py refuses to
    probe under sys.frozen, so for everyone who DOWNLOADED the app "Auto" is
    CPU. The row must not be drawn at all there — on either platform."""
    assert pt.gpu_choice_applies(frozen=True, platform=WIN) is False
    assert pt.gpu_choice_applies(frozen=True, platform=MAC) is False


def test_a_mac_is_never_offered_the_gpu_even_from_source():
    """CTranslate2's only accelerator backend is CUDA, and there is no macOS
    build of it — so the choice is dead on a Mac however Rekounts was started."""
    assert pt.gpu_choice_applies(frozen=False, platform=MAC) is False


def test_a_source_run_on_windows_keeps_the_choice():
    """The one audience the setting was ever able to serve."""
    assert pt.gpu_choice_applies(frozen=False, platform=WIN) is True
    assert pt.gpu_choice_applies(frozen=False, platform="linux") is True


def test_frozen_defaults_to_this_process():
    import sys
    assert pt.gpu_choice_applies(platform=WIN) is not getattr(sys, "frozen", False)


def test_the_processing_hint_is_written_for_the_only_reader_who_sees_it():
    """A from-source run — so naming the CUDA libraries is actionable, not
    jargon. What must never come back is telling a packaged user to install
    them, and the row simply is not there to say it."""
    hint = pt.processing_hint()
    assert "CUDA" in hint and "README" in hint
    assert "NVIDIA" in hint


def test_the_privacy_promise_survives_the_preroll_rewording():
    """Both pre-roll hints must still say the audio never hits disk — it is the
    one load-bearing sentence in that row, not decoration."""
    for platform in (WIN, MAC):
        assert "never written to disk" in pt.preroll_hint(platform)


# --- the hotkey ------------------------------------------------------------
def test_the_pill_caption_keeps_its_windows_shape():
    # Byte-identical to the (cfg.get("hotkey") or "").upper() it replaced.
    assert pt.hotkey_label("ctrl+win", WIN) == "CTRL+WIN"
    assert pt.hotkey_label("ctrl+alt+f9", WIN) == "CTRL+ALT+F9"
    assert pt.hotkey_label("", WIN) == ""
    assert pt.hotkey_label(None, WIN) == ""


def test_the_pill_names_the_key_a_mac_keyboard_actually_has():
    assert pt.hotkey_label("ctrl+win", MAC) == "CTRL+CMD"
    assert pt.hotkey_label("alt+9", MAC) == "OPTION+9"
    # Non-modifier tokens are untouched on both platforms.
    assert pt.hotkey_label("f8", MAC) == "F8"


def test_pretty_hotkey_per_platform():
    assert pt.pretty_hotkey("ctrl+win", WIN) == "Ctrl + Win"
    assert pt.pretty_hotkey("ctrl+win", MAC) == "Ctrl + Cmd"
    assert pt.pretty_hotkey("page_up", WIN) == "Page Up"
    assert pt.pretty_hotkey("page_up", MAC) == "Page Up"
    assert pt.pretty_hotkey("", MAC) == ""


def test_paste_shortcut_matches_what_each_backend_synthesizes():
    """Not cosmetic: _Win32Backend sends Ctrl+V and _MacBackend sends Cmd+V
    (rekounts/text_inserter.py). The hint that tells a user to switch the
    escalation off has to name the keystroke their app is actually ignoring."""
    assert pt.paste_shortcut(WIN) == "Ctrl+V"
    assert pt.paste_shortcut(MAC) == "Cmd+V"


def test_platform_defaults_to_this_machine():
    import sys
    assert pt.is_mac() is (sys.platform == "darwin")
    assert pt.os_name() == ("macOS" if sys.platform == "darwin" else "Windows")


def test_an_unknown_platform_gets_the_windows_table_not_a_crash():
    """Linux is unsupported, but the Hub must still render rather than raise."""
    assert pt.os_name("linux") == "Windows"
    assert pt.hotkey_label("ctrl+win", "linux") == "CTRL+WIN"
