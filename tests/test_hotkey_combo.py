"""Combo-tracker edge detection, incl. the 'release any key ends PTT' bug fix."""
from pynput import keyboard

from rekounts.hotkey_manager import _Combo

CTRL = keyboard.Key.ctrl
CMD = keyboard.Key.cmd
SHIFT = keyboard.Key.shift
A = keyboard.KeyCode.from_char("a")


def make(keys):
    events = []
    # _Combo passes the event timestamp (or None) to its edge callbacks; these
    # tests don't care about it, so they accept and ignore it.
    combo = _Combo(keys, lambda now=None: events.append("down"),
                   lambda now=None: events.append("up"))
    return combo, events


def test_fires_down_when_all_keys_pressed():
    combo, events = make([CTRL, CMD])
    combo.press(CTRL)
    assert events == []          # not complete yet
    combo.press(CMD)
    assert events == ["down"]    # completed -> down


def test_fires_up_when_a_required_key_released():
    combo, events = make([CTRL, CMD])
    combo.press(CTRL)
    combo.press(CMD)
    combo.release(CMD)
    assert events == ["down", "up"]


def test_releasing_unrelated_key_does_not_end_hold():
    # The old bug: releasing ANY key while active ended the hold. Holding the
    # combo and releasing an unrelated key must NOT fire up.
    combo, events = make([CTRL, CMD])
    combo.press(CTRL)
    combo.press(CMD)
    combo.release(A)             # unrelated key
    combo.release(SHIFT)         # another unrelated key
    assert events == ["down"]    # still held


def test_key_repeat_is_idempotent():
    combo, events = make([CTRL, CMD])
    combo.press(CTRL)
    combo.press(CMD)
    combo.press(CMD)             # OS key-repeat
    combo.press(CTRL)
    assert events == ["down"]    # only one down


def test_single_key_hotkey():
    combo, events = make([keyboard.Key.f8])
    combo.press(keyboard.Key.f8)
    combo.release(keyboard.Key.f8)
    assert events == ["down", "up"]


def test_re_press_after_release_fires_again():
    combo, events = make([CTRL, CMD])
    combo.press(CTRL)
    combo.press(CMD)
    combo.release(CMD)
    combo.press(CMD)
    combo.release(CTRL)
    assert events == ["down", "up", "down", "up"]


# --- OS ground-truth polling (self-heal + watchdog, finding 4) -------------
def test_all_required_down_uses_pollable_vks():
    combo, _ = make([CTRL, CMD])
    # ctrl -> VK_CONTROL 0x11; win -> VK_LWIN 0x5B / VK_RWIN 0x5C.
    assert combo.all_required_down(lambda vk: vk in {0x11, 0x5B}) is True
    assert combo.all_required_down(lambda vk: vk == 0x11) is False   # win up


def test_all_required_down_accepts_the_right_hand_win_key():
    # pynput reports the Windows key as VK_LWIN, but a right-Win press is 0x5C;
    # the poll must count either as "win is down".
    combo, _ = make([CTRL, CMD])
    assert combo.all_required_down(lambda vk: vk in {0x11, 0x5C}) is True


def test_all_required_down_accepts_right_hand_modifiers():
    # Shift arrives as VK_LSHIFT from pynput; a right-shift poll (0xA1) must
    # still count. (Guards the modifier-group expansion.)
    combo, _ = make([SHIFT, A])
    assert combo.all_required_down(lambda vk: vk in {0xA1, ord("A")}) is True


def test_reconcile_heals_a_stuck_active_when_the_keys_are_up():
    combo, events = make([CTRL, CMD])
    combo.press(CTRL)
    combo.press(CMD)
    assert events == ["down"]
    # The CMD key-up was lost — the combo still believes it is held. OS ground
    # truth says both keys are up, so reconcile fires the up edge to unwedge it.
    assert combo.reconcile(lambda vk: False) is True
    assert events == ["down", "up"]
    assert combo.active is False


def test_reconcile_is_a_noop_while_the_keys_are_genuinely_down():
    combo, events = make([CTRL, CMD])
    combo.press(CTRL)
    combo.press(CMD)
    assert combo.reconcile(lambda vk: True) is False   # still really held
    assert events == ["down"]
    assert combo.active is True


def test_reconcile_is_a_noop_when_not_active():
    combo, events = make([CTRL, CMD])
    assert combo.reconcile(lambda vk: False) is False
    assert events == []


def test_active_property_tracks_the_combo_state():
    combo, _ = make([CTRL, CMD])
    assert combo.active is False
    combo.press(CTRL)
    assert combo.active is False        # not complete yet
    combo.press(CMD)
    assert combo.active is True
    combo.release(CTRL)
    assert combo.active is False
