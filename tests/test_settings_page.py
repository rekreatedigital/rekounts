"""Tests for the Settings page embedded in the Hub.

Covers the two things that must not regress from wave 1 — hotkey capture with
validation, and live-apply — plus the new instant-apply model.
"""
import os

import pytest

from rekounts.config import Config
from rekounts.history import History

# Offscreen so the suite stays headless and never pops a real window.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
QtCore = pytest.importorskip("PySide6.QtCore")
QtGui = pytest.importorskip("PySide6.QtGui")
QtWidgets = pytest.importorskip("PySide6.QtWidgets")

from rekounts import sounds  # noqa: E402  (after importorskip)
from rekounts.ui.settings_page import (  # noqa: E402  (after importorskip)
    SettingsPage, ToggleSwitch, _compose, _nearest_volume,
    _normalize_mic_entries, _qt_event_to_token, microphone_options,
    pretty_hotkey)

FAKE_MICS = [("Microphone (ME6S)", "Microphone (ME6S)"),
             ("EMEET SmartCam", "EMEET SmartCam")]


@pytest.fixture(scope="module")
def app():
    yield QtWidgets.QApplication.instance() or QtWidgets.QApplication([])


@pytest.fixture
def cfg(tmp_path):
    return Config(path=tmp_path / "config.json")


@pytest.fixture
def history(tmp_path):
    h = History(path=tmp_path / "history.db")
    yield h
    h.close()


@pytest.fixture
def page(app, cfg, history, monkeypatch):
    """A page with a deterministic mic list and a counting apply callback."""
    monkeypatch.setattr("rekounts.ui.settings_page.microphone_options",
                        lambda: list(FAKE_MICS))
    applies = []
    p = SettingsPage(cfg, history, on_saved=lambda: applies.append(1),
                     startup_setter=lambda enabled: applies.append(("startup", enabled)))
    p.applies = applies
    yield p
    p.deleteLater()


def _key_event(kind, key):
    return QtGui.QKeyEvent(kind, key, QtCore.Qt.NoModifier)


def _press(widget, key):
    widget.keyPressEvent(_key_event(QtCore.QEvent.KeyPress, key))


def _release(widget, key):
    widget.keyReleaseEvent(_key_event(QtCore.QEvent.KeyRelease, key))


# ============================================================ instant apply
def test_toggle_persists_immediately_and_schedules_apply(page, cfg, tmp_path):
    page.sound_effects.setChecked(False)
    assert cfg.get("sound_effects") is False
    # Persisted to disk right away — not deferred behind the apply timer.
    assert Config(path=tmp_path / "config.json").get("sound_effects") is False
    assert page._apply_timer.isActive()


def test_hedge_switch_is_wired_to_its_config_key(page, cfg):
    assert page.strip_discourse.isChecked() is True      # app default: on
    page.strip_discourse.setChecked(False)
    assert cfg.get("strip_discourse_fillers") is False


def test_long_text_via_paste_switch_is_wired_to_its_config_key(page, cfg):
    # The documented escape hatch for apps that silently ignore Ctrl+V — a
    # refused paste is undetectable, so the user needs a way to force typing.
    assert page.long_text_via_paste.isChecked() is True   # app default: on
    page.long_text_via_paste.setChecked(False)
    assert cfg.get("long_text_via_paste") is False


def test_burst_of_changes_coalesces_into_one_apply(page):
    page.strip_fillers.setChecked(not page.strip_fillers.isChecked())
    page.auto_cap.setChecked(not page.auto_cap.isChecked())
    page.fix_punct.setChecked(not page.fix_punct.isChecked())
    assert page.applies == []          # nothing applied yet — still coalescing
    page._flush_apply()
    assert page.applies == [1]         # one rebuild for three changes


def test_hiding_the_page_flushes_a_pending_apply(page):
    # Closing the Hub (or navigating off Settings) hides the page — a change
    # made a moment earlier must still reach the app.
    page.show()
    page.show_pill.setChecked(False)
    assert page._apply_timer.isActive()
    page.hide()
    assert page.applies == [1]
    assert not page._apply_timer.isActive()


