import logging
import re

log = logging.getLogger(__name__)

FILLERS = {"um", "umm", "uh", "uhh", "erm", "ah", "hmm"}

# Hedge phrases that are fillers only when punctuation marks them as asides
# (", you know,"). Every one also has a literal meaning ("I like it", "turn
# right", "I mean it"), so - unlike FILLERS - these are removed ONLY when
# delimited on both sides. Whisper reliably comma-wraps the discourse use,
# which is what makes the delimited form safe to drop.
DISCOURSE_FILLERS = {"you know", "i mean", "like", "right"}

# Words that are commonly repeated on purpose - never collapse these.
INTENTIONAL_DOUBLES = {
    "very", "no", "so", "ha", "haha", "yeah", "really", "bye", "hey",
    "hi", "ok", "okay", "please", "now", "go", "run", "help", "yes",
}


def _phrase_alternation(phrases):
    """Longest-first regex alternation; spaces inside a phrase match any run
    of whitespace."""
    alts = sorted(phrases, key=len, reverse=True)
    return "|".join(r"\s+".join(map(re.escape, p.split())) for p in alts)


# An ellipsis marks a hesitation pause, not a sentence end ("uh... maybe").
_ELLIPSIS = re.compile(r"\.{2,}|…")

# A filler plus the punctuation stranded around it: lead is the separator it
# hides behind ("I think, um, ..."), trail is what it drags along ("Um, ..." /
# "Uh..."). Removing only the word - the old behavior - orphans both
# (", hello there." / "I think, , we"). The \w guards keep word-internal hits
# ("drum") and hyphen/apostrophe compounds ("uh-huh") intact.
_FILLER_RX = re.compile(
    r"(?P<lead>[,;:]\s*)?"
    r"(?<![\w'-])"
    r"(?:" + _phrase_alternation(FILLERS) + r")"
    r"(?P<trail>\s*[.,!?;:…]+)?"
    r"(?![\w'-])",
    re.IGNORECASE,
)

# Discourse fillers additionally REQUIRE delimiters: sentence start or [,;:]
# on the left, comma / period / end of text on the right. "?" and "!" on the
# right are deliberately not enough - "it works, right?" is a real question
# and stays whole.
_DISCOURSE_RX = re.compile(
    r"(?:(?P<lead>[,;:]\s*)|(?P<bos>^\s*|(?<=[.!?])\s+))"
    r"(?<![\w'-])(?:" + _phrase_alternation(DISCOURSE_FILLERS) + r")(?![\w'-])"
    r"(?P<trail>\s*[,.]+|\s*$)",
    re.IGNORECASE,
)


def _drop_filler(m):
    """Decide what a removed filler leaves behind.

    ", um," keeps the lead comma; ", um." keeps the sentence's own period
    (the comma yields to it); a filler opening a sentence ("Um, hello")
    vanishes with its whole trail so the real first word takes sentence
    position; one dangling at the very end ("...that's it, um") takes its
    lead comma with it. A mid-sentence filler that carries the sentence's
    period ("did it um. Next") hands the period back instead of swallowing
    the boundary with it.
    """
    lead = m.group("lead") or ""
    trail = m.group("trail") or ""
    hard = [c for c in _ELLIPSIS.sub("", trail) if c in ".!?"]
    if lead:
        if hard:
            return hard[-1]
        if not m.string[m.end():].strip():
            return ""
        return lead
    before = m.string[:m.start()].rstrip()
    if hard and before and before[-1] not in ".!?…":
        return hard[-1]
    return m.groupdict().get("bos") or ""


_SEP = ".,!?;:"


def _trailing_sep(token: str) -> str:
    return token[len(token.rstrip(_SEP)):]


def _repeat_length(out, tokens, i):
    """Length (3, 2 or 1) of the phrase ending at out[-1] that repeats,
    normalized, at tokens[i:] - or 0 when nothing repeats there."""
    def norm(t):
        return t.lower().strip(_SEP)

    for n in (3, 2, 1):
        if len(out) < n or i + n > len(tokens):
            continue
        prev, nxt = out[-n:], tokens[i:i + n]
        pn = [norm(t) for t in prev]
        if pn != [norm(t) for t in nxt]:
            continue
        if not all(pn):
            continue                    # punctuation-only tokens
        # A sentence end in the first copy is a real boundary ("It. It"); one
        # inside the second copy (before its last token) means the "repeat"
        # spans two sentences - both stay.
        if any(t[-1] in ".!?" for t in prev):
            continue
        if any(t[-1] in ".!?" for t in nxt[:-1]):
            continue
        # Emphatic repeats ("no no", "very very very") are deliberate.
        if all(w in INTENTIONAL_DOUBLES for w in pn):
            continue
        return n
    return 0


