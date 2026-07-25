"""Phantom YouTube outros: the composite-phrase family and the per-segment
tail strip.

The no_speech_prob values used here are REAL, measured with the shipped model
(small, int8, CPU) over real audio — see the PR for the full table:

    genuine speech                              0.0009 - 0.0794
    genuine "Thanks for watching, talk soon."   0.0058
    genuine dictation of the FULL outro         0.0057
    phantom "You" after 30 s of trailing dead air  0.8681
    phantom on silence-only / noise-only clips  0.9435 / 0.9939
"""
import threading

import numpy as np
import pytest

from rekounts.transcriber import (
    PHANTOM_NO_SPEECH_THRESHOLD,
    Transcriber,
    Transcript,
    is_hallucination,
    is_phantom_evidence,
    segments_no_speech_prob,
    strip_phantom_tail,
)

# Measured values, used throughout so the intent of each test is readable.
GENUINE_PROB = 0.0057    # genuine speech, incl. a real dictated outro
PHANTOM_PROB = 0.87      # phantom tail after 30 s of dead air

# ---------------------------------------------------------------------------
# 1. The composite phrase family (hole 1: the frozenset was exact-match only)
# ---------------------------------------------------------------------------

# The exact sentence that reached Ryan's transcript on 2026-07-25.
OWNERS_PHANTOM = ("Thank you so much for watching this video, I hope you "
                  "enjoyed it, see you in the next one.")

PHANTOM_TEXTS = [
    OWNERS_PHANTOM,
    "thank you so much for watching",
    "Thanks for watching",
    "Thank you.",
    "Thanks for watching!",
    "Thank you for watching this video.",
    "Thanks for watching, don't forget to subscribe!",
    "Thank you for watching, please like and subscribe.",
    "Thanks for watching everyone, see you in the next video!",
    "I hope you enjoyed this video, see you next time.",
    "Thank you so much for watching, I hope you enjoyed it.",
    "Thanks for watching and I'll see you in the next one.",
    "So, thank you for watching.",
    "And that's all for today. Thanks for watching, see you next time.",
    "That's it for today, thanks for watching!",
    "Please subscribe to my channel.",
    "Don't forget to like and subscribe!",
    "Like and subscribe.",
    "See you in the next one.",
    "And I'll see you in the next one.",
    "Until next time.",
    "Bye bye.",
    "You",
    "♪ Thank you ♪",
    "Subtitles by the Amara.org community",
    "Transcription by CastingWords",
    "Subs by www.zeoranger.co.uk",
    "[Music]",
    "[Applause]",
    "Thank you very much.",
    "thanks a lot",
]

# Genuine dictation that LOOKS like a hallucination. Losing any of these is
# worse than letting a phantom through: the user may not notice for hours.
GENUINE_TEXTS = [
    # a real sign-off that merely starts like the phantom
    "thanks for watching, talk soon",
    "Thanks for watching, talk soon.",
    # someone dictating an actual YouTube script - must survive verbatim
    "And that is everything for today. " + OWNERS_PHANTOM,
    "Okay here is the outro: thanks for watching, see you next time.",
    # ordinary gratitude
    "Thank you for the report you sent me.",
    "Thank you very much for the report.",
    "Thanks for watching the kids on Saturday, it really helped.",
    "Thank you so much for watching my dog while I was away.",
    "Thanks for watching my presentation, your feedback was useful.",
    "Thank you for watching over the deployment last night.",
    "Thanks, I'll take a look at it tomorrow.",
    "Thanks for everything you did this week.",
    # "subscribe" in a real sentence
    "Please subscribe to the newsletter and let me know what you think.",
    "I need to subscribe to the pro plan before Friday.",
    "Don't forget to subscribe to the calendar feed I sent you.",
    "Can you like and subscribe to the channel we set up for the team?",
    "Like and subscribe are the two metrics the client cares about.",
    # sign-offs that are NOT caption boilerplate
    "See you soon.",
    "See you later.",
    "See you tomorrow at the standup.",
    "See you next week.",
    "Bye for now, I'll call you when I land.",
    "I hope you enjoyed the trip, tell me all about it.",
    "I hope you enjoyed it, let me know if you want to go again.",
    # "and" is a clause separator - it must not eat real text
    "Thanks for watching and let me know what you think.",
    "Thank you for watching the demo and sending over your notes.",
    "Thanks and please send me the invoice when you get a chance.",
    "Subscribe and unsubscribe links are both broken on the site.",
    "See you in the next sprint and bring the roadmap.",
    "Turn on subtitles and check the timing against the audio.",
    "Bye and good luck with the interview.",
    "Thank you and goodbye were the only words I could make out.",
    "I hope you enjoyed it and I hope the weather held up.",
    # ordinary work dictation
    "Let's schedule the meeting for Tuesday.",
    "Bye week is next week for the team.",
    "Okay so the plan for tomorrow is to finish the migration script.",
    "You should probably check the logs first.",
    "You know, I think we should ship it.",
    "Music is playing in the background of the recording.",
]