def test_apply_callback_failure_does_not_escape(app, cfg, history, monkeypatch):
    monkeypatch.setattr("rekounts.ui.settings_page.microphone_options",
                        lambda: list(FAKE_MICS))

    def boom():
        raise RuntimeError("apply exploded")

    p = SettingsPage(cfg, history, on_saved=boom)
    p.sound_effects.setChecked(False)
    p._flush_apply()                   # must not raise
    assert cfg.get("sound_effects") is False


def test_unwritable_config_does_not_schedule_an_apply(page, monkeypatch):
    def boom():
        raise OSError("disk full")

    monkeypatch.setattr(page.config, "save", boom)
    page.sound_effects.setChecked(False)
    assert not page._apply_timer.isActive()
    assert page.applies == []


# =============================================================== sound effects
def test_sound_controls_live_in_the_audio_section(page):
    """Discoverability, not decoration: someone hunting for the off switch looks
    under Audio. It used to sit under System, three sections further down."""
    audio = next(w for w in page.findChildren(QtWidgets.QLabel)
                 if w.text() == "AUDIO")
    card = audio.parent()
    assert page.sound_effects in card.findChildren(ToggleSwitch)
    assert page.sound_volume in card.findChildren(QtWidgets.QComboBox)


def test_volume_persists_immediately_and_schedules_apply(page, cfg, tmp_path):
    page.sound_volume.setCurrentIndex(
        page.sound_volume.findData(sounds.VOLUME_LOUD))
    assert cfg.get("sound_volume") == sounds.VOLUME_LOUD
    assert Config(path=tmp_path / "config.json").get("sound_volume") == \
        sounds.VOLUME_LOUD
    assert page._apply_timer.isActive()


def test_volume_offers_exactly_the_three_levels(page):
    data = [page.sound_volume.itemData(i)
            for i in range(page.sound_volume.count())]
    assert data == list(sounds.VOLUME_LEVELS)


def test_volume_defaults_to_normal(page):
    assert page.sound_volume.currentData() == sounds.VOLUME_NORMAL


def test_volume_greys_out_while_sounds_are_off(page):
    assert page.sound_volume.isEnabled() is True
    page.sound_effects.setChecked(False)
    assert page.sound_volume.isEnabled() is False
    assert "on to change" in page.volume_row.hint.text()
    page.sound_effects.setChecked(True)
    assert page.sound_volume.isEnabled() is True


def test_volume_starts_greyed_out_when_sounds_are_already_off(
        app, cfg, history, monkeypatch):
    """The disabled state has to be right on construction, not only after a
    toggle — a user who turned sounds off last week reopens to a live-looking
    control otherwise."""
    monkeypatch.setattr("rekounts.ui.settings_page.microphone_options",
                        lambda: list(FAKE_MICS))
    cfg.set("sound_effects", False)
    p = SettingsPage(cfg, history)
    assert p.sound_volume.isEnabled() is False
    p.deleteLater()


@pytest.mark.parametrize("stored,expected", [
    (0.05, sounds.VOLUME_SOFT),
    (0.09, sounds.VOLUME_NORMAL),
    (0.18, sounds.VOLUME_LOUD),
    (0.15, sounds.VOLUME_LOUD),      # hand-edited: snaps to the nearest level
    (0.0, sounds.VOLUME_SOFT),
    (None, sounds.VOLUME_NORMAL),    # key absent
    ("loud", sounds.VOLUME_NORMAL),  # junk
])
def test_nearest_volume_never_misreports_what_is_playing(stored, expected):
    assert _nearest_volume(stored) == expected


def test_hand_edited_volume_is_shown_as_the_nearest_level(
        app, cfg, history, monkeypatch):
    monkeypatch.setattr("rekounts.ui.settings_page.microphone_options",
                        lambda: list(FAKE_MICS))
    cfg.set("sound_volume", 0.16)
    p = SettingsPage(cfg, history)
    assert p.sound_volume.currentData() == sounds.VOLUME_LOUD
    p.deleteLater()


# =============================================================== hotkey (wave 1)
def test_capture_commits_a_valid_combo_and_persists_it(page, cfg):
    _press(page.hotkey, QtCore.Qt.Key_Control)
    _press(page.hotkey, QtCore.Qt.Key_Alt)
    _press(page.hotkey, QtCore.Qt.Key_F9)
    _release(page.hotkey, QtCore.Qt.Key_F9)
    assert page.hotkey.hotkey() == "ctrl+alt+f9"
    assert cfg.get("hotkey") == "ctrl+alt+f9"


