"""Tests for the Hub shell and the wiring contract __main__ depends on.

The contract these lock down:
    Dashboard(config, history, on_settings_saved=None)
    Dashboard.open_settings()      -> Hub raised on the Settings page
    Dashboard.open_and_raise()     -> Hub raised on whatever page it was on
"""
import inspect
import os

import pytest

from rekounts.config import Config
from rekounts.history import History

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
QtWidgets = pytest.importorskip("PySide6.QtWidgets")

from rekounts.ui.dashboard import Dashboard  # noqa: E402 (after importorskip)
from rekounts.ui.settings_page import SettingsPage  # noqa: E402


@pytest.fixture(scope="module")
def app():
    yield QtWidgets.QApplication.instance() or QtWidgets.QApplication([])


@pytest.fixture
def hub(app, tmp_path, monkeypatch):
    monkeypatch.setattr("rekounts.ui.settings_page.microphone_options",
                        lambda: [("Mic A", "Mic A")])
    # Dashboard wires the real launch-at-login query/setter into Settings; keep
    # the suite off the real Windows registry.
    monkeypatch.setattr("rekounts.startup.is_enabled", lambda *a, **k: False)
    monkeypatch.setattr("rekounts.startup.set_enabled", lambda *a, **k: None)
    cfg = Config(path=tmp_path / "config.json")
    history = History(path=tmp_path / "history.db")
    applies = []
    d = Dashboard(cfg, history, on_settings_saved=lambda: applies.append(1))
    d.applies = applies
    d.config = cfg
    yield d
    d.close()
    d.deleteLater()
    history.close()


# ============================================================ wiring contract
def test_constructor_signature_matches_the_contract():
    params = list(inspect.signature(Dashboard.__init__).parameters)
    assert params == ["self", "config", "history", "on_settings_saved"]
    assert (inspect.signature(Dashboard.__init__)
            .parameters["on_settings_saved"].default is None)


def test_on_settings_saved_is_invoked_with_no_arguments(hub):
    hub.settings.sound_effects.setChecked(False)
    hub.settings._flush_apply()
    assert hub.applies == [1]


def test_open_settings_raises_the_hub_on_the_settings_page(hub):
    hub.show_page(0)
    hub.open_settings()
    assert hub.stack.currentIndex() == hub.settings_index
    assert hub.stack.currentWidget() is hub.settings
    assert hub._nav_group.button(hub.settings_index).isChecked()


def test_open_and_raise_keeps_the_current_page(hub):
    hub.show_page(1)
    hub.open_and_raise()
    assert hub.stack.currentIndex() == 1


def test_settings_is_a_page_not_a_second_window(hub):
    assert isinstance(hub.settings, SettingsPage)
    # Embedded in the stack -> it can never appear as its own top-level window.
    assert hub.settings.parent() is not None
    assert hub.stack.indexOf(hub.settings) == hub.settings_index


def test_no_separate_settings_window_module_remains():
    with pytest.raises(ModuleNotFoundError):
        __import__("rekounts.ui.settings_window")


# =================================================================== the shell
def test_hub_has_the_expected_pages_in_order(hub):
    assert [name for name, _ in hub.pages] == [
        "Dictation", "Insights", "Dictionary", "Settings", "Account"]


def test_every_page_has_a_nav_button(hub):
    assert len(hub._nav_group.buttons()) == len(hub.pages)


def test_show_page_checks_the_matching_nav_button(hub):
    for i in range(len(hub.pages)):
        hub.show_page(i)
        assert hub.stack.currentIndex() == i
        assert hub._nav_group.button(i).isChecked()


def test_dictionary_page_states_that_words_influence_recognition(hub):
    page = hub.pages[2][1]
    hints = [w.text() for w in page.findChildren(QtWidgets.QLabel)
             if w.property("role") == "hint"]
    assert any("recognizer" in h for h in hints), hints


def test_settings_changes_reach_the_shared_config(hub):
    hub.settings.max_minutes.setValue(2)
    assert hub.config.get("max_recording_seconds") == 120


# ======================================================= live page refresh (4)
def test_result_refreshes_the_visible_dictation_page(hub):
    dict_page = hub.pages[0][1]
    hub.stack.setCurrentIndex(0)                 # Dictation is visible
    dict_page.history.add("hello world", "Hello world.", 1.0)
    # A dictation lands while the page sits open — it must appear without a
    # page switch.
    hub.on_result_recorded("hello world", "Hello world.", 1.0, True)
    assert any(e.get("cleaned_text") == "Hello world." for e in dict_page._loaded)


def test_result_refreshes_the_visible_insights_page(hub):
    ins_page = hub.pages[1][1]
    hub.stack.setCurrentIndex(1)                 # Insights is visible
    ins_page.history.add("one two three", "One two three.", 1.0)
    hub.on_result_recorded("one two three", "One two three.", 1.0, True)
    assert ins_page.cards["words_all"].value.text() == "3"


def test_result_on_a_non_history_page_is_harmless(hub):
    hub.show_page(hub.settings_index)            # Settings visible
    hub.on_result_recorded("x", "x", 1.0, True)  # must not raise / must be a no-op


# =========================================================== account profile (7)
def test_sidebar_profile_hidden_without_a_display_name(hub):
    assert hub._name_label.text() == ""
    assert hub._profile_wrap.isHidden() is True
    assert hub._avatar_label.isHidden() is True


def test_saving_a_profile_name_renders_it_in_the_sidebar(hub):
    account = hub.pages[4][1]
    account.name.setText("Ada Lovelace")
    account._save()
    assert hub._name_label.text() == "Ada Lovelace"
    assert hub._profile_wrap.isHidden() is False
    pix = hub._avatar_label.pixmap()             # a monogram is drawn from "A"
    assert pix is not None and not pix.isNull()


def test_insights_surfaces_dictation_and_active_day_counts(hub):
    ins_page = hub.pages[1][1]
    assert "entries_all" in ins_page.cards
    assert "active_days" in ins_page.cards
    ins_page.history.add("alpha beta", "Alpha beta.", 1.0)
    ins_page.refresh()
    assert ins_page.cards["entries_all"].value.text() == "1"
    assert ins_page.cards["active_days"].value.text() == "1"


# ============================================================== sidebar chrome (3)
def test_clicking_a_nav_item_does_not_park_keyboard_focus_on_it(hub):
    """The platform draws a dotted focus box inside a nav item that holds
    keyboard focus — on top of a pill that already shows the selection. Nav is
    reached by clicking, so click-focus buys nothing and costs that artefact."""
    from PySide6 import QtCore
    for i in range(len(hub.pages)):
        policy = hub._nav_group.button(i).focusPolicy()
        assert not (policy & QtCore.Qt.ClickFocus), "nav item takes focus on click"


def test_nav_items_are_still_reachable_by_keyboard(hub):
    """Killing the focus box must not strand keyboard users: Tab still lands
    here, and the theme gives :focus a visible style of its own."""
    from PySide6 import QtCore
    for i in range(len(hub.pages)):
        policy = hub._nav_group.button(i).focusPolicy()
        assert policy & QtCore.Qt.TabFocus, "nav item is not tab-reachable"


def test_the_privacy_tagline_sits_under_the_wordmark_exactly_once(hub):
    from PySide6 import QtWidgets
    labels = [w for w in hub.findChildren(QtWidgets.QLabel)
              if w.text() == "Local · Private"]
    assert len(labels) == 1, "tagline missing or duplicated"
    assert labels[0].property("role") == "meta"