# Prefix for the per-rule group names build_replacements emits. Must be a valid
# Python identifier start, and must not collide with anything a user could put
# in the dictionary — group names come from this counter, never from their text.
_GROUP = "rk"


def build_replacements(pairs):
    """Compile (sounds_like, correct_word) pairs into one alternation regex.

    Returns ``(pattern, lookup)`` where lookup is keyed by GROUP NAME, so the
    caller reads the answer off the match object rather than turning the matched
    text back into a dictionary key.

    That indirection is the point. Keying by ``matched.lower()`` looked
    equivalent and was not: ``re.IGNORECASE`` uses Unicode simple case folding,
    whose equivalence classes are wider than ``str.lower()``. Three BMP
    characters — U+017F LONG S, U+0130 CAPITAL I WITH DOT ABOVE, U+0131 DOTLESS
    I — match a plain s/i under IGNORECASE but do not lower() to one, so a rule
    for "sam altman" could match "ſam altman" and then miss its own key. The
    KeyError that followed carried the matched span, which is a fragment of the
    user's dictation, into a log file that promises never to hold one. Naming
    the alternatives removes the lookup, and with it the whole failure mode.

    One combined pattern means a single left-to-right pass, so a replacement can
    never be re-matched by a later rule (a -> b, b -> c must not yield c).
    Longest phrase first so "cooper netties" wins over a "netties" rule.
    Word boundaries use lookarounds rather than \\b so multi-word phrases whose
    edges aren't word characters still anchor correctly.
    """
    # Deduplicated first, keyed the way the old lookup was: a dictionary holding
    # the same misheard form twice keeps the later correction, and only one
    # alternative is emitted for it.
    cleaned = {}
    for heard, correct in pairs or ():
        if not isinstance(heard, str) or not isinstance(correct, str):
            continue
        heard = " ".join(heard.split())
        correct = correct.strip()
        if heard and correct:
            cleaned[heard.lower()] = (heard, correct)
    if not cleaned:
        return None, {}
    entries = sorted(cleaned.values(), key=lambda p: len(p[0]), reverse=True)
    # Whitespace inside a phrase matches any run of whitespace, so "sounds like"
    # still matches a transcript that came out as "sounds  like".
    alts = [f"(?P<{_GROUP}{i}>" + r"\s+".join(re.escape(w) for w in heard.split()) + ")"
            for i, (heard, _) in enumerate(entries)]
    pattern = re.compile(r"(?<!\w)(?:" + "|".join(alts) + r")(?!\w)", re.IGNORECASE)
    lookup = {f"{_GROUP}{i}": correct for i, (_, correct) in enumerate(entries)}
    return pattern, lookup


# A word that starts lowercase but carries a capital of its own: "iPhone",
# "eBay", "npmRun". That spelling is deliberate, so sentence-start
# capitalization must leave it alone rather than produce "IPhone".
_OWN_CAPITAL = re.compile(r"^[a-z]\w*[A-Z]")


def _cap_word(word: str) -> str:
    if _OWN_CAPITAL.match(word):
        return word
    return word[:1].upper() + word[1:]


def _apply_case(matched: str, correct: str) -> str:
    """Keep a sentence-initial capital when the stored word is plain lowercase.

    If the user typed any capital themselves ("iPhone", "Rekounts") that IS
    the spelling they asked for, so it's used verbatim - force-capitalizing it
    would produce "IPhone".
    """
    if correct.islower() and matched[:1].isupper():
        return correct[:1].upper() + correct[1:]
    return correct


