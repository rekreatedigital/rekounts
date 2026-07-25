import logging
import os
import re
import subprocess
import sys
import threading

import numpy as np

log = logging.getLogger(__name__)

# Phrases Whisper commonly hallucinates from silence, breath or background noise.
# Kept lowercased and punctuation-stripped; compared against the WHOLE result so
# a genuine "thank you very much for the report" is never dropped - only a clip
# whose entire content is one of these phantoms. Sourced from the well-known
# Whisper hallucination set (YouTube-caption artefacts the model was trained on).
HALLUCINATION_PHRASES = frozenset({
    "thank you",
    "thank you.",
    "thanks",
    "thank you very much",
    "thank you for watching",
    "thanks for watching",
    "thank you for watching!",
    "thanks for watching!",
    "thank you so much for watching",
    "please subscribe",
    "like and subscribe",
    "please like and subscribe",
    "don't forget to subscribe",
    "see you next time",
    "see you in the next video",
    "bye",
    "bye bye",
    "you",
    "subtitles by the amara.org community",
    "subs by www.zeoranger.co.uk",
    "transcription by castingwords",
})

_STRIP_EDGE = re.compile(r"^[^\w]+|[^\w]+$")

# ------------------------------------------------------------ phantom family
# The fixed list above cannot win on its own: real hallucinations are COMPOSITE
# and endlessly recombined ("Thank you so much for watching this video, I hope
# you enjoyed it, see you in the next one." is three separate caption clauses
# glued together, and no one of them is in the list as written). Growing the
# list is a losing race, so we match the FAMILY instead: split the transcript
# into clauses and ask whether every clause is a known caption-outro clause.
#
# "Every clause" is the guard that makes this safe. A user who says "thanks for
# watching, talk soon" keeps it, because "talk soon" is not a caption clause -
# one ordinary clause anywhere in the text is enough to protect the whole thing.
# Clause patterns are matched with fullmatch, so "thank you very much for the
# report" is not a match for "thank you very much".
# Sentence punctuation only splits when followed by space or end-of-string, so
# "amara.org" and "www.zeoranger.co.uk" survive as one clause. " and " splits
# too: the outros are strung together with it as often as with a comma
# ("Thanks for watching and I'll see you in the next one."), and since EVERY
# clause must be phantom, splitting more can only ever protect genuine text.
_CLAUSE_SPLIT = re.compile(
    r"\s*(?:,|[.!?;:…]+(?=\s|$)|\s+and\s+|\s+-+\s+)\s*")

# Discourse openers Whisper likes to prepend; they carry no meaning of their own
# and must not rescue a clause that is otherwise pure caption boilerplate.
_FILLERS = r"(and|so|but|well|ok|okay|alright|all right|now|oh|um|uh)"
_LEADING_FILLER = re.compile(rf"^{_FILLERS}\s+")
_FILLER_ONLY = re.compile(rf"{_FILLERS}")

_THANKS = r"(thank you|thank u|thanks|thankyou)"
# "so much", "very much", "a lot", "again", "all", "everyone", "guys" - any run.
_INTENSIFIER = r"(\s+(so much|very much|a lot|again|all|everyone|guys|folks))*"