def test_unmappable_key_leaves_the_hotkey_untouched(page, cfg):
    before = page.hotkey.hotkey()
    _press(page.hotkey, QtCore.Qt.Key_Escape)     # not a supported token
    _release(page.hotkey, QtCore.Qt.Key_Escape)
    assert page.hotkey.hotkey() == before
    assert cfg.get("hotkey") == before


def test_invalid_hotkey_never_reaches_config(page, cfg):
    before = cfg.get("hotkey")
    page._hotkey_changed("not-a-real+++key")      # belt-and-suspenders path
    assert cfg.get("hotkey") == before
    assert "isn" in page.hotkey_row.hint.text()   # "isn't a usable hotkey"


def test_reset_restores_the_default_and_persists(page, cfg):
    page.hotkey.set_hotkey("ctrl+alt+f9")
    assert cfg.get("hotkey") == "ctrl+alt+f9"
    page.hotkey.set_hotkey("ctrl+win")
    assert cfg.get("hotkey") == "ctrl+win"


def test_focus_out_discards_a_half_typed_combo(page):
    committed = page.hotkey.hotkey()
    _press(page.hotkey, QtCore.Qt.Key_Control)    # chord still in progress
    page.hotkey.focusOutEvent(QtGui.QFocusEvent(QtCore.QEvent.FocusOut))
    assert page.hotkey.hotkey() == committed
    assert page.hotkey.text() == pretty_hotkey(committed)


def test_hotkey_is_shown_prettified_but_stored_canonically(page, cfg):
    # The DISPLAY name of the "win" token is per-platform ("Win" on Windows,
    # "Cmd" on a Mac keyboard — rekounts/ui/platform_text.py), so this asserts
    # against the platform's own table rather than a hardcoded "Ctrl + Win".
    # The point of the test is the stored/shown SPLIT, which holds on both.
    assert page.hotkey.text() == pretty_hotkey("ctrl+win")
    assert cfg.get("hotkey") == "ctrl+win"
    assert pretty_hotkey("ctrl+alt+f9") == "Ctrl + Alt + F9"
    assert pretty_hotkey("page_up") == "Page Up"
    assert pretty_hotkey("") == ""


def test_compose_orders_modifiers_canonically():
    assert _compose(["f9", "win", "ctrl", "shift", "alt"]) == "ctrl+alt+shift+win+f9"


def test_qt_event_to_token_maps_modifiers_letters_and_function_keys(app):
    assert _qt_event_to_token(_key_event(QtCore.QEvent.KeyPress,
                                         QtCore.Qt.Key_Meta)) == "win"
    assert _qt_event_to_token(_key_event(QtCore.QEvent.KeyPress,
                                         QtCore.Qt.Key_K)) == "k"
    assert _qt_event_to_token(_key_event(QtCore.QEvent.KeyPress,
                                         QtCore.Qt.Key_F8)) == "f8"
    assert _qt_event_to_token(_key_event(QtCore.QEvent.KeyPress,
                                         QtCore.Qt.Key_Escape)) is None


def test_hotkey_changed_signal_only_fires_on_a_real_change(page):
    seen = []
    page.hotkey.hotkeyChanged.connect(seen.append)
    page.hotkey.set_hotkey(page.hotkey.hotkey())
    assert seen == []
    page.hotkey.set_hotkey("ctrl+alt+f9")
    assert seen == ["ctrl+alt+f9"]


# ================================================================== controls
def test_dropdowns_persist_values_not_labels(page, cfg):
    page.model.setCurrentIndex(page.model.findData("medium"))
    page.language.setCurrentIndex(page.language.findData("tl"))
    page.insertion.setCurrentIndex(page.insertion.findData("keystroke"))
    assert cfg.get("model") == "medium"
    assert cfg.get("language") == "tl"
    assert cfg.get("insertion_mode") == "keystroke"


def test_model_dropdown_offers_exactly_the_published_models(page):
    # The dropdown must only offer models the release-host manifest can serve;
    # distil-large-v3 / large-v3-turbo rejoin it once their files are published.
    values = {page.model.itemData(i) for i in range(page.model.count())}
    assert {"base", "small", "medium"} <= values
    assert "distil-large-v3" not in values
    assert "large-v3-turbo" not in values


