def _words(s: str):
    return s.split()


def new_suffix(already_typed: str, new_transcript: str) -> str:
    """Return the words in new_transcript after the longest common word-prefix
    shared with already_typed. Forward-only (never rewrites already_typed)."""
    typed = _words(already_typed)
    trans = _words(new_transcript)
    i = 0
    while i < len(typed) and i < len(trans) and typed[i] == trans[i]:
        i += 1
    return " ".join(trans[i:])


class LiveTyper:
    """Stateful helper for chunk-append live typing.

    Whisper re-transcribes the whole growing audio buffer each tick and may
    revise earlier words. Diffing each new transcript against an accumulated
    "already typed" string caused runaway doubling once a word was revised.

    LiveTyper instead tracks how many WORDS it has already emitted and only ever
    emits words beyond that index. A word is typed exactly once; revisions to
    already-emitted words are ignored (we keep the earlier guess — the safe,
    never-delete tradeoff). This eliminates doubling and mid-sentence stalls.
    """

    def __init__(self):
        self._emitted = 0

    def feed(self, transcript: str) -> str:
        """Consume the latest full transcript; return only the newly-settled
        words to type now (empty string if nothing new)."""
        words = _words(transcript)
        if len(words) <= self._emitted:
            return ""              # no growth (or transcript shrank) -> emit nothing
        new_words = words[self._emitted:]
        self._emitted = len(words)
        return " ".join(new_words)

    def final_tail(self, final_transcript: str) -> str:
        """On release: return the remainder of the final transcript that hasn't
        been emitted yet (the end of the sentence the last chunk missed)."""
        words = _words(final_transcript)
        if len(words) <= self._emitted:
            return ""
        tail = " ".join(words[self._emitted:])
        self._emitted = len(words)
        return tail