_PHANTOM_CLAUSE_PATTERNS = tuple(re.compile(p) for p in (
    # bare thanks - the classic silence artefact
    rf"{_THANKS}{_INTENSIFIER}",
    # thanks for watching / listening / joining, with any caption trimmings
    rf"{_THANKS}{_INTENSIFIER}\s+for\s+"
    r"(watching|listening|joining us|joining|tuning in|watching this|being here)"
    r"(\s+(this|the|my|our))?(\s+(video|one|episode|stream|tutorial|channel))?"
    r"(\s+(everyone|guys|all|you all|folks|today))?",
    # hope you enjoyed it
    r"(i|we)('?ll|'?ve)?\s+(really\s+)?hope\s+(you|u)\s+"
    r"(enjoyed|enjoy|liked|like|found)"
    r"(\s+(it|this|that|the video|this video|my video|it helpful|it useful))?",
    r"(i|we)\s+hope\s+(you|u)\s+found\s+(this|it)"
    r"(\s+(video|one))?(\s+(helpful|useful|informative|interesting))?",
    # see you in the next one - deliberately NOT "see you soon"/"see you later",
    # which are ordinary things to dictate at the end of a real message.
    r"((i|we)('?ll)?\s+)?(see|catch)\s+(you|ya|u)(\s+(all|guys))?"
    r"(\s+in)?(\s+the)?\s+next\s+(one|time|video|episode|week's video)",
    r"((i|we)('?ll)?\s+)?see\s+(you|ya|u)\s+next\s+time",
    r"until\s+next\s+time",
    # like and subscribe
    r"((please|don'?t forget to|do not forget to|remember to|make sure to|"
    r"be sure to|and)\s+)*"
    r"((like|comment|share|smash the like button|hit the like button)"
    r"(\s*(,|and|&)\s*)?)*"
    r"subscribe(\s+to\s+(my|the|our)\s+channel)?"
    r"(\s+for\s+more(\s+(videos|content))?)?",
    r"((please|don'?t forget to|do not forget to|remember to|make sure to|"
    r"be sure to)\s+)*(like|hit the like button|smash the like button)"
    r"(\s+and\s+(subscribe|share))?",
    r"(don'?t forget to\s+|please\s+)?(hit|ring|smash)\s+the\s+bell"
    r"(\s+icon)?(\s+for\s+notifications)?",
    # sign-offs
    r"(bye|bye bye|goodbye|good bye|bye for now|see ya)",
    r"(that'?s|that is)\s+(it|all)\s+for\s+"
    r"(today|now|this video|this one|this week)",
    # caption-track credits baked into the training data
    r"(subtitles|subs|subtitling|captions|transcription|translation)"
    r"(\s+and\s+translation)?\s+(by|provided by)\s+.{0,60}",
    # bare halves left over when a credit line is split on " and "
    r"(subtitles|subs|subtitling|captions)",
    r".{0,40}\b(amara\.org|zeoranger|castingwords)\b.{0,40}",
    # bracketed non-speech events (the brackets are stripped before we get here)
    r"(music|applause|laughter|silence|blank_?audio|inaudible|"
    r"foreign|no audio|background noise)",
    # the single most common silence token of all
    r"(you|thank you\.?)",
))


def _clause_is_phantom(clause: str) -> bool:
    """True when one clause is caption-outro boilerplate and nothing else."""
    clause = _LEADING_FILLER.sub("", clause).strip()
    if not clause or _FILLER_ONLY.fullmatch(clause):
        return True   # punctuation or a bare "so": carries no user content
    if clause in HALLUCINATION_PHRASES:
        return True
    return any(p.fullmatch(clause) for p in _PHANTOM_CLAUSE_PATTERNS)


def _phantom_clauses(text: str):
    """Split into normalized clauses. Returns [] when there is nothing to judge."""
    norm = " ".join(_normalize_phrase(text).split())
    if not norm:
        return []
    out = []
    for part in _CLAUSE_SPLIT.split(norm):
        part = _normalize_phrase(part)
        part = " ".join(part.split())
        if part:
            out.append(part)
    return out

# ---------------------------------------------------------------- hotwording
# Dictionary words are fed to Whisper through faster-whisper's `hotwords`
# argument, which puts them in the decoder's "previous text" slot on EVERY
# 30-second window (initial_prompt only survives the first window once
# condition_on_previous_text=False, which is what we use). See the PR for the
# measurement behind that choice.
#
# The prompt is a header-style glossary line rather than a bare comma list:
# a bare list reads to the model like transcript content it should carry on
# writing, which is the classic way a prompt turns into a hallucination on a
# silent clip. "Glossary: a, b, c." reads as a preamble instead.
HOTWORD_PROMPT_TEMPLATE = "Glossary: {words}."
# Whisper truncates the prompt at half the context (223 tokens) anyway; capping
# on our side keeps the prompt short (long prompts dilute the bias) and keeps
# what we send deterministic instead of silently clipped mid-word.
MAX_HOTWORDS = 48
MAX_HOTWORD_CHARS = 320