@pytest.mark.parametrize("text", PHANTOM_TEXTS)
def test_phantom_family_is_dropped(text):
    assert is_hallucination(text) is True


@pytest.mark.parametrize("text", GENUINE_TEXTS)
def test_genuine_lookalike_is_kept(text):
    assert is_hallucination(text) is False


def test_the_exact_sentence_that_reached_the_users_transcript():
    """The regression this branch exists for: a composite outro that no single
    entry of the old frozenset could match."""
    assert is_hallucination(OWNERS_PHANTOM) is True


def test_one_ordinary_clause_protects_the_whole_transcript():
    """The guard that makes the family match safe - every clause must be
    phantom, so a single real clause anywhere keeps everything."""
    assert is_hallucination("Thanks for watching, talk soon.") is False
    assert is_hallucination("Thanks for watching. Call me back.") is False


# ---------------------------------------------------------------------------
# 2. The per-segment tail strip (hole 2: the filter only saw the whole clip)
# ---------------------------------------------------------------------------
class Seg:
    """Stands in for a faster-whisper Segment (a NamedTuple carrying
    no_speech_prob / avg_logprob / compression_ratio)."""

    def __init__(self, text, no_speech_prob=0.001):
        self.text = text
        self.no_speech_prob = no_speech_prob


def test_phantom_tail_is_stripped_from_genuine_speech():
    """Real measurement: speech1.wav + 30 s of dead air decoded to three
    segments, the last of which was a phantom "You" at no_speech_prob 0.8681."""
    segs = [
        Seg("Okay so the plan for tomorrow is to finish the migration script "
            "and then review the pull", 0.0009),
        Seg("request that Ryan opened this morning.", 0.0009),
        Seg("You", 0.8681),
    ]
    kept = strip_phantom_tail(segs)
    assert kept == [segs[0].text, segs[1].text]


def test_composite_outro_tail_is_stripped():
    segs = [
        Seg("I wanted to get your thoughts on the migration plan.", 0.002),
        Seg(OWNERS_PHANTOM, 0.87),
    ]
    assert strip_phantom_tail(segs) == [segs[0].text]


def test_several_phantom_tail_segments_are_all_stripped():
    segs = [
        Seg("Here is the summary you asked for.", 0.001),
        Seg("Thanks for watching.", 0.91),
        Seg("See you in the next one.", 0.88),
    ]
    assert strip_phantom_tail(segs) == [segs[0].text]


def test_genuine_outro_is_kept_because_the_decoder_heard_speech():
    """THE false-positive case, and the whole reason the statistical gate
    exists: the identical sentence, genuinely spoken, measured at 0.0057."""
    segs = [
        Seg("And that is everything for today.", 0.0057),
        Seg(OWNERS_PHANTOM, 0.0057),
    ]
    assert strip_phantom_tail(segs) == [segs[0].text, segs[1].text]


