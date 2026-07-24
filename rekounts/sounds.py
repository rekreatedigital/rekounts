"""Subtle audio cues for dictation start / stop / error.

Stdlib only: each cue is synthesized as a soft, low-amplitude sine wave and
played via ``winsound.PlaySound`` straight from memory on Windows (SND_MEMORY)
or via the stock ``afplay`` from a temp WAV on macOS — so there is nothing to
bundle, nothing to download, and no new dependency. A pure sine at low
amplitude is the point — ``winsound.Beep`` can only emit a fixed, full-volume
square wave (no volume parameter exists), which is exactly the harsh cue we
are moving away from, so it is not in the fallback chain at all: where
in-memory playback is unavailable every cue is simply silent.

Wiring contract (this is what ``__main__`` calls)::

    from rekounts.sounds import Sounds

    sounds = Sounds(enabled_provider=lambda: cfg.get("sound_effects"),
                    volume_provider=lambda: cfg.get("sound_volume"))
    sounds.start_cue()    # recording began
    sounds.stop_cue()     # recording ended, transcription starting
    sounds.error_cue()    # something failed

Both providers are read on every cue (never cached), so the Hub's "Sound
effects" switch and "Volume" dropdown take effect immediately with no rebuild.
All three methods are thread-safe, return immediately (playback happens on a
daemon thread), and never raise — they are safe to call from the hotkey
listener, a worker thread, or the Qt GUI thread.
"""

import array
import io
import logging
import math
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import wave

log = logging.getLogger(__name__)

# (frequency Hz, duration ms) sequences. A toot, not a notification jingle —
# short, low, and soft enough that you stop noticing it after a day.
#
# Both levers matter, and pitch is the one that was wrong before. The ear is far
# more sensitive around 600-900 Hz than it is near 350 Hz, so the old 659/880 Hz
# cues were the loudest thing here even before amplitude came into it. Dropping
# into the 260-470 Hz range buys ~4 dB of perceived loudness for free and turns
# the character from "beep" into "toot".
#
# There is a floor, though: laptop speakers roll off hard below ~400 Hz, so cues
# pitched down at 200-260 Hz measure lovely and then vanish on the most common
# hardware. These sit at or above that knee deliberately. Measured A-weighted
# against the v0.3.0 cues (and again through a laptop-speaker rolloff model):
# start -9.8 dB, stop -12.5 dB, error -8.3 dB — about half as loud, still there.
#
# START and STOP are each a SINGLE note ("minimal, nothing fancy"), told apart by
# pitch: the stop tone is lower, which reads as "done". ERROR keeps a two-note
# fall — it is rare, and it is the one cue that must never be mistaken for the
# other two.
START_CUE = ((466, 55),)              # single soft note: "listening"
STOP_CUE = ((349, 60),)               # lower single note: "done"
ERROR_CUE = ((392, 55), (262, 85))    # falling pair: "that didn't work"

# --- soft sine synthesis (stdlib) ---------------------------------------------
# A low-amplitude sine, rendered to an in-memory WAV, replaces the fixed-volume
# Beep square wave so the cues can be genuinely gentle.
_SAMPLE_RATE = 22050          # ample for sub-2 kHz cues; keeps the buffer tiny
_AMPLITUDE = 0.09             # ~-21 dBFS, the "Normal" volume level below
_FADE_MS = 14                 # per-note fade in/out kills click/pop transients

# The three volumes the Hub offers, as peak amplitude (0..1 of full scale).
# Stored in config as the float itself, so hand-editing config.json to any value
# in between works; the Hub's dropdown just snaps to the nearest of these.
# LOUD is still quieter, A-weighted, than the single fixed volume v0.3.0 shipped —
# the old cues were bright as well as loud, and this range replaces both.
VOLUME_SOFT = 0.05
VOLUME_NORMAL = 0.09
VOLUME_LOUD = 0.18
VOLUME_LEVELS = (VOLUME_SOFT, VOLUME_NORMAL, VOLUME_LOUD)