def format_hotwords(words) -> str | None:
    """Build the biasing prompt from dictionary words, or None when there's
    nothing to bias with. None means "behave exactly as if the feature were
    absent" - it is the default value of faster-whisper's `hotwords` argument.

    Words are trimmed, de-duplicated case-insensitively (first spelling wins,
    since that's the spelling the user typed) and capped."""
    if not words:
        return None
    kept, seen, chars = [], set(), 0
    for raw in words:
        if not isinstance(raw, str):
            continue
        # Commas separate entries in the prompt, so a word can't contain one.
        word = " ".join(raw.replace(",", " ").split())
        if not word or word.lower() in seen:
            continue
        if len(kept) >= MAX_HOTWORDS or chars + len(word) > MAX_HOTWORD_CHARS:
            log.debug("hotword list capped at %d words", len(kept))
            break
        seen.add(word.lower())
        kept.append(word)
        chars += len(word) + 2  # ", "
    if not kept:
        return None
    return HOTWORD_PROMPT_TEMPLATE.format(words=", ".join(kept))


def _normalize_phrase(text: str) -> str:
    """Lowercase and strip leading/trailing punctuation/quotes/music glyphs so
    'Thank you.' , '♪ Thank you ♪' and 'thank you' all compare equal."""
    return _STRIP_EDGE.sub("", (text or "").strip().lower())


def is_hallucination(text: str) -> bool:
    """True when the ENTIRE transcript is caption-outro boilerplate and nothing
    else. Applied after transcription so a silent/noise clip that Whisper
    'hears' as 'Thank you.' is suppressed instead of inserted.

    Every clause must be phantom. That is what keeps a genuine sentence safe:
    one ordinary clause anywhere ("thanks for watching, talk soon") protects the
    whole transcript, and a phantom tail on real speech is deliberately NOT
    handled here - it has no text-only tell, and is caught per segment with the
    decoder's own no-speech evidence instead (see strip_phantom_tail)."""
    clauses = _phantom_clauses(text)
    if not clauses:
        return False  # empty is handled separately (no-speech notice)
    return all(_clause_is_phantom(c) for c in clauses)


# --------------------------------------------------------- phantom tail strip
# Whisper's own decoder tells us how confident it is that a window contained NO
# speech, and the app was throwing that away. Measured on this model (small,
# int8, CPU) over real audio - the numbers are in the PR:
#
#   genuine speech                              no_speech_prob 0.0009 - 0.0794
#   genuine "Thanks for watching, talk soon."   no_speech_prob 0.0058
#   genuine dictation of the FULL outro         no_speech_prob 0.0057
#   phantom "You" on 30 s of trailing silence   no_speech_prob 0.8681
#   phantom on silence / noise only             no_speech_prob 0.9435 / 0.9939
#
# Two orders of magnitude of daylight, and - crucially - the identical sentence
# spoken for real sits at 0.0057 while the hallucinated one sits at 0.87. That
# is the separation a text-only filter can never see, and it is what lets us
# strip a phantom tail off genuine speech without touching the speech.
#
# 0.6 is the same cut-off OpenAI's own implementation uses, and it sits an order
# of magnitude above every genuine reading measured here.
PHANTOM_NO_SPEECH_THRESHOLD = 0.6


