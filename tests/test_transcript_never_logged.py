"""No part of a dictation may reach the log file. Ever.

docs/privacy.md states this without qualification — "It records startup, model
loading, errors, and audio *durations* — **not** your transcripts" — so it is a
published promise, not a preference, and the fix belongs in the code rather than
in a softer sentence.

The hole was in the dictionary-replacement pass. The compiled pattern matches
with ``re.IGNORECASE``, whose case-equivalence is WIDER than ``str.lower()``, so
the matched span could fail the ``lookup[...lower()]`` that followed it. The
resulting ``KeyError``'s string form *is* the matched span, and it went straight
into ``log.warning(..., e)``.

Three BMP characters trigger it — U+017F LATIN SMALL LETTER LONG S, U+0130
LATIN CAPITAL LETTER I WITH DOT ABOVE, U+0131 LATIN SMALL LETTER DOTLESS I —
and each is a plausible thing for a speech model to emit or a user to have in a
dictionary entry. The matched span is a phrase, not a word: a rule for "sam
altman" leaks "sam altman" out of a sentence about a salary.
"""
import logging

import pytest

from rekounts.text_cleaner import TextCleaner, build_replacements

# The exact case-equivalences re.IGNORECASE honours and str.lower() does not.
LONG_S = "ſ"        # matches s / S
DOTTED_I = "İ"      # matches i / I
DOTLESS_I = "ı"     # matches i / I


@pytest.fixture
def logged(caplog):
    caplog.set_level(logging.DEBUG, logger="rekounts.text_cleaner")
    return caplog


def _cleaner(pairs):
    """A cleaner with every other pass off, so only replacements are in play."""
    return TextCleaner(
        replacements_provider=lambda: pairs,
        strip_fillers=False, collapse_repeats=False, auto_capitalize=False,
        strip_discourse_fillers=False, fix_punctuation_spacing=False)


@pytest.mark.parametrize("odd,heard,spoken,marker", [
    (LONG_S, "sam altman", f"{LONG_S}am altman", "altman"),
    (DOTTED_I, "ian mcewan", f"{DOTTED_I}an mcewan", "mcewan"),
    (DOTLESS_I, "ian mcewan", f"{DOTLESS_I}an mcewan", "mcewan"),
])
def test_a_matched_phrase_never_reaches_the_log(logged, odd, heard, spoken,
                                                marker):
    secret = f"my salary is ninety thousand and I told {spoken} about it"
    _cleaner([(heard, "Someone Else")]).clean(secret)

    # Case-insensitively, because the leak was a lowercased form of the span:
    # U+0130 lowercases to i + a combining dot, so the escaped text no longer
    # matches the spoken text character for character while still being, word
    # for word, what the user said.
    written = "\n".join(r.getMessage() for r in logged.records).lower()
    assert marker not in written
    assert spoken.lower() not in written
    assert "salary" not in written
    assert odd not in written


def test_the_replacement_still_applies_to_the_odd_spelling(logged):
    # The pattern matched it, so the rule should fire — silently skipping the
    # replacement would trade a privacy bug for a correctness one.
    out = _cleaner([("sam altman", "Sam Altman")]).clean(
        f"I told {LONG_S}am altman about it")
    assert out == "I told Sam Altman about it"
    assert not [r for r in logged.records if r.levelno >= logging.WARNING]


def test_a_provider_that_raises_is_still_reported(logged):
    # The diagnostic that matters — "your dictionary is broken" — must survive
    # the hardening. Nothing here has seen the transcript.
    def boom():
        raise RuntimeError("history.db is locked")

    out = _cleaner(None).clean("unchanged")            # provider=None: no-op
    assert out == "unchanged"

    cleaner = TextCleaner(replacements_provider=boom, strip_fillers=False,
                          collapse_repeats=False, auto_capitalize=False,
                          strip_discourse_fillers=False,
                          fix_punctuation_spacing=False)
    assert cleaner.clean("my private words") == "my private words"
    written = "\n".join(r.getMessage() for r in logged.records)
    assert "history.db is locked" in written
    assert "my private words" not in written


def test_a_failure_inside_the_substitution_names_the_type_not_the_text(logged,
                                                                       monkeypatch):
    # Belt and braces for the whole class of bug: anything that can raise while
    # standing on the transcript is reported by exception TYPE only, because an
    # exception's own message can quote the text it choked on.
    def explode(matched, correct):
        raise ValueError(matched)

    monkeypatch.setattr("rekounts.text_cleaner._apply_case", explode)
    out = _cleaner([("sam altman", "Sam Altman")]).clean("I told sam altman")
    assert out == "I told sam altman"        # dictation survives untouched

    written = "\n".join(r.getMessage() for r in logged.records)
    assert "ValueError" in written
    assert "sam altman" not in written


# --- the structural fix ---------------------------------------------------
def test_the_matched_rule_is_identified_by_group_not_by_re_reading_the_text():
    # Root cause and fix in one assertion: the sub no longer needs to turn the
    # matched TEXT back into a dictionary key, so there is no key left to miss.
    pattern, lookup = build_replacements([("sam altman", "Sam Altman"),
                                          ("kubernetes", "Kubernetes")])
    match = pattern.search(f"I told {LONG_S}am altman about it")
    assert match.lastgroup in lookup
    assert lookup[match.lastgroup] == "Sam Altman"


def test_a_long_dictionary_still_compiles():
    # The fix gives every rule its own named group; a real dictionary can hold
    # hundreds of entries, so the group count must not be a limit.
    pairs = [(f"heard phrase {i}", f"Correct {i}") for i in range(400)]
    pattern, lookup = build_replacements(pairs)
    match = pattern.search("say heard phrase 399 now")
    assert lookup[match.lastgroup] == "Correct 399"


def test_a_repeated_entry_keeps_the_last_spelling_wins_rule():
    # Unchanged behaviour from the dict this replaced: a dictionary holding the
    # same misheard form twice uses the later correction.
    pattern, lookup = build_replacements([("sam", "Sam One"), ("SAM", "Sam Two")])
    match = pattern.search("hello sam")
    assert lookup[match.lastgroup] == "Sam Two"
