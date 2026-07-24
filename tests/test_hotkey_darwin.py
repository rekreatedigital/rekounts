"""The macOS side of the hotkey manager's platform seams.

Everything here injects the platform explicitly (the same functions serve
Windows via sys.platform defaults), so both numbering spaces are exercised on
every CI OS.
"""
from pynput import keyboard

import rekounts.hotkey_manager as hm


# --- per-platform key identity tokens -----------------------------------------

def test_char_vk_is_windows_ord_on_win32():
    assert hm._char_vk("a", "win32") == ord("A")
    assert hm._char_vk("7", "win32") == ord("7")


def test_char_vk_is_ansi_keycode_on_darwin():
    assert hm._char_vk("a", "darwin") == 0
    assert hm._char_vk("v", "darwin") == 9
    # The digit row is NOT sequential in the mac keycode space.
    assert hm._char_vk("5", "darwin") == 23
    assert hm._char_vk("6", "darwin") == 22
    assert hm._char_vk("7", "darwin") == 26


def test_char_vk_unknown_platform_emits_nothing():
    assert hm._char_vk("a", "linux") is None


def test_key_tokens_letter_gets_the_platform_keycode():
    key = keyboard.KeyCode.from_char("a")
    win = hm._key_tokens(key, platform="win32")
    mac = hm._key_tokens(key, platform="darwin")
    assert ("vk", ord("A")) in win
    assert ("vk", 0) in mac
    # A Windows-style ord() token must never leak into the mac token set —
    # ord('A') == 65 collides with unrelated keycodes there.
    assert ("vk", ord("A")) not in mac


def test_c0_unfold_still_works_per_platform():
    """ctrl+a arriving as '\\x01' matches the configured 'a' on both platforms."""
    ctrl_a = keyboard.KeyCode.from_char("\x01")
    for platform, vk in (("win32", ord("A")), ("darwin", 0)):
        tokens = hm._key_tokens(ctrl_a, platform=platform)
        assert ("char", "a") in tokens
        assert ("vk", vk) in tokens


# --- watchdog polling groups ---------------------------------------------------

def test_darwin_modifier_families_expand_left_and_right():
    # Tokens as darwin pynput would emit them (Key.cmd carries keycode 55
    # there; the host's pynput carries the HOST's code, so build it directly).
    req = frozenset({("key", "cmd"), ("vk", 55)})
    vks = hm._pollable_vks(req, platform="darwin")
    assert {54, 55} <= vks          # both Command keys poll as "cmd down"


def test_windows_modifier_families_unchanged():
    req = frozenset({("key", "ctrl"), ("vk", 0x11)})   # as win32 pynput emits
    vks = hm._pollable_vks(req, platform="win32")
    assert {0x11, 0xA2, 0xA3} <= vks


# --- key-state poll selection + watchdog gating ---------------------------------

def test_key_state_poll_windows_is_trusted():
    poll, trusted = hm._key_state_poll("win32")
    assert poll is hm._win_key_down
    assert trusted is True


def test_key_state_poll_other_platforms_untrusted():
    poll, trusted = hm._key_state_poll("linux")
    assert trusted is False
    assert poll(65) is False


class _DummyListener:
    def __init__(self):
        self.running = True

    def start(self):
        pass

    def stop(self):
        self.running = False

    def is_alive(self):
        return self.running

    def canonical(self, key):
        return key


def _manager(**kw):
    mgr = hm.HotkeyManager("ctrl+win", on_start=lambda: None,
                           on_stop=lambda: None,
                           dispatcher=hm._InlineDispatcher(), **kw)
    mgr._new_listener = _DummyListener
    return mgr


def test_untrusted_key_state_disables_the_watchdog(monkeypatch):
    """A poll that could read HELD keys as 'up' would force-release every
    push-to-talk hold (the heal path fires on_up). No watchdog beats a lying
    one, so an untrusted platform poll must yield no watchdog at all."""
    monkeypatch.setattr(hm, "_key_state_poll", lambda p=None: (lambda vk: False, False))
    mgr = _manager(watchdog=True)
    mgr.start()
    try:
        assert mgr._watchdog is None
    finally:
        mgr.stop()


def test_injected_key_state_keeps_the_watchdog():
    mgr = _manager(watchdog=True, key_state=lambda vk: False)
    mgr.start()
    try:
        assert mgr._watchdog is not None
    finally:
        mgr.stop()