def strip_phantom_tail(segments):
    """Drop trailing segments that are BOTH decoder-flagged as no-speech AND
    pure caption boilerplate. Returns the segment texts to keep.

    Both conditions are required, in that order of importance:

    * the statistical gate is what distinguishes a phantom from a user who
      really did dictate an outro (0.87 vs 0.0057 on the very same sentence);
    * the phrase-family gate is what keeps an unlucky no_speech_prob on real
      words from ever costing the user those words.

    Only a TAIL is considered. A high-no-speech segment in the middle of a
    dictation is far more likely to be a genuine quiet passage than a phantom,
    and removing text from the middle is the most damaging thing this could do.

    Segments without the metadata (older faster-whisper, or a test double) are
    left alone: no evidence means no deletion.
    """
    kept = list(segments)
    while kept:
        seg = kept[-1]
        prob = getattr(seg, "no_speech_prob", None)
        if prob is None or prob < PHANTOM_NO_SPEECH_THRESHOLD:
            break
        text = getattr(seg, "text", "") or ""
        if not is_hallucination(text):
            break
        log.info("dropping phantom tail segment (no_speech_prob=%.3f): %r",
                 prob, text.strip())
        kept.pop()
    return [getattr(s, "text", "") for s in kept]


# --------------------------------------------------------------- segment join
# Whisper punctuates each segment in isolation once condition_on_previous_text
# is off (a deliberate anti-repetition choice), so a pause mid-dictation can
# come back as ["so that's done", "Now the next part"] - which a bare-space
# join turns into one run-on sentence.

# The pronoun "I" is capitalized wherever it sits, so it carries no
# new-sentence signal.
_ALWAYS_CAPITALIZED = {"i", "i'm", "i'll", "i've", "i'd"}


def _needs_period(prev: str, nxt: str) -> bool:
    """True when a period is missing between two adjacent segment texts.

    Fires only when the left side ends unpunctuated AND the right side starts
    with a capital (Whisper's own new-sentence signal). Two exceptions keep it
    from over-firing: a right side starting with "I" proves nothing, and a
    right side that restarts the left side's last words ("...and at the" |
    "At the same time") is a stutter - the cleaner's repeat collapse handles
    that, and a period at the seam would hide it from the collapse."""
    if prev[-1] in ".!?,;:…\"')]":
        return False
    first = nxt.split()[0]
    if not first[0].isupper():
        return False
    if first.strip(".,!?;:").lower() in _ALWAYS_CAPITALIZED:
        return False
    pw = [w.strip(".,!?;:").lower() for w in prev.split()[-3:]]
    nw = [w.strip(".,!?;:").lower() for w in nxt.split()[:3]]
    for n in (3, 2, 1):
        if len(pw) >= n and len(nw) >= n and pw[-n:] == nw[:n]:
            return False
    return True


def join_segments(texts) -> str:
    """Join Whisper segment texts into one transcript, restoring the sentence
    break Whisper omits at some segment seams."""
    out = []
    for t in texts:
        t = (t or "").strip()
        if not t:
            continue
        if out and _needs_period(out[-1], t):
            out[-1] += "."
        out.append(t)
    return " ".join(out)


def _is_prompt_echo(text: str, prompt: str | None) -> bool:
    """True when the model just parroted the glossary prompt back at us.

    Priming the decoder makes this possible on a silent or noise-only clip.
    The check is deliberately exact-match-only: dictating a single dictionary
    word is a completely normal thing to do (it's how you test the feature),
    so only a transcript that IS the whole prompt is suppressed."""
    if not prompt or not text:
        return False
    return (_normalize_phrase(" ".join(text.split()))
            == _normalize_phrase(" ".join(prompt.split())))


# ------------------------------------------------------------- model aliases
# faster-whisper 1.0.3 ships a built-in name map (base/small/medium/large-v3/
# distil-large-v3/...) that it turns into Systran CT2 repos. It does NOT know
# "large-v3-turbo" — OpenAI's turbo model shipped after this release — so we map
# that friendly name onto a pinned community CT2 conversion. Every other name is
# passed through untouched, so faster-whisper's own resolution (and any raw HF
# repo id or local path a power user puts in config) keeps working.
#
# Pinned by repo id, not revision: the download is cached after first use and
# offline thereafter (see load_model_offline_first). Turbo is the top-quality
# option and is really only practical on GPU (int8_float16) on this class of
# hardware — see the Accuracy guide in the README.
_MODEL_ALIASES = {
    "large-v3-turbo": "deepdml/faster-whisper-large-v3-turbo-ct2",
    "turbo": "deepdml/faster-whisper-large-v3-turbo-ct2",
}


