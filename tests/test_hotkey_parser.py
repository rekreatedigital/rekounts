import pytest
from pynput import keyboard

from rekounts.hotkey_manager import parse_hotkey, is_valid_hotkey


def test_single_function_key():
    assert parse_hotkey("f8") == keyboard.HotKey.parse("<f8>")


def test_single_char_key():
    assert parse_hotkey("a") == keyboard.HotKey.parse("a")


def test_modifier_combo():
    assert parse_hotkey("ctrl+alt+space") == keyboard.HotKey.parse("<ctrl>+<alt>+<space>")


def test_win_maps_to_cmd():
    # pynput calls the Windows key Key.cmd; "win" must not become "<win>".
    assert parse_hotkey("ctrl+win") == keyboard.HotKey.parse("<ctrl>+<cmd>")


@pytest.mark.parametrize("alias", ["win", "windows", "super", "meta", "cmd", "command"])
def test_windows_key_aliases(alias):
    assert parse_hotkey(alias) == keyboard.HotKey.parse("<cmd>")


@pytest.mark.parametrize("alias,canonical", [
    ("escape", "<esc>"), ("return", "<enter>"), ("del", "<delete>"),
    ("pgup", "<page_up>"), ("control", "<ctrl>"), ("option", "<alt>"),
])
def test_named_aliases(alias, canonical):
    assert parse_hotkey(alias) == keyboard.HotKey.parse(canonical)


def test_case_and_whitespace_insensitive():
    assert parse_hotkey("  CtRl + WIN ") == parse_hotkey("ctrl+win")


@pytest.mark.parametrize("bad", ["f88", "", "  ", "ctrl+", "notakey", "ctrl+f99"])
def test_invalid_hotkeys_raise(bad):
    with pytest.raises(ValueError):
        parse_hotkey(bad)


def test_is_valid_hotkey():
    assert is_valid_hotkey("ctrl+win")
    assert is_valid_hotkey("f8")
    assert not is_valid_hotkey("f88")
    assert not is_valid_hotkey("")
