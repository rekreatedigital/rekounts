"""The Hub's per-platform wording.

Every one of these strings was hardcoded to Windows and shown verbatim to a Mac
user. The point of the module under test is that the mac wording is assertable
from a Windows box (and vice versa), because nobody can run the Hub on both.

The tests are therefore written the way the bug would have been caught: pin the
Windows strings BYTE-FOR-BYTE against what shipped in v0.4.0 (so this refactor
cannot have changed what a Windows user reads), then assert the mac variants say
something different and factually right.
"""
import pytest

from rekounts.ui import platform_text as pt

WIN = "win32"
MAC = "darwin"

# Verbatim from rekounts/ui/settings_page.py as of v0.4.0. If a future edit
# rewords a Windows hint, this test SHOULD fail — that is a copy change, and it
# has to be made on purpose in both tables.
V040_WINDOWS = {
    "mic": "System default follows whatever Windows is using.",
    "long_text": (
        "Keystroke mode only. Typed keystrokes can't deliver a long transcript "
        "intact, so anything over ~100 characters goes via the clipboard and "
        "the clipboard is put straight back. Turn off if your app ignores "
        "Ctrl+V."),
    "preroll": (
        "Catches the first syllable. Holds the microphone stream open, so "
        "Windows shows the mic-in-use indicator continuously — the audio stays "
        "in memory and is never written to disk."),
    "launch": "Start Rekounts automatically when you sign in to Windows.",
    "processing": (
        "Auto tries your NVIDIA GPU (needs the CUDA libraries — see the "
        "README) and quietly falls back to CPU if it can't run there. Big "
        "models are only fast on a GPU."),
    "scratchpad": (
        "A floating sticky note you can dictate into — open it from the tray "
        "menu. Dictation lands in the note while it is the focused window, and "
        "goes to whatever app you are in otherwise."),
}

HINTS = {
    "mic": pt.mic_default_hint,
    "long_text": pt.long_text_hint,
    "preroll": pt.preroll_hint,
    "launch": pt.launch_at_login_hint,
    "processing": pt.processing_hint,
    "scratchpad": pt.scratchpad_hint,
}


@pytest.mark.parametrize("key", sorted(V040_WINDOWS))
def test_windows_wording_is_unchanged_from_v040(key):
    assert HINTS[key](WIN) == V040_WINDOWS[key]


@pytest.mark.parametrize("key", sorted(V040_WINDOWS))
def test_every_hint_has_its_own_mac_wording(key):
    """No hint may fall through to the Windows sentence on a Mac."""
    assert HINTS[key](MAC) != V040_WINDOWS[key]


@pytest.mark.parametrize("key", sorted(V040_WINDOWS))
def test_no_mac_hint_says_windows(key):
    text = HINTS[key](MAC)
    assert "Windows" not in text
    # "Ctrl+V" is the Windows paste, and only appears in the long-text hint.
    assert "Ctrl+V" not in text


def test_the_mac_hints_say_the_true_thing():
    assert "Cmd+V" in pt.long_text_hint(MAC)
    assert "macOS" in pt.mic_default_hint(MAC)
    # The mic indicator on macOS 12+ is an orange dot in the menu bar, not
    # Windows' "mic in use" tray icon.
    assert "menu bar" in pt.preroll_hint(MAC)
    assert "Mac" in pt.launch_at_login_hint(MAC)
    # CTranslate2 has no Apple-silicon accelerator, so "Auto" is CPU on a Mac.
    assert "NVIDIA-only" in pt.processing_hint(MAC)
    assert "menu-bar icon" in pt.scratchpad_hint(MAC)


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
