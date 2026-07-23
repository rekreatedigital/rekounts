"""The comma-delimited hedge tier ("you know", "I mean", "like", "right").

Unlike FILLERS these words all have literal uses ("I like it", "turn right"),
so they are removed ONLY when punctuation marks them as asides — the form
Whisper reliably produces for the discourse use.
"""
from rekounts.config import DEFAULTS
from rekounts.text_cleaner import TextCleaner


def _c():
    return TextCleaner(strip_fillers=False, auto_capitalize=False,
                       fix_punctuation_spacing=False,
                       strip_discourse_fillers=True)


def test_comma_wrapped_hedges_are_dropped():
    assert _c().clean("it works, you know, most days") == "it works, most days"
    assert _c().clean("the answer is, like, seven") == "the answer is, seven"
    assert _c().clean("it broke, I mean, it failed") == "it broke, it failed"
    assert _c().clean("we won, right, and moved on") == "we won, and moved on"


def test_sentence_initial_hedge_is_dropped():
    assert _c().clean("You know, it works") == "it works"
    assert _c().clean("I mean, we tried") == "we tried"
    assert _c().clean("Right, let's go") == "let's go"


def test_hedge_before_the_final_period_keeps_the_period():
    assert _c().clean("It works, you know.") == "It works."


def test_hedge_dangling_at_the_end_takes_its_comma():
    assert _c().clean("it works, you know") == "it works"


def test_literal_uses_are_never_touched():
    assert _c().clean("I like it") == "I like it"
    assert _c().clean("turn right now") == "turn right now"
    assert (_c().clean("you have the right to remain silent")
            == "you have the right to remain silent")
    assert _c().clean("I mean it") == "I mean it"
    assert _c().clean("you know the answer") == "you know the answer"
    assert _c().clean("Like father, like son.") == "Like father, like son."


def test_tag_questions_keep_their_meaning():
    # "?" is doing real work — this is a question, not a hedge
    assert _c().clean("it works, right?") == "it works, right?"


def test_off_by_default_in_the_class():
    c = TextCleaner(strip_fillers=False, auto_capitalize=False,
                    fix_punctuation_spacing=False)
    assert c.clean("it works, you know, most days") == "it works, you know, most days"


def test_on_by_default_in_the_app_config():
    assert DEFAULTS["strip_discourse_fillers"] is True


def test_stacks_with_core_fillers_and_collapse():
    c = TextCleaner(strip_fillers=True, auto_capitalize=True,
                    fix_punctuation_spacing=True, collapse_repeats=True,
                    strip_discourse_fillers=True)
    assert (c.clean("So, um, we could, like, try it, you know.")
            == "So, we could, try it.")


def test_a_hedge_that_is_the_whole_utterance_survives():
    assert _c().clean("Right.") == "Right."
    assert _c().clean("You know.") == "You know."


def test_a_trailing_hedge_sentence_still_drops_when_more_was_said():
    assert _c().clean("Is that OK? Right.") == "Is that OK?"
