"""The pending-applies indicator: what has changed but hasn't taken effect.

Two things in Rekounts are genuinely deferred — a model reload (seconds, during
which the OLD model keeps transcribing) and a mic change made mid-recording.
Both used to be announced only as a toast, so the "Tray notifications" switch
could hide them completely. These pin the state machine that replaced that.
"""
import pytest

from rekounts.__main__ import PendingApplies, _model_loading_text


@pytest.fixture
def seen():
    """A sink that records every rendered message it is pushed."""
    return []


@pytest.fixture
def pending(seen):
    return PendingApplies(sinks=[seen.append])


# ------------------------------------------------------------------ rendering
def test_nothing_pending_renders_empty(pending):
    assert pending.message() == ""


def test_set_then_clear_round_trips(pending, seen):
    pending.set("model", "Loading Medium…")
    assert pending.message() == "Loading Medium…"
    pending.clear("model")
    assert pending.message() == ""
    assert seen == ["Loading Medium…", ""]


def test_reasons_are_independent(pending):
    """A mic change landing must not erase a model reload still in flight."""
    pending.set("model", "Loading Medium…")
    pending.set("microphone", "New mic next time.")
    pending.clear("microphone")
    assert pending.message() == "Loading Medium…"


def test_several_pending_reasons_are_all_shown_oldest_first(pending):
    pending.set("model", "A")
    pending.set("microphone", "B")
    assert pending.message() == "A" + PendingApplies.SEPARATOR + "B"


def test_setting_the_same_message_twice_does_not_re_notify(pending, seen):
    pending.set("model", "Loading Medium…")
    pending.set("model", "Loading Medium…")
    assert seen == ["Loading Medium…"]


def test_replacing_a_reasons_message_notifies(pending, seen):
    pending.set("model", "Loading Medium…")
    pending.set("model", "Loading Base…")
    assert seen == ["Loading Medium…", "Loading Base…"]


def test_clearing_something_that_was_never_pending_is_silent(pending, seen):
    pending.clear("model")
    assert seen == []


# --------------------------------------------------------------------- sinks
def test_every_sink_is_pushed(seen):
    other = []
    p = PendingApplies(sinks=[seen.append, other.append])
    p.set("model", "x")
    assert seen == other == ["x"]


def test_one_broken_sink_never_stops_the_others():
    """The pill and the Hub are independent surfaces — losing one must not
    silently cost the user the other, which is the whole point of having two."""
    good = []

    def boom(_text):
        raise RuntimeError("widget already destroyed")

    p = PendingApplies(sinks=[boom, good.append])
    p.set("model", "x")
    assert good == ["x"]


def test_sinks_added_after_the_fact_are_used(seen):
    """The Hub is built after the first reload can already be in flight."""
    p = PendingApplies()
    p.set("model", "x")
    p.sinks.append(seen.append)
    p.clear("model")
    assert seen == [""]


# ------------------------------------------------------------- loading text
def test_loading_text_names_the_model_still_doing_the_work():
    text = _model_loading_text("medium", "small")
    assert "medium" in text and "small" in text


def test_loading_text_without_a_known_previous_model_still_reassures():
    text = _model_loading_text("medium", None)
    assert "medium" in text
    assert "keeps working" in text


def test_loading_text_does_not_claim_a_switch_that_is_not_happening():
    """device-only change: same model name on both sides."""
    assert _model_loading_text("medium", "medium") == _model_loading_text("medium")