def test_processing_device_persists(page, cfg):
    page.device.setCurrentIndex(page.device.findData("auto"))
    assert cfg.get("device") == "auto"
    page.device.setCurrentIndex(page.device.findData("cpu"))
    assert cfg.get("device") == "cpu"


def test_max_recording_is_shown_in_minutes_and_stored_in_seconds(page, cfg):
    assert page.max_minutes.value() == 10         # default 600s
    page.max_minutes.setValue(12)
    assert cfg.get("max_recording_seconds") == 720


def test_zero_minutes_means_no_limit(page, cfg):
    page.max_minutes.setValue(0)
    assert cfg.get("max_recording_seconds") == 0
    assert page.max_minutes.text() == "No limit"


def test_microphone_selection_persists(page, cfg):
    page.mic.setCurrentIndex(page.mic.findData("EMEET SmartCam"))
    assert cfg.get("microphone") == "EMEET SmartCam"
    page.mic.setCurrentIndex(page.mic.findData(None))
    assert cfg.get("microphone") is None


def test_system_default_is_always_the_first_microphone_option(page):
    assert page.mic.itemData(0) is None
    assert page.mic.count() == len(FAKE_MICS) + 1


def test_history_switch_flips_the_store_live(page, history, cfg):
    page.history_enabled.setChecked(False)
    assert history.enabled is False
    assert cfg.get("history_enabled") is False
    page.history_enabled.setChecked(True)
    assert history.enabled is True


def test_clear_history_hint_reports_the_count(page, history):
    history.add("hello there", "Hello there.", 1.0)
    assert "1 dictation" in page._history_count_hint()


def test_launch_at_login_updates_the_registry_entry(page, cfg):
    page.launch_startup.setChecked(True)
    assert cfg.get("launch_on_startup") is True
    assert ("startup", True) in page.applies


# --------- finding 3: speech-model selector is inert while live typing on -----
def test_launch_switch_reflects_the_real_state_not_just_config(
        app, cfg, history, monkeypatch):
    monkeypatch.setattr("rekounts.ui.settings_page.microphone_options",
                        lambda: list(FAKE_MICS))
    cfg.set("launch_on_startup", True)                 # config says ON...
    p = SettingsPage(cfg, history, startup_getter=lambda: False)  # ...Windows skips us
    assert p.launch_startup.isChecked() is False       # honest: shows OFF


def test_showing_settings_resyncs_the_launch_switch(app, cfg, history, monkeypatch):
    monkeypatch.setattr("rekounts.ui.settings_page.microphone_options",
                        lambda: list(FAKE_MICS))
    state = {"enabled": True}
    p = SettingsPage(cfg, history, startup_getter=lambda: state["enabled"])
    assert p.launch_startup.isChecked() is True
    state["enabled"] = False                           # disabled in Task Manager meanwhile
    p.showEvent(QtGui.QShowEvent())
    assert p.launch_startup.isChecked() is False
    assert cfg.get("launch_on_startup") is False        # config reconciled to reality


def test_resyncing_the_launch_switch_does_not_write_the_registry(
        app, cfg, history, monkeypatch):
    monkeypatch.setattr("rekounts.ui.settings_page.microphone_options",
                        lambda: list(FAKE_MICS))
    setter_calls = []
    state = {"enabled": False}
    p = SettingsPage(cfg, history,
                     startup_setter=lambda e: setter_calls.append(e),
                     startup_getter=lambda: state["enabled"])
    state["enabled"] = True
    p.showEvent(QtGui.QShowEvent())
    assert p.launch_startup.isChecked() is True
    assert setter_calls == []            # the sync only mirrors; it never rewrites


def test_launch_at_login_failure_is_reported_not_raised(app, cfg, history,
                                                        monkeypatch):
    monkeypatch.setattr("rekounts.ui.settings_page.microphone_options",
                        lambda: list(FAKE_MICS))

    def boom(enabled):
        raise PermissionError("registry locked")

    p = SettingsPage(cfg, history, startup_setter=boom)
    p.launch_startup.setChecked(True)              # must not raise
    assert cfg.get("launch_on_startup") is True    # config still records intent
    assert "Could not update" in p.startup_row.hint.text()


