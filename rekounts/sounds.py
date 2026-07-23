"""Subtle audio cues for dictation start / stop / error.

Stdlib only, Windows-first: each cue is synthesized as a soft, low-amplitude
sine wave and played straight from memory via ``winsound.PlaySound``
(SND_MEMORY), so there is nothing to bundle, nothing to download, and no new
dependency. A pure sine at low amplitude is the point — ``winsound.Beep`` can
only emit a fixed, full-volume square wave (no volume parameter exists), which
is exactly the harsh cue we are moving away from. Where in-memory playback is
unavailable it falls back to ``Beep``, and failing that every cue is silent.

Wiring contract (this is what ``__main__`` calls)::

    from rekounts.sounds import Sounds

    sounds = Sounds(enabled_provider=lambda: cfg.get("sound_effects"))
    sounds.start_cue()    # recording began
    sounds.stop_cue()     # recording ended, transcription starting
    sounds.error_cue()    # something failed

``enabled_provider`` is read on every cue (never cached), so flipping the
"Sound effects" switch in the Hub takes effect immediately with no rebuild.
All three methods are thread-safe, return immediately (playback happens on a
daemon thread), and never raise — they are safe to call from the hotkey
listener, a worker thread, or the Qt GUI thread.
"""

import array
import io
import logging
import math
import sys
import threading
import wave

log = logging.getLogger(__name__)

# (frequency Hz, duration ms) sequences. Deliberately quiet and short — a cue you
# stop noticing after a day, not a notification jingle. START is a single note:
# "minimal, nothing fancy". STOP/ERROR keep a two-note shape so the three cues
# stay instantly distinguishable by ear.
START_CUE = ((659, 90),)              # single soft note: "listening"
STOP_CUE = ((880, 45), (659, 55))     # descending: "done"
ERROR_CUE = ((392, 70), (294, 100))   # low fall: "that didn't work"

# --- soft sine synthesis (stdlib) ---------------------------------------------
# A low-amplitude sine, rendered to an in-memory WAV, replaces the fixed-volume
# Beep square wave so the cues can be genuinely gentle.
_SAMPLE_RATE = 22050          # ample for sub-2 kHz cues; keeps the buffer tiny
_AMPLITUDE = 0.22             # ~-13 dBFS: clearly audible but never startling
_FADE_MS = 6                  # per-note fade in/out kills click/pop transients


def render_wav(tones, sample_rate=_SAMPLE_RATE, amplitude=_AMPLITUDE,
               fade_ms=_FADE_MS):
    """Render (freq_hz, duration_ms) tones to a mono 16-bit PCM WAV (bytes).

    Each note is a sine at `amplitude` (0..1 of full scale) with a short linear
    fade in/out so consecutive notes don't click. Pure and stdlib-only, so it is
    unit-testable without an audio device.
    """
    frames = array.array("h")
    fade = max(1, int(sample_rate * fade_ms / 1000))
    peak = int(max(0.0, min(1.0, amplitude)) * 32767)
    for freq, ms in tones:
        n = max(1, int(sample_rate * ms / 1000))
        step = 2.0 * math.pi * freq / sample_rate
        for i in range(n):
            if i < fade:
                env = i / fade
            elif i >= n - fade:
                env = max(0.0, (n - 1 - i) / fade)
            else:
                env = 1.0
            frames.append(int(peak * env * math.sin(step * i)))
    if sys.byteorder != "little":     # WAV PCM is little-endian; array is native
        frames.byteswap()
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sample_rate)
        w.writeframes(frames.tobytes())
    return buf.getvalue()


# Cues are ~100 ms and play one at a time. If two are already queued, a third
# would only ever arrive late and out of context, so it is dropped instead.
_MAX_PENDING = 2