def resolve_model_id(model: str) -> str:
    """Translate a config/UI model name into what faster-whisper can load.

    Names faster-whisper already understands (base, small, medium,
    distil-large-v3, ...) pass straight through; only the handful it predates
    are remapped to a pinned CT2 repo. Unknown strings are returned unchanged so
    a raw HF repo id or local path still works.
    """
    return _MODEL_ALIASES.get((model or "").strip(), model)


def _register_cuda_dlls():
    """Add pip-installed NVIDIA CUDA runtime DLL directories to the search path
    so ctranslate2 can find cublas/cudnn/cudart when device='cuda'. No-op if the
    packages aren't installed (CPU-only setups). Safe to call always.

    Two Windows gotchas, both of which silently disabled GPU before:

    1. `nvidia` is a PEP 420 namespace package, so `nvidia.__file__` is None.
       The old `os.path.dirname(nvidia.__file__)` raised TypeError, which the
       broad except swallowed - so nothing was ever registered even when the
       CUDA wheels WERE installed. Use `__path__` instead.
    2. `os.add_dll_directory()` alone is not enough. ctranslate2 loads cuBLAS
       lazily via a plain LoadLibrary, and that search order does NOT include
       directories added with add_dll_directory (those need the
       LOAD_LIBRARY_SEARCH_USER_DIRS flag). Prepending to PATH is what actually
       makes "cublas64_12.dll is not found" go away. We do both: PATH for the
       lazy loads, add_dll_directory for anything linked the normal way.

    Note cublas64_12.dll itself depends on cudart64_12.dll, so the
    nvidia-cuda-runtime-cu12 wheel is required alongside cublas and cudnn.
    """
    try:
        import nvidia  # the nvidia-* cu12 packages create this namespace
        base = list(nvidia.__path__)[0]
    except Exception:
        return
    found = []
    for sub in ("cublas", "cudnn", "cuda_runtime", "cuda_nvrtc"):
        d = os.path.join(base, sub, "bin")
        if os.path.isdir(d):
            found.append(d)
            try:
                os.add_dll_directory(d)
            except Exception:
                pass
    if found:
        os.environ["PATH"] = os.pathsep.join(
            found + [os.environ.get("PATH", "")])


_register_cuda_dlls()


def load_model_offline_first(model_name, device, compute_type, loader=None):
    """Load a WhisperModel from local files ONLY — never the network.

    `model_name` is expected to be an absolute directory that
    rekounts.models.ensure_model has already populated with the CT2 files
    (config.json/model.bin/tokenizer.json/vocabulary.txt). Given a directory,
    faster-whisper uses it verbatim and never contacts huggingface.co; passing
    `local_files_only=True` is belt-and-suspenders so that even a bare model
    name could only ever resolve from an on-disk cache, not a download.

    There is deliberately NO downloading fallback here: model delivery is handled
    up front by rekounts.models (our own host + Hugging Face-cache migration),
    so no faster-whisper code path in the running app may reach the network. A
    failure here (e.g. a broken CUDA runtime) propagates to Transcriber.__init__,
    which retries on CPU — itself still offline.
    """
    if loader is None:
        from faster_whisper import WhisperModel
        loader = WhisperModel
    return loader(model_name, device=device, compute_type=compute_type,
                  local_files_only=True)


# Offline-only CUDA probe. `{name}` is the local model directory ensure_model
# already populated, so local_files_only=True always resolves and the probe
# never downloads. Crucially the probe doesn't stop at LOADING the model: a
# CUDA model can load on a GPU whose cuBLAS/cuDNN runtime is missing or
# mismatched, and the failure only surfaces on the first encode ("Library
# cublas64_12.dll is not found"). So the probe runs one tiny inference too -
# if that returns, CUDA can actually transcribe on this machine, not merely
# allocate.
_PROBE_CODE = """
import numpy as np
from faster_whisper import WhisperModel
m = WhisperModel({name!r}, device='cuda', compute_type='int8_float16',
                 local_files_only=True)
list(m.transcribe(np.zeros(16000, dtype='float32'), beam_size=1)[0])
print('ok')
"""