def render_wav(tones, sample_rate=_SAMPLE_RATE, amplitude=_AMPLITUDE,
               fade_ms=_FADE_MS):
    """Render (freq_hz, duration_ms) tones to a mono 16-bit PCM WAV (bytes).

    Each note is a sine at `amplitude` (0..1 of full scale) with a short linear
    fade in/out so consecutive notes don't click. Pure and stdlib-only, so it is
    unit-testable without an audio device.
    """
    frames = array.array("h")
    want_fade = max(1, int(sample_rate * fade_ms / 1000))
    peak = int(max(0.0, min(1.0, amplitude)) * 32767)
    for freq, ms in tones:
        n = max(1, int(sample_rate * ms / 1000))
        # Per note, never let the two ramps overlap: with a long fade and a short
        # note the envelope would otherwise jump from full scale straight into
        # the fade-out — a click, which is exactly what the fade exists to avoid.
        fade = max(1, min(want_fade, n // 2))
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


def _resolve_amplitude(amplitude):
    """Peak amplitude for the next cue, as a clamped 0..1 float.

    `amplitude` is either a plain float or a callable returning one. The callable
    form is what makes the Hub's volume dropdown live: it is read on every cue,
    never cached, so changing volume applies without rebuilding anything —
    exactly like ``Sounds``' enabled_provider. A missing key or a broken provider
    falls back to the default rather than going silent or blaring.
    """
    try:
        value = amplitude() if callable(amplitude) else amplitude
        if value is None:
            return _AMPLITUDE
        return min(1.0, max(0.0, float(value)))
    except Exception:
        log.info("volume provider failed; using the default cue volume")
        return _AMPLITUDE


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

    ``amplitude`` may be a float or a callable returning one — see
    :func:`_resolve_amplitude` for why the callable form matters.
    """

    def __init__(self, winsound_module=None, sample_rate=_SAMPLE_RATE,
                 amplitude=_AMPLITUDE):
        if winsound_module is None:
            import winsound as winsound_module  # noqa: PLC0415 (Windows-only, lazy)
        # Without in-memory playback there is no volume control at all, so this
        # machine gets silence rather than a full-volume Beep. See default_backend.
        if not hasattr(winsound_module, "PlaySound") or not hasattr(
                winsound_module, "SND_MEMORY"):
            raise RuntimeError("winsound has no in-memory PlaySound")
        self._winsound = winsound_module
        self._sample_rate = sample_rate
        self._amplitude = amplitude
        # Keyed on volume too: the 3 cues repeat at a stable volume, so this
        # still renders once each, but changing volume re-renders instead of
        # replaying a stale WAV at the old level.
        self._cache = {}                 # (tones, volume) -> rendered WAV

    def play(self, tones):
        key = (tuple(tones), _resolve_amplitude(self._amplitude))
        data = self._cache.get(key)
        if data is None:
            data = render_wav(key[0], self._sample_rate, key[1])
            self._cache[key] = data
        flags = self._winsound.SND_MEMORY | getattr(
            self._winsound, "SND_NODEFAULT", 0)   # silence, not a system ding
        self._winsound.PlaySound(data, flags)


class WinsoundBackend:
    """Plays tone pairs through ``winsound.Beep`` (Windows, stdlib).

    **No longer auto-selected** — see :func:`default_backend`. ``Beep`` emits a
    fixed, full-volume square wave and takes no volume parameter, so it can honor
    neither the quiet cue design nor the Hub's volume setting. It is kept because
    the backend slot is injectable and it remains a valid thing to pass by hand,
    but nothing reaches it by default. ``winsound_module`` is injectable so tests
    can pass a fake instead of making the machine beep.
    """

    def __init__(self, winsound_module=None):
        if winsound_module is None:
            import winsound as winsound_module  # noqa: PLC0415 (Windows-only, lazy)
        self._winsound = winsound_module

    def play(self, tones):
        for freq, ms in tones:
            self._winsound.Beep(int(freq), int(ms))


class AfplayBackend:
    """Plays cues on macOS via ``afplay``, the stock command-line audio player.

    The same soft sine cues as :class:`SineBackend`, rendered once per cue to a
    small WAV in a private temp directory and handed to ``afplay`` (present on
    every macOS install — nothing to bundle, no new Python dependency, and no
    permission involved: playback needs no consent, only recording does).

    ``afplay`` blocks until the cue finishes, which preserves ``Sounds``'
    one-cue-at-a-time ``_play_lock`` semantics exactly like the synchronous
    ``winsound.PlaySound`` path. ``runner`` and ``which`` are injectable so
    tests never spawn a process or require macOS.
    """

    def __init__(self, runner=None, which=None, sample_rate=_SAMPLE_RATE,
                 amplitude=_AMPLITUDE):
        which = which or shutil.which
        if not which("afplay"):
            raise RuntimeError("afplay not found on PATH")
        self._runner = runner or self._run_afplay
        self._sample_rate = sample_rate
        self._amplitude = amplitude
        self._cache = {}          # (tones, volume) -> WAV path; the 3 cues repeat
        self._tmpdir = None       # created lazily, on the first actual cue

    @staticmethod
    def _run_afplay(path):
        subprocess.run(["afplay", path], check=True, timeout=10,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    def _cue_path(self, key):
        path = self._cache.get(key)
        if path is None or not os.path.exists(path):
            if self._tmpdir is None:
                self._tmpdir = tempfile.mkdtemp(prefix="rekounts-cues-")
            path = os.path.join(self._tmpdir, "cue-%d.wav" % len(self._cache))
            with open(path, "wb") as f:
                f.write(render_wav(key[0], self._sample_rate, key[1]))
            self._cache[key] = path
        return path

    def play(self, tones):
        self._runner(self._cue_path(
            (tuple(tones), _resolve_amplitude(self._amplitude))))


class NullBackend:
    """Used when no audio backend exists. Every cue is silence."""

    def play(self, tones):
        pass


def default_backend(amplitude=_AMPLITUDE):
    """The best backend available here — never raises, worst case it is silent.

    Preference, per platform:
      * Windows (and anywhere stdlib winsound exists): soft in-memory sine
        (SineBackend) -> silence.
      * macOS: the same soft sine rendered to a temp WAV and played by the
        stock ``afplay`` (AfplayBackend) -> silence.

    ``winsound.Beep`` is deliberately NOT in the Windows chain any more. It is
    a fixed, full-volume square wave with no volume parameter, so it can honor
    neither the quiet cues nor the volume setting — on a machine that somehow
    can't do in-memory playback, silence is the better failure. In practice the
    distinction is theoretical: every real Windows Python has PlaySound and
    SND_MEMORY, so SineBackend is what actually gets selected.

    ``amplitude`` is passed through to the rendering backends and may be a
    callable, which is how the Hub's volume setting applies live.
    """
    if sys.platform == "darwin":
        factories = (AfplayBackend,)
    else:
        factories = (SineBackend,)
    for factory in factories:
        try:
            return factory(amplitude=amplitude)
        except Exception as e:  # missing player, or a stripped-down winsound
            log.info("audio backend %s unavailable (%s)", factory.__name__, e)
    log.info("no audio cue backend available; cues will be silent")
    return NullBackend()


def _spawn(fn):
    threading.Thread(target=fn, daemon=True).start()


class Sounds:
    """Non-blocking start/stop/error cues, gated on a live enabled provider."""

    def __init__(self, enabled_provider=None, backend=None, spawn=None,
                 volume_provider=None):
        self._enabled_provider = (
            enabled_provider if callable(enabled_provider) else (lambda: True))
        # volume_provider configures the backend we build; an injected backend
        # already owns its own amplitude, so it is left alone.
        if backend is None:
            backend = default_backend(
                amplitude=volume_provider if callable(volume_provider)
                else _AMPLITUDE)
        self._backend = backend
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
