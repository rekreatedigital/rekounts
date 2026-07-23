from rekounts.text_stream import LiveTyper


def run(raws):
    """Feed a sequence of growing transcripts to a fresh LiveTyper; return the
    concatenation of everything it emitted (i.e. what lands in the document)."""
    lt = LiveTyper()
    parts = []
    for raw in raws:
        emitted = lt.feed(raw)
        if emitted:
            parts.append(emitted)
    return " ".join(parts)


def test_normal_growth_emits_each_word_once():
    assert run(["the quick", "the quick brown", "the quick brown fox"]) == "the quick brown fox"


def test_repeated_transcript_emits_nothing_extra():
    # a stalled/identical transcript must not re-type words (no doubling)
    assert run(["hello world", "hello world", "hello world how"]) == "hello world how"


def test_revision_of_earlier_word_does_not_double():
    # Whisper revises "to" -> "two"; we keep the earlier guess but never double.
    assert run(["I want to", "I want to buy", "I want two apples and"]) \
        == "I want to buy and"


def test_first_feed_emits_all_words():
    lt = LiveTyper()
    assert lt.feed("hello there friend") == "hello there friend"


def test_shorter_transcript_emits_nothing():
    lt = LiveTyper()
    lt.feed("one two three four")
    assert lt.feed("one two") == ""   # transcript shrank; never un-type


def test_final_tail_returns_untyped_remainder():
    lt = LiveTyper()
    lt.feed("hello world")
    # release pass: full transcript is longer; only the remainder is returned
    assert lt.final_tail("hello world how are you") == "how are you"


def test_final_tail_when_nothing_streamed():
    lt = LiveTyper()
    assert lt.final_tail("hello world") == "hello world"


def test_final_tail_no_new_words_returns_empty():
    lt = LiveTyper()
    lt.feed("hello world done")
    assert lt.final_tail("hello world done") == ""