def _cuda_loads_safely(model_name: str) -> bool:
    """Probe whether CUDA can actually TRANSCRIBE on this machine.

    ctranslate2 can report a CUDA device is present (get_cuda_device_count() > 0)
    yet still fail on real use - either a native access violation from a missing
    cuDNN runtime, or a "cublas64_12.dll is not found" the moment the first
    encode runs. Neither a native crash nor a runtime that only breaks at encode
    time can be caught by wrapping the load alone, so we run the whole thing -
    load AND one tiny inference - in a throwaway subprocess. If that subprocess
    exits cleanly, CUDA is safe to use in-process; otherwise we fall back to CPU
    without ever risking the main process.
    """
    if getattr(sys, "frozen", False):
        # The packaged exe is a deliberately CPU-only build (the spec excludes
        # the CUDA runtime), and sys.executable IS the app there - the probe
        # subprocess would just relaunch the app and exit at the single-instance
        # mutex, "passing" without ever executing the probe code.
        return False
    try:
        import ctranslate2
        if ctranslate2.get_cuda_device_count() < 1:
            return False
    except Exception:
        return False

    code = _PROBE_CODE.format(name=resolve_model_id(model_name))
    try:
        proc = subprocess.run(
            [sys.executable, "-c", code],
            capture_output=True, timeout=120,
        )
        return proc.returncode == 0
    except Exception as e:
        log.warning("CUDA probe failed: %s", e)
        return False