class SineBackend:
    """Plays cues as a soft, low-amplitude sine via ``winsound.PlaySound`` with
    SND_MEMORY (Windows, stdlib). Unlike ``Beep`` this has a real volume and a
    clean tone, so the cues can be genuinely subtle.

    Playback is synchronous (no SND_ASYNC): each cue plays to completion on the
    caller's daemon thread, so ``Sounds``' one-cue-at-a-time ``_play_lock``
    semantics hold (SND_ASYNC would cut off an overlapping cue instead).
    ``winsound_module`` is injectable so tests never touch a real audio device.
    """

    def __init__(self, winsound_module=None, sample_rate=_SAMPLE_RATE,
                 amplitude=_AMPLITUDE):
        if winsound_module is None:
            import winsound as winsound_module  # noqa: PLC0415 (Windows-only, lazy)
        # A winsound without in-memory playback should fall through to Beep.
        if not hasattr(winsound_module, "PlaySound") or not hasattr(
                winsound_module, "SND_MEMORY"):
            raise RuntimeError("winsound has no in-memory PlaySound")
        self._winsound = winsound_module
        self._sample_rate = sample_rate
        self._amplitude = amplitude
        self._cache = {}                 # tones -> rendered WAV; the 3 cues repeat

    def play(self, tones):
        key = tuple(tones)
        data = self._cache.get(key)
        if data is None:
            data = render_wav(key, self._sample_rate, self._amplitude)
            self._cache[key] = data
        flags = self._winsound.SND_MEMORY | getattr(
            self._winsound, "SND_NODEFAULT", 0)   # silence, not a system ding
        self._winsound.PlaySound(data, flags)


class WinsoundBackend:
    """Fallback that plays tone pairs through ``winsound.Beep`` (Windows, stdlib).

    Harsher than :class:`SineBackend` (fixed-volume square wave), used only when
    in-memory playback is unavailable. ``winsound_module`` is injectable so tests
    can pass a fake instead of making the machine beep.
    """

    def __init__(self, winsound_module=None):
        if winsound_module is None:
            import winsound as winsound_module  # noqa: PLC0415 (Windows-only, lazy)
        self._winsound = winsound_module

    def play(self, tones):
        for freq, ms in tones:
            self._winsound.Beep(int(freq), int(ms))


class NullBackend:
    """Used when no audio backend exists. Every cue is silence."""

    def play(self, tones):
        pass


def default_backend():
    """The best backend available here — never raises, worst case it is silent.

    Preference: soft in-memory sine (SineBackend) -> winsound.Beep
    (WinsoundBackend) -> silence (NullBackend).
    """
    for factory in (SineBackend, WinsoundBackend):
        try:
            return factory()
        except Exception as e:  # non-Windows, or a stripped-down winsound
            log.info("audio backend %s unavailable (%s)", factory.__name__, e)
    log.info("no audio cue backend available; cues will be silent")
    return NullBackend()


def _spawn(fn):
    threading.Thread(target=fn, daemon=True).start()


class Sounds:
    """Non-blocking start/stop/error cues, gated on a live enabled provider."""

    def __init__(self, enabled_provider=None, backend=None, spawn=None):
        self._enabled_provider = (
            enabled_provider if callable(enabled_provider) else (lambda: True))
        self._backend = backend if backend is not None else default_backend()
        # Injectable so tests can run cues synchronously instead of racing threads.
        self._spawn = spawn or _spawn
        self._play_lock = threading.Lock()   # Beep blocks; play one cue at a time
        self._guard = threading.Lock()       # protects _pending / _available
        self._pending = 0
        self._available = True

    # ------------------------------------------------------------------ cues
    def start_cue(self):
        self._play(START_CUE)

    def stop_cue(self):
        self._play(STOP_CUE)

    def error_cue(self):
        self._play(ERROR_CUE)

    # ----------------------------------------------------------------- state
    def enabled(self) -> bool:
        """True if cues should sound right now. A provider that raises is
        treated as "off" — a broken setting must not break dictation."""
        try:
            return bool(self._enabled_provider())
        except Exception:
            return False

    # --------------------------------------------------------------- internal
    def _play(self, tones):
        if not self._available or not self.enabled():
            return
        with self._guard:
            if self._pending >= _MAX_PENDING:
                return
            self._pending += 1
        self._spawn(lambda: self._run(tones))

    def _run(self, tones):
        try:
            with self._play_lock:
                self._backend.play(tones)
        except Exception as e:
            # One failure means this machine can't play cues at all (no audio
            # device, blocked API). Go quiet permanently rather than raising on
            # every dictation.
            with self._guard:
                self._available = False
            log.info("audio cue failed (%s); disabling sound effects", e)
        finally:
            with self._guard:
                self._pending -= 1