def test_every_switch_starts_from_the_stored_value(app, cfg, history, monkeypatch):
    monkeypatch.setattr("rekounts.ui.settings_page.microphone_options",
                        lambda: list(FAKE_MICS))
    cfg.set("preroll_enabled", True)
    cfg.set("show_pill", False)
    p = SettingsPage(cfg, history)
    assert p.preroll.isChecked() is True
    assert p.show_pill.isChecked() is False


def test_building_the_page_writes_nothing(app, cfg, history, monkeypatch):
    """Opening Settings must not itself count as a settings change."""
    monkeypatch.setattr("rekounts.ui.settings_page.microphone_options",
                        lambda: list(FAKE_MICS))
    applies = []
    p = SettingsPage(cfg, history, on_saved=lambda: applies.append(1))
    assert applies == []
    assert not p._apply_timer.isActive()


# ============================================================== microphones
def test_normalize_accepts_names_pairs_and_dicts():
    assert _normalize_mic_entries(["Mic A"]) == [("Mic A", "Mic A")]
    assert _normalize_mic_entries([("Mic A (USB)", "Mic A")]) == [("Mic A (USB)", "Mic A")]
    assert _normalize_mic_entries([{"name": "Mic A"}]) == [("Mic A", "Mic A")]
    assert _normalize_mic_entries([{"name": "Mic A", "label": "Mic A (USB)"}]) == \
        [("Mic A (USB)", "Mic A")]
    # A (name, index) pair keeps the name as the stored value.
    assert _normalize_mic_entries([("Mic A", 3)]) == [("Mic A", "Mic A")]
    assert _normalize_mic_entries(None) == []


def test_microphone_options_prefers_the_device_utils_contract(monkeypatch):
    from rekounts import device_utils
    monkeypatch.setattr(device_utils, "list_microphones",
                        lambda: ["Clean Mic"], raising=False)
    assert microphone_options() == [("Clean Mic", "Clean Mic")]


def test_microphone_options_falls_back_when_the_contract_is_missing(monkeypatch):
    from rekounts import device_utils
    monkeypatch.delattr(device_utils, "list_microphones", raising=False)
    monkeypatch.setattr("rekounts.ui.settings_page._fallback_microphones",
                        lambda: [("Raw Mic", "Raw Mic")])
    assert microphone_options() == [("Raw Mic", "Raw Mic")]


def test_microphone_options_falls_back_when_the_contract_raises(monkeypatch):
    from rekounts import device_utils

    def boom():
        raise RuntimeError("driver on fire")

    monkeypatch.setattr(device_utils, "list_microphones", boom, raising=False)
    monkeypatch.setattr("rekounts.ui.settings_page._fallback_microphones",
                        lambda: [("Raw Mic", "Raw Mic")])
    assert microphone_options() == [("Raw Mic", "Raw Mic")]


# =================================================================== switch
def test_toggle_switch_is_a_checkbox_underneath(app):
    sw = ToggleSwitch(checked=True)
    assert sw.isChecked() is True
    seen = []
    sw.toggled.connect(seen.append)
    sw.setChecked(False)
    assert seen == [False]
    assert sw.knob is not None      # animated position property exists


# ------------------------------------------------------------- scratchpad
def test_scratchpad_switch_persists_and_schedules_an_apply(page):
    page.scratchpad.setChecked(False)
    assert page.config.get("scratchpad_enabled") is False
    assert page._apply_timer.isActive()
    page._flush_apply()
    assert page.applies == [1]

    page.scratchpad.setChecked(True)
    assert page.config.get("scratchpad_enabled") is True


def test_scratchpad_switch_starts_from_the_stored_value(app, cfg, history,
                                                        monkeypatch):
    monkeypatch.setattr("rekounts.ui.settings_page.microphone_options",
                        lambda: list(FAKE_MICS))
    cfg.set("scratchpad_enabled", False)
    p = SettingsPage(cfg, history)
    assert p.scratchpad.isChecked() is False


def test_the_scratchpad_ships_on_by_default():
    """Nothing appears on screen until the user opens it, so defaulting to on
    costs them nothing and saves a hunt through Settings."""
    from rekounts.config import DEFAULTS
    assert DEFAULTS["scratchpad_enabled"] is True