def test_high_no_speech_but_real_words_are_never_dropped():
    """Phrase family is required as well as the statistic - an unlucky
    no_speech_prob on real words must never cost the user those words."""
    segs = [
        Seg("Let's ship it on Friday.", 0.001),
        Seg("Remember to bring the laptop.", 0.99),
    ]
    assert strip_phantom_tail(segs) == [segs[0].text, segs[1].text]


def test_phantom_in_the_middle_is_left_alone():
    """Only a TAIL is considered: removing text from the middle of a dictation
    is the most damaging thing this could do, and a quiet passage mid-sentence
    is far more likely than a phantom."""
    segs = [
        Seg("First the good news.", 0.001),
        Seg("Thank you.", 0.95),
        Seg("The build is green again.", 0.001),
    ]
    assert strip_phantom_tail(segs) == [s.text for s in segs]


def test_borderline_no_speech_is_kept():
    segs = [Seg("Real words here.", 0.001),
            Seg("Thanks for watching.", PHANTOM_NO_SPEECH_THRESHOLD - 0.01)]
    assert strip_phantom_tail(segs) == [s.text for s in segs]


def test_segments_without_metadata_are_left_alone():
    """No evidence means no deletion - an older faster-whisper or a test double
    must never cause silent text loss."""
    class Bare:
        text = "Thanks for watching."

    assert strip_phantom_tail([Bare()]) == ["Thanks for watching."]


def test_whole_clip_phantom_strips_to_empty():
    """A clip that is nothing but a phantom collapses to "", which the
    controller already reports as "No speech detected"."""
    assert strip_phantom_tail([Seg("you", 0.9435)]) == []


# ---------------------------------------------------------------------------
# 3. The setting must genuinely turn all of it off
# ---------------------------------------------------------------------------
class FakeModel:
    def __init__(self, segments):
        self._segments = segments

    def transcribe(self, audio, **kwargs):
        return iter(self._segments), None


def make_transcriber(segments, filter_provider=None):
    t = object.__new__(Transcriber)
    t.language = "en"
    t.beam_size = 5
    t.hotwords_provider = None
    t.device = "cpu"
    t._lock = threading.Lock()
    t.model = FakeModel(segments)
    if filter_provider is not None:
        t.filter_provider = filter_provider
    return t


AUDIO = np.zeros(16000, dtype="float32")

TAIL_SEGMENTS = [Seg("Here is the real dictation.", 0.001),
                 Seg("Thanks for watching.", 0.93)]


def test_transcribe_strips_the_tail_by_default():
    t = make_transcriber(TAIL_SEGMENTS)
    assert t.transcribe(AUDIO) == "Here is the real dictation."


def test_setting_off_keeps_everything():
    t = make_transcriber(TAIL_SEGMENTS, filter_provider=lambda: False)
    assert t.transcribe(AUDIO) == "Here is the real dictation. Thanks for watching."


def test_setting_on_via_provider_strips():
    t = make_transcriber(TAIL_SEGMENTS, filter_provider=lambda: True)
    assert t.transcribe(AUDIO) == "Here is the real dictation."


def test_broken_provider_falls_back_to_filtering():
    def boom():
        raise RuntimeError("config went away")

    t = make_transcriber(TAIL_SEGMENTS, filter_provider=boom)
    assert t.transcribe(AUDIO) == "Here is the real dictation."


# ---------------------------------------------------------------------------
# 4. Text alone must NEVER delete anything
#
# The predicate above is broad on purpose, and broad is only safe because every
# caller pairs it with evidence. These tests are the ones that keep it that way.
# ---------------------------------------------------------------------------
def test_no_evidence_is_not_evidence():
    assert is_phantom_evidence(None) is False
    assert is_phantom_evidence(0.0) is False
    assert is_phantom_evidence(GENUINE_PROB) is False
    assert is_phantom_evidence(PHANTOM_NO_SPEECH_THRESHOLD) is True
    assert is_phantom_evidence(PHANTOM_PROB) is True