class TextCleaner:
    def __init__(self, strip_fillers=True, auto_capitalize=True, fix_punctuation_spacing=True,
                 collapse_repeats=False, strip_discourse_fillers=False,
                 replacements_provider=None):
        self.strip_fillers = strip_fillers
        self.auto_capitalize = auto_capitalize
        self.fix_punctuation_spacing = fix_punctuation_spacing
        self.collapse_repeats = collapse_repeats
        self.strip_discourse_fillers = strip_discourse_fillers
        # Callable -> list[tuple[sounds_like, correct_word]] from the dictionary.
        # Read fresh on every clean() so a word added in the dashboard applies to
        # the very next dictation. Default None = no replacements at all.
        self.replacements_provider = replacements_provider

    def clean(self, text: str) -> str:
        text = (text or "").strip()
        if not text:
            return ""
        # First, before anything else touches the words: a misheard form may
        # itself contain a filler ("uh mazon") or a stutter, and stripping those
        # first would leave nothing for the rule to match.
        text = self._apply_replacements(text)
        if self.strip_fillers:
            text = self._strip_fillers(text)
        # Collapse before the discourse pass: "you know, you know, fine"
        # first loses the stutter, then the surviving ", you know," marker.
        if self.collapse_repeats:
            text = self._collapse_repeats(text)
        if self.strip_discourse_fillers:
            text = self._strip_discourse(text)
        if self.fix_punctuation_spacing:
            text = self._fix_spacing(text)
        if self.auto_capitalize:
            text = self._capitalize(text)
        return text.strip()

    def _apply_replacements(self, text: str) -> str:
        """Swap each dictionary word's misheard form for its correct spelling.
        Never raises: a broken provider must not cost the user their dictation.

        Split into two guarded steps because they can say different amounts. The
        first has not seen the transcript — a provider that cannot read the
        dictionary, or a pattern that will not compile, is a real problem worth
        naming in full. The second is standing on the user's words, so it
        reports the exception TYPE and nothing else: an exception's message is
        written by whatever raised it and can quote the text it choked on, which
        is exactly how a KeyError used to put a phrase from a dictation into a
        log file that promises never to hold one. build_replacements no longer
        has a lookup that can miss, so this is the belt to that fix's braces —
        it closes the whole class rather than the one instance.
        """
        provider = self.replacements_provider
        if provider is None:
            return text
        try:
            pattern, lookup = build_replacements(provider())
        except Exception as e:
            log.warning("dictionary replacements unavailable (ignored): %s", e)
            return text
        if pattern is None:
            return text
        try:
            return pattern.sub(
                lambda m: _apply_case(m.group(0), lookup[m.lastgroup]), text)
        except Exception as e:
            log.warning("dictionary replacements failed (ignored): %s",
                        type(e).__name__)
            return text

    def _collapse_repeats(self, text: str) -> str:
        """Collapse an immediately-repeated word or short phrase (1-3 words,
        case-insensitive): the restart stutter "I'm gonna I'm gonna do it"
        and Whisper's segment-seam duplicates ("...and at the At the same
        time..."). Intentional doubles ("very very") and repeats across a
        sentence boundary survive."""
        tokens = text.split()
        out = []
        i = 0
        while i < len(tokens):
            n = _repeat_length(out, tokens, i)
            if n:
                # Keep the FIRST copy (it owns the sentence-start capital) but
                # give it the dropped copy's trailing separator - that is the
                # one that connects to what follows: "gonna, gonna do" ->
                # "gonna do", "gonna gonna, do" -> "gonna, do".
                out[-1] = out[-1].rstrip(",;:") + _trailing_sep(tokens[i + n - 1])
                i += n
            else:
                out.append(tokens[i])
                i += 1
        return " ".join(out)

    def _strip_fillers(self, text: str) -> str:
        out = _FILLER_RX.sub(_drop_filler, text)
        return re.sub(r"\s{2,}", " ", out).strip()

    def _strip_discourse(self, text: str) -> str:
        out = _DISCOURSE_RX.sub(_drop_filler, text)
        out = re.sub(r"\s{2,}", " ", out).strip()
        # A hedge that IS the whole utterance ("Right.") is a real answer,
        # not an aside - deleting it would insert nothing with no feedback.
        if not out:
            return text
        return out

    def _fix_spacing(self, text: str) -> str:
        # remove space before , . ! ? ; :
        text = re.sub(r"\s+([,.!?;:])", r"\1", text)
        # ensure one space after , . ! ? ; : when followed by a non-space char
        text = re.sub(r"([,.!?;:])(?=\S)", r"\1 ", text)
        return re.sub(r"\s{2,}", " ", text).strip()

    def _capitalize(self, text: str) -> str:
        # capitalize the first word and any word following . ! ?
        def cap(m):
            return m.group(1) + _cap_word(m.group(2))
        text = re.sub(r"^(\s*)([a-z]\w*)", cap, text)
        text = re.sub(r"([.!?]\s+)([a-z]\w*)", cap, text)
        return text
