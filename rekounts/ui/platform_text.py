"""Per-platform wording for the text the user reads in the Hub.

Rekounts was written Windows-first, and several of the sentences that *explain*
the app named Windows out loud. On a Mac they were not merely parochial, they
were false: the Hub told a Mac user that "System default follows whatever
Windows is using", that a long dictation goes via the clipboard so turn it off
"if your app ignores Ctrl+V" (the mac backend sends **Cmd+V** —
:class:`rekounts.text_inserter._MacBackend.send_paste`), that the pre-roll
buffer makes "Windows show the mic-in-use indicator", and that launch-at-login
starts the app "when you sign in to Windows". The pill said ``HOLD CTRL+WIN``
for a chord the Mac keyboard calls Ctrl+Cmd.

Wrong wording in the one place the app explains itself is worse than terse
wording, so every such sentence now comes from here.

Two conventions, both deliberate:

* **Every function takes an explicit ``platform``**, defaulting to
  ``sys.platform``, so the whole table is testable on any OS — the pattern
  :mod:`rekounts.permissions` and :mod:`rekounts.startup` already use. A test
  on Windows can assert the mac wording, which is the only way this module can
  be checked at all from a Windows box.
* **Whole sentences live here, not just nouns.** Interpolating an OS name into
  one shared sentence produces stilted copy ("macOS shows the mic-in-use
  indicator continuously" is not what macOS does — it shows an orange dot in
  the menu bar). Copy that differs per platform belongs in one table per
  platform.

Scope: sentences that make a factual claim about the operating system. Control
*titles* ("Tray notifications") are left alone — they name a Rekounts feature,
not an OS behavior, and churning them buys nothing.

Nothing here imports Qt or anything else from the app: it is strings only, and
it is the single place to add a third platform's wording.
"""
from __future__ import annotations

import sys

_DARWIN = "darwin"


def _platform(platform=None) -> str:
    return platform if platform is not None else sys.platform


def is_mac(platform=None) -> bool:
    return _platform(platform) == _DARWIN


def os_name(platform=None) -> str:
    """What to call the operating system in a sentence."""
    return "macOS" if is_mac(platform) else "Windows"


# --- the hotkey ------------------------------------------------------------
# pynput calls the Windows key and the Command key the same thing (``Key.cmd``),
# so the config token is "win" on every platform — see the module note in
# rekounts/hotkey_manager.py. Only the DISPLAY name differs, and it has to,
# because "Ctrl + Win" is not a chord that exists on a Mac keyboard.
_MODIFIER_NAMES = {"ctrl": "Ctrl", "alt": "Alt", "shift": "Shift", "win": "Win"}
_MODIFIER_NAMES_MAC = {"ctrl": "Ctrl", "alt": "Option", "shift": "Shift",
                       "win": "Cmd"}


def modifier_names(platform=None) -> dict[str, str]:
    """token -> display name for the four modifiers, for this platform."""
    return dict(_MODIFIER_NAMES_MAC if is_mac(platform) else _MODIFIER_NAMES)


def pretty_hotkey(value: str, platform=None) -> str:
    """'ctrl+win' -> 'Ctrl + Win' (Windows) / 'Ctrl + Cmd' (macOS).

    Display only — config keeps the canonical, cross-platform token form.
    """
    names = modifier_names(platform)
    return " + ".join(names.get(t, t.replace("_", " ").title())
                      for t in (value or "").split("+") if t)


def hotkey_label(value: str, platform=None) -> str:
    """The upper-case form the dictation pill shows ('CTRL+WIN' / 'CTRL+CMD').

    Same shape as the plain ``value.upper()`` it replaces — token order and the
    ``+`` separator are untouched — so the pill looks exactly as it always did
    on Windows and merely stops lying on a Mac.
    """
    names = modifier_names(platform)
    return "+".join(names.get(t, t).upper()
                    for t in (value or "").split("+") if t)


def paste_shortcut(platform=None) -> str:
    """The keystroke the clipboard-paste path actually synthesizes."""
    return "Cmd+V" if is_mac(platform) else "Ctrl+V"


def tray_menu_name(platform=None) -> str:
    """What the user's OS calls the thing our QSystemTrayIcon lives in."""
    return "menu-bar icon" if is_mac(platform) else "tray menu"


# --- the settings hints ----------------------------------------------------
def mic_default_hint(platform=None) -> str:
    return f"System default follows whatever {os_name(platform)} is using."


def long_text_hint(platform=None) -> str:
    return ("Keystroke mode only. Typed keystrokes can't deliver a long "
            "transcript intact, so anything over ~100 characters goes via the "
            "clipboard and the clipboard is put straight back. Turn off if "
            f"your app ignores {paste_shortcut(platform)}.")


def preroll_hint(platform=None) -> str:
    # macOS's indicator is not a copy of Windows': it is the orange dot in the
    # menu bar (macOS 12+), and it stays lit for as long as the stream is open.
    if is_mac(platform):
        return ("Catches the first syllable. Holds the microphone stream open, "
                "so the orange microphone dot stays in your menu bar the whole "
                "time — the audio stays in memory and is never written to disk.")
    return ("Catches the first syllable. Holds the microphone stream open, so "
            "Windows shows the mic-in-use indicator continuously — the audio "
            "stays in memory and is never written to disk.")


def launch_at_login_hint(platform=None) -> str:
    if is_mac(platform):
        return "Start Rekounts automatically when you log in to this Mac."
    return "Start Rekounts automatically when you sign in to Windows."


def processing_hint(platform=None) -> str:
    """Why the Processing dropdown has nothing to offer a Mac.

    Not a hardware finding — it follows from what the speech engine supports.
    faster-whisper runs on CTranslate2, whose only accelerator backend is CUDA
    (``ctranslate2.get_cuda_device_count()``, see rekounts/transcriber.py), so
    on a Mac "Auto" resolves to CPU every time. Saying so beats offering a
    setting that silently does nothing.
    """
    if is_mac(platform):
        return ("Auto and CPU do the same thing on a Mac: the speech engine's "
                "GPU support is NVIDIA-only, so there is nothing else for it "
                "to try. Base and Small are the realistic choices.")
    return ("Auto tries your NVIDIA GPU (needs the CUDA libraries — see the "
            "README) and quietly falls back to CPU if it can't run there. Big "
            "models are only fast on a GPU.")


def scratchpad_hint(platform=None) -> str:
    return ("A floating sticky note you can dictate into — open it from the "
            f"{tray_menu_name(platform)}. Dictation lands in the note while it "
            "is the focused window, and goes to whatever app you are in "
            "otherwise.")
