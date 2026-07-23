from rekounts.text_cleaner import TextCleaner


def test_strips_filler_words():
    c = TextCleaner(strip_fillers=True, auto_capitalize=False, fix_punctuation_spacing=False)
    assert c.clean("um so uh this is a test") == "so this is a test"


def test_filler_stripping_is_case_insensitive_and_word_bounded():
    c = TextCleaner(strip_fillers=True, auto_capitalize=False, fix_punctuation_spacing=False)
    # "drum" must NOT lose "um"; standalone "Um" is removed
    assert c.clean("Um the drum is loud") == "the drum is loud"


def test_auto_capitalize_first_letter_and_after_period():
    c = TextCleaner(strip_fillers=False, auto_capitalize=True, fix_punctuation_spacing=False)
    assert c.clean("hello world. how are you") == "Hello world. How are you"


def test_fix_punctuation_spacing():
    c = TextCleaner(strip_fillers=False, auto_capitalize=False, fix_punctuation_spacing=True)
    assert c.clean("hello ,world .yes") == "hello, world. yes"


def test_all_toggles_off_only_trims():
    c = TextCleaner(strip_fillers=False, auto_capitalize=False, fix_punctuation_spacing=False)
    assert c.clean("  spaced out  ") == "spaced out"


def test_empty_input_returns_empty():
    c = TextCleaner(strip_fillers=True, auto_capitalize=True, fix_punctuation_spacing=True)
    assert c.clean("   ") == ""


def _collapser():
    return TextCleaner(strip_fillers=False, auto_capitalize=False,
                       fix_punctuation_spacing=False, collapse_repeats=True)


def test_collapse_accidental_repeat():
    assert _collapser().clean("the the cat") == "the cat"


def test_collapse_repeat_is_case_insensitive():
    assert _collapser().clean("The the cat") == "The cat"


def test_collapse_three_in_a_row():
    assert _collapser().clean("I I I want it") == "I want it"


def test_keeps_intentional_doubles():
    # words that are legitimately repeated must survive
    assert _collapser().clean("it is very very good") == "it is very very good"
    assert _collapser().clean("no no don't") == "no no don't"


def test_collapse_respects_punctuation_boundary():
    # a word repeated across a sentence boundary is not an accidental stutter
    assert _collapser().clean("I like it. It is nice") == "I like it. It is nice"


def test_collapse_off_by_default_leaves_repeats():
    c = TextCleaner(strip_fillers=False, auto_capitalize=False, fix_punctuation_spacing=False)
    assert c.clean("the the cat") == "the the cat"


def test_own_capital_words_survive_auto_capitalize():
    # "iPhone"/"eBay" spell themselves; sentence position must not change them.
    c = TextCleaner(strip_fillers=False, auto_capitalize=True,
                    fix_punctuation_spacing=False)
    assert c.clean("iPhone sales rose. eBay fell.") == "iPhone sales rose. eBay fell."
    assert c.clean("hello there") == "Hello there"


# ---------------------------------------------------------------------------
# Fillers the way Whisper actually writes them - wrapped in punctuation. The
# stranded punctuation must leave with the filler, not stay behind orphaned.

def _full():
    return TextCleaner(strip_fillers=True, auto_capitalize=True,
                       fix_punctuation_spacing=True)


def test_sentence_initial_filler_takes_its_comma_along():
    assert _full().clean("Um, hello there.") == "Hello there."


def test_comma_wrapped_filler_leaves_a_single_comma():
    assert _full().clean("I think, um, we should go.") == "I think, we should go."


def test_filler_with_ellipsis_disappears_entirely():
    assert _full().clean("Uh... maybe not.") == "Maybe not."


def test_filler_ending_a_sentence_keeps_the_period():
    assert (_full().clean("I was thinking, um. Next thing.")
            == "I was thinking. Next thing.")


def test_filler_dangling_at_the_end_takes_its_comma_too():
    assert _full().clean("That's it, um") == "That's it"


def test_filler_after_a_sentence_break_recapitalizes_next_word():
    assert _full().clean("Something. Um, another thing.") == "Something. Another thing."


def test_hyphen_compounds_are_not_mangled():
    # "uh-huh" contains a filler but is a word of its own
    assert _full().clean("uh-huh sounds good") == "Uh-huh sounds good"


def test_doubled_filler_spellings_are_stripped():
    assert _full().clean("Umm, sure. Uhh, fine.") == "Sure. Fine."


def test_quoted_filler_is_someone_elses_word_and_stays():
    assert _full().clean("he said 'um' twice") == "He said 'um' twice"


# ---------------------------------------------------------------------------
# Phrase-level stutters: a restart re-speaks a short RUN of words, not just
# one ("I'm gonna I'm gonna"), and Whisper's segment seams duplicate runs too.

def test_collapses_repeated_two_word_phrase():
    assert _collapser().clean("I'm gonna I'm gonna do it") == "I'm gonna do it"


def test_collapses_phrase_repeat_with_comma_between():
    # Whisper often writes the restart pause as a comma
    assert _collapser().clean("I'm gonna, I'm gonna do it") == "I'm gonna do it"


def test_collapses_segment_seam_duplicate_case_insensitively():
    # the reported real-transcript artifact: the phrase restarts recapitalized
    assert (_collapser().clean("and at the At the same time it works")
            == "and at the same time it works")


def test_collapses_three_word_phrase():
    assert _collapser().clean("I want to I want to go") == "I want to go"


def test_collapses_chained_phrase_repeats():
    assert _collapser().clean("that was that was that was nice") == "that was nice"


def test_phrase_repeat_keeps_dropped_copys_separator():
    assert _collapser().clean("I'm gonna I'm gonna, do it") == "I'm gonna, do it"


def test_phrase_repeat_across_sentence_boundary_stays():
    assert _collapser().clean("That's it. That's it") == "That's it. That's it"


def test_emphatic_repeats_of_intentional_doubles_stay():
    assert _collapser().clean("no no no no way") == "no no no no way"


def test_sentence_final_filler_keeps_the_sentence_period():
    c = TextCleaner()
    assert c.clean("So we did it um. Next thing.") == "So we did it. Next thing."
    assert c.clean("We tried uh. It failed.") == "We tried. It failed."


def test_sentence_initial_filler_after_a_boundary_still_vanishes():
    c = TextCleaner()
    assert c.clean("Did it work? Um. Yes.") == "Did it work? Yes."