def test_whole_clip_probability_is_the_minimum_across_segments():
    """One confident segment protects the whole transcript: the question a
    whole-clip filter asks is "did ANY of this contain speech?"."""
    assert segments_no_speech_prob([Seg("a", 0.9), Seg("b", 0.004)]) == 0.004
    assert segments_no_speech_prob([]) is None

    class Bare:
        text = "no metadata"

    assert segments_no_speech_prob([Bare()]) is None


def test_transcribe_reports_the_evidence_for_what_survived():
    t = make_transcriber(TAIL_SEGMENTS)
    out = t.transcribe(AUDIO)
    assert isinstance(out, Transcript)
    # the 0.93 tail was stripped, so the evidence describes the kept speech
    assert out.no_speech_prob == 0.001


def test_transcript_is_still_an_ordinary_string():
    """Every existing caller and test double must keep working untouched."""
    tr = Transcript("hello world", 0.5)
    assert tr == "hello world"
    assert isinstance(tr, str)
    assert tr.upper() == "HELLO WORLD"
    assert tr.split() == ["hello", "world"]
    assert Transcript("x").no_speech_prob is None


def test_splitting_can_manufacture_a_phantom_and_that_is_why_evidence_gates_it():
    """An earlier version of the comment on _CLAUSE_SPLIT claimed splitting
    "can only ever protect genuine text". That is FALSE, and this test pins the
    counter-example so nobody relies on the claim again: a genuine composite
    decomposes into two boilerplate halves.

    "Thank you and goodbye." is a real thing to dictate. The text predicate
    flags it; the evidence gate is the only reason it is never deleted."""
    assert is_hallucination("Thank you and goodbye.") is True   # text alone!
    # ...but with the probability genuine speech actually has, nothing goes:
    assert strip_phantom_tail([Seg("Thank you and goodbye.", GENUINE_PROB)]) \
        == ["Thank you and goodbye."]


@pytest.mark.parametrize("text", [
    "Ok thanks", "Thanks, bye.", "Thanks!", "Thanks.", "Bye.", "Thank you.",
    "Thank you very much.", "You", "Thanks a lot.", "Thanks for listening.",
    "That's it for today.", "Thank you and goodbye.", "Please subscribe.",
    "Like and subscribe.", "See you in the next one.", "Until next time.",
    "I hope you enjoyed it.", "Thanks for watching.", "Okay, thanks.",
    OWNERS_PHANTOM,
])
def test_short_genuine_dictation_survives_the_tail_strip(text):
    """Short single-clause dictations have no ordinary clause to protect them,
    so the evidence gate is all that stands between the user and silent data
    loss. Every one of these was deleted by the first cut of this branch."""
    assert strip_phantom_tail([Seg(text, GENUINE_PROB)]) == [text]


@pytest.mark.parametrize("text", [
    "Okay.", "Ok", "So", "Well", "Alright", "Now", "Oh",
])
def test_a_bare_filler_is_real_dictation_not_a_phantom(text):
    assert is_hallucination(text) is False


def test_filler_still_does_not_rescue_a_real_phantom():
    assert is_hallucination("So, thank you for watching.") is True
    assert is_hallucination("Okay, thanks for watching, see you next time.") is True


@pytest.mark.parametrize("text", [
    "Captions by Sarah.",
    "Translation by the marketing team.",
    "Subtitles by the editor.",
    "Transcription by the intern, due Friday.",
])
def test_credit_lines_by_a_real_person_are_not_caption_farms(text):
    """A "<credit word> by <anything>" wildcard deleted these. Only the three
    caption farms that actually appear in Whisper's output are matched now."""
    assert is_hallucination(text) is False


@pytest.mark.parametrize("text", [
    "Subtitles by the Amara.org community",
    "Transcription by CastingWords",
    "Subs by www.zeoranger.co.uk",
])
def test_the_real_caption_farms_are_still_matched(text):
    assert is_hallucination(text) is True


@pytest.mark.parametrize("text", [
    "Thank you for joining us.",
    "Thanks for joining us today.",
    "Thank you all for being here.",
])
def test_meeting_language_is_not_caption_boilerplate(text):
    assert is_hallucination(text) is False