class Transcriber:
    # Class-level defaults, so the live-settings providers are safe to read on
    # ANY instance — including ones built with object.__new__ (the test suites
    # do this to skip loading a real model) and any left over from an older
    # build. A missing provider must degrade to the plain attribute, never blow
    # up a transcription.
    language_provider = None
    beam_size_provider = None
    filter_provider = None
    # Mirrors the "Ignore phantom phrases" setting (config default True). OFF
    # must mean genuinely off, including the per-segment tail strip.
    filter_hallucinations = True

    def __init__(self, model_name="small", device="auto", language="en", beam_size=5,
                 hotwords_provider=None, language_provider=None,
                 beam_size_provider=None):
        self.language = None if language == "auto" else language
        # Callable -> list[str] of dictionary words to bias recognition toward.
        # Read fresh on every transcribe() call so a word added in the dashboard
        # applies to the very next dictation without a model reload.
        self.hotwords_provider = hotwords_provider
        # beam_size=1 is greedy; 5 is noticeably more accurate for a modest CPU
        # cost. Accuracy matters more than ~100 ms here (per the pipeline audit).
        self.beam_size = beam_size
        # Language and beam size are PULLED from config per call rather than
        # pushed in on save. Pushing left two stale windows that a user reads as
        # "it dictated with my old settings":
        #
        #   * the Hub's live-apply is debounced, so a change made and dictated
        #     against inside that window went to the model as the old value;
        #   * a model reload builds its replacement Transcriber on a background
        #     thread and installs it seconds later, wiping any language change
        #     made while it was loading — permanently, since the config and the
        #     model signature both then agree there is nothing left to apply.
        #
        # Reading per call closes both by construction: there is no captured
        # copy left to go stale. The plain attributes remain the source of truth
        # when no provider is attached.
        self.language_provider = language_provider
        self.beam_size_provider = beam_size_provider
        # A single ctranslate2 WhisperModel is NOT safe to call concurrently:
        # warm_up() runs on a daemon thread at startup and could overlap the
        # user's first real dictation (and, when live typing is on, the stream
        # loop). Serialize every model.transcribe() call through this lock so the
        # warm-up finishes before the first dictation runs on the warm model.
        self._lock = threading.Lock()

        if device == "auto":
            device = "cuda" if _cuda_loads_safely(model_name) else "cpu"

        compute_type = "int8_float16" if device == "cuda" else "int8"
        try:
            self.model = load_model_offline_first(model_name, device, compute_type)
            self.device = device
        except Exception as e:
            log.warning("%s init failed (%s); falling back to CPU", device, e)
            self.model = load_model_offline_first(model_name, "cpu", "int8")
            self.device = "cpu"

    def set_hotwords_provider(self, provider) -> None:
        """Install (or clear, with None) the dictionary-word provider."""
        self.hotwords_provider = provider

    def _from_provider(self, provider, fallback, what):
        """Read a live setting, never at the cost of the user's dictation.

        A provider that raises (a half-written config, a torn-down Hub) must
        degrade to the last known value, not lose the clip.
        """
        if provider is None:
            return fallback
        try:
            return provider()
        except Exception as e:
            log.warning("%s provider failed (using %r): %s", what, fallback, e)
            return fallback

    def _current_language(self) -> str | None:
        """The language for THIS call. "auto" (and None) mean let Whisper detect."""
        value = self._from_provider(self.language_provider, self.language, "language")
        return None if value == "auto" else value

    def _current_beam_size(self) -> int:
        return self._from_provider(self.beam_size_provider, self.beam_size, "beam size")

    def _filter_enabled(self) -> bool:
        return bool(self._from_provider(
            self.filter_provider, self.filter_hallucinations, "phantom filter"))

    def _current_hotwords(self) -> str | None:
        """The glossary prompt for this call, or None. Never raises: a broken
        provider must not cost the user their dictation."""
        provider = self.hotwords_provider
        if provider is None:
            return None
        try:
            return format_hotwords(provider())
        except Exception as e:
            log.warning("hotwords provider failed (ignored): %s", e)
            return None

    def transcribe(self, audio: np.ndarray) -> str:
        if audio is None or len(audio) == 0:
            return ""
        hotwords = self._current_hotwords()
        with self._lock:
            segments, _ = self.model.transcribe(
                audio, language=self._current_language(),
                beam_size=self._current_beam_size(),
                # Dictionary words, biasing every window of this clip. None when
                # the dictionary is empty, which is faster-whisper's own default.
                hotwords=hotwords,
                # Don't feed each segment's text as context to the next. On long
                # dictations this is faster and avoids repetition/drift as the clip grows.
                condition_on_previous_text=False,
                # VAD trims dead air (faster) and, with a lower threshold, keeps soft
                # speech from quiet mics instead of dropping it.
                vad_filter=True,
                vad_parameters=dict(threshold=0.3, min_silence_duration_ms=500),
            )
            # Materialize once: the generator is lazy, and the phantom-tail
            # check needs to look at the LAST segment. This is the same single
            # decode pass either way - no second model run.
            segments = list(segments)
            texts = (strip_phantom_tail(segments) if self._filter_enabled()
                     else [seg.text for seg in segments])
            text = join_segments(texts)
        return self._drop_prompt_echo(text, hotwords)

    @staticmethod
    def _drop_prompt_echo(text: str, hotwords: str | None) -> str:
        if _is_prompt_echo(text, hotwords):
            log.info("dropping glossary prompt echoed back as transcript")
            return ""
        return text

    def warm_up(self) -> None:
        """Run one tiny transcription so the model's kernels/buffers are ready.
        Without this the FIRST real dictation after launch pays a warm-up cost;
        doing it silently at startup makes every user-visible dictation fast.
        Holds the model lock for its duration so a dictation that fires mid
        warm-up waits and then runs on the already-warm model.

        No hotwords here on purpose: this runs on pure silence, the textbook
        way to make a primed decoder emit its prompt, and the output is thrown
        away anyway."""
        try:
            silence = np.zeros(16000, dtype="float32")  # 1s of silence
            with self._lock:
                list(self.model.transcribe(
                    silence, language=self._current_language(), beam_size=1)[0])
        except Exception as e:
            log.warning("warm-up failed (non-fatal): %s", e)
