"""Tests for the start/stop/error audio cues.

Everything runs against a fake backend and a synchronous spawn, so the suite
never makes the machine beep and never depends on thread timing.
"""
import pytest

from rekounts.sounds import (_AMPLITUDE, ERROR_CUE, START_CUE, STOP_CUE,
                                VOLUME_LEVELS, VOLUME_LOUD, VOLUME_NORMAL,
                                VOLUME_SOFT, NullBackend, SineBackend, Sounds,
                                WinsoundBackend, default_backend, render_wav)


class FakeBackend:
    def __init__(self, fail=False):
        self.played = []
        self.fail = fail

    def play(self, tones):
        if self.fail:
            raise OSError("no audio device")
        self.played.append(tuple(tones))


def make(enabled=True, backend=None, spawn=None):
    """A Sounds that plays synchronously on the calling thread."""
    backend = backend or FakeBackend()
    provider = enabled if callable(enabled) else (lambda: enabled)
    return Sounds(provider, backend=backend,
                  spawn=spawn or (lambda fn: fn())), backend


# ------------------------------------------------------------------ gating
def test_cues_play_when_enabled():
    s, backend = make(enabled=True)
    s.start_cue()
    s.stop_cue()
    s.error_cue()
    assert backend.played == [START_CUE, STOP_CUE, ERROR_CUE]


def test_disabled_is_a_silent_no_op():
    s, backend = make(enabled=False)
    s.start_cue()
    s.stop_cue()
    s.error_cue()
    assert backend.played == []


def test_provider_is_read_every_cue_not_cached():
    # Flipping the "Sound effects" switch must take effect with no rebuild.
    state = {"on": False}
    s, backend = make(enabled=lambda: state["on"])
    s.start_cue()
    assert backend.played == []
    state["on"] = True
    s.start_cue()
    assert backend.played == [START_CUE]


def test_broken_provider_is_treated_as_off():
    def boom():
        raise RuntimeError("config exploded")

    s, backend = make(enabled=boom)
    s.start_cue()          # must not raise
    assert backend.played == []
    assert s.enabled() is False


def test_start_stop_and_error_cues_are_distinct():
    assert len({START_CUE, STOP_CUE, ERROR_CUE}) == 3


# --------------------------------------------------------------- resilience
def test_backend_failure_is_swallowed_and_silences_further_cues():
    s, backend = make(enabled=True, backend=FakeBackend(fail=True))
    s.start_cue()          # must not raise
    backend.fail = False   # even if the backend recovers, we stay quiet
    s.stop_cue()
    assert backend.played == []


def test_pending_cues_are_capped_then_accepted_again():
    queued = []
    s, backend = make(enabled=True, spawn=queued.append)
    for _ in range(5):
        s.start_cue()
    assert len(queued) == 2          # _MAX_PENDING; the rest are dropped
    for fn in queued:
        fn()
    assert len(backend.played) == 2
    s.start_cue()                    # queue drained -> accepting again
    assert len(queued) == 3


def test_null_backend_plays_nothing_and_never_raises():
    NullBackend().play(START_CUE)


def test_default_backend_exposes_play():
    assert callable(default_backend().play)


def test_winsound_backend_uses_injected_module():
    class FakeWinsound:
        def __init__(self):
            self.beeps = []

        def Beep(self, freq, ms):  # noqa: N802 (mirrors the stdlib name)
            self.beeps.append((freq, ms))

    ws = FakeWinsound()
    WinsoundBackend(ws).play(((440, 50), (880, 60)))
    assert ws.beeps == [(440, 50), (880, 60)]


def test_default_enabled_provider_is_on():
    s = Sounds(backend=FakeBackend(), spawn=lambda fn: fn())
    assert s.enabled() is True


@pytest.mark.parametrize("cue", [START_CUE, STOP_CUE, ERROR_CUE])
def test_cues_are_short_and_subtle(cue):
    total_ms = sum(ms for _, ms in cue)
    assert total_ms <= 200, "a cue longer than 200ms stops feeling subtle"
    assert all(200 <= freq <= 2000 for freq, _ in cue)


def test_start_and_stop_are_single_minimal_notes():
    # "A very minimalistic beep, nothing fancy, like a toot" -> one note each,
    # told apart by pitch. ERROR keeps two so it can never be mistaken for them.
    assert len(START_CUE) == 1
    assert len(STOP_CUE) == 1
    assert len(ERROR_CUE) > 1


def test_stop_is_pitched_below_start():
    # Falling = "done" without needing a second note to say so.
    assert STOP_CUE[0][0] < START_CUE[0][0]


@pytest.mark.parametrize("cue", [START_CUE, STOP_CUE, ERROR_CUE])
def test_cues_sit_in_the_soft_low_band(cue):
    """The user report was "too loud and too noticeable", and pitch drove that
    as much as level: the ear is far more sensitive at 660-880 Hz (where the
    v0.3.0 cues sat) than down here. The floor matters too — laptop speakers
    roll off below ~400 Hz, so a cue pitched much lower measures quieter and
    then can't be heard at all on the commonest hardware."""
    for freq, _ in cue:
        assert 250 <= freq <= 500, "outside the soft-but-still-audible band"


def test_cues_are_quieter_than_the_v030_release():
    """Regression guard on the actual complaint. 0.22 was the fixed v0.3.0
    amplitude; every level we now offer has to stay under it."""
    assert _AMPLITUDE < 0.22
    assert max(VOLUME_LEVELS) < 0.22


def test_volume_levels_are_ordered_and_default_is_normal():
    assert VOLUME_SOFT < VOLUME_NORMAL < VOLUME_LOUD
    assert _AMPLITUDE == VOLUME_NORMAL


# ------------------------------------------------------------- sine synthesis
class FakeWinsound:
    """Stand-in for the stdlib winsound module (both backends' dependency)."""
    SND_MEMORY = 0x0004
    SND_NODEFAULT = 0x0002
    SND_ASYNC = 0x0001

    def __init__(self):
        self.played = []            # (data, flags) captured from PlaySound
        self.beeps = []             # (freq, ms) captured from Beep

    def PlaySound(self, data, flags):  # noqa: N802 (mirrors the stdlib name)
        self.played.append((data, flags))

    def Beep(self, freq, ms):  # noqa: N802
        self.beeps.append((freq, ms))


def _wav_header(data):
    """(channels, sampwidth, framerate, nframes) of an in-memory WAV."""
    import io
    import wave
    with wave.open(io.BytesIO(data), "rb") as w:
        return (w.getnchannels(), w.getsampwidth(),
                w.getframerate(), w.getnframes())


def test_render_wav_is_a_valid_mono_16bit_pcm():
    data = render_wav(((440, 100),), sample_rate=22050)
    ch, width, rate, nframes = _wav_header(data)
    assert (ch, width, rate) == (1, 2, 22050)
    assert nframes == int(22050 * 100 / 1000)


def _samples(data):
    """The raw 16-bit samples of an in-memory WAV."""
    import array
    import io
    import wave
    with wave.open(io.BytesIO(data), "rb") as w:
        s = array.array("h")
        s.frombytes(w.readframes(w.getnframes()))
    return s


def test_render_wav_stays_soft():
    data = render_wav(((440, 120),), amplitude=0.22)
    peak = max(abs(s) for s in _samples(data))
    assert 0 < peak <= int(0.22 * 32767) + 1   # audible, but never above amplitude


def test_render_wav_honors_amplitude():
    quiet = max(abs(s) for s in _samples(render_wav(((440, 80),), amplitude=0.05)))
    loud = max(abs(s) for s in _samples(render_wav(((440, 80),), amplitude=0.18)))
    assert quiet < loud


def test_render_wav_clamps_amplitude_to_full_scale():
    peak = max(abs(s) for s in _samples(render_wav(((440, 40),), amplitude=9.0)))
    assert peak <= 32767


def test_short_note_fades_instead_of_clicking():
    """A fade longer than half the note must not leave the envelope jumping from
    full scale straight into the fade-out — that step is an audible click, which
    is the one thing the fade exists to prevent."""
    sr, freq = 22050, 440
    data = render_wav(((freq, 20),), sample_rate=sr, amplitude=0.5, fade_ms=14)
    s = _samples(data)
    peak = max(abs(x) for x in s)
    # A clean sine steps at most peak*2*pi*f/sr between samples (~12.5% here);
    # the discontinuity this guards against is several times larger.
    import math
    clean_step = peak * 2 * math.pi * freq / sr
    worst = max(abs(s[i + 1] - s[i]) for i in range(len(s) - 1))
    assert worst < clean_step * 2, "envelope discontinuity -> click"


def test_render_wav_differs_per_cue():
    assert len({render_wav(START_CUE), render_wav(STOP_CUE),
                render_wav(ERROR_CUE)}) == 3


def test_sine_backend_plays_from_memory_synchronously():
    fw = FakeWinsound()
    SineBackend(fw).play(START_CUE)
    assert len(fw.played) == 1
    data, flags = fw.played[0]
    assert flags & fw.SND_MEMORY
    assert not flags & fw.SND_ASYNC     # synchronous -> _play_lock stays one-at-a-time
    _wav_header(data)                   # the payload is a real WAV (raises otherwise)


def test_sine_backend_caches_render_per_cue():
    fw = FakeWinsound()
    backend = SineBackend(fw)
    backend.play(START_CUE)
    backend.play(START_CUE)
    assert len(fw.played) == 2                  # played both times...
    assert fw.played[0][0] is fw.played[1][0]   # ...from a single cached render


def test_sine_backend_requires_in_memory_playsound():
    class BeepOnly:                     # a winsound lacking PlaySound / SND_MEMORY
        def Beep(self, freq, ms):  # noqa: N802
            pass

    with pytest.raises(Exception):
        SineBackend(BeepOnly())


def test_default_backend_prefers_sine_where_winsound_exists():
    pytest.importorskip("winsound")    # Windows-only; skipped on other platforms
    from rekounts import sounds
    assert isinstance(sounds.default_backend(), sounds.SineBackend)


def test_default_backend_falls_back_to_silence_not_beep(monkeypatch):
    """No in-memory playback -> silence. ``winsound.Beep`` is a fixed
    FULL-VOLUME square wave with no volume parameter, so it can honor neither
    the quiet cues nor the volume setting; on a machine that can't do
    PlaySound/SND_MEMORY, silence is the better failure than a blast."""
    import sys

    from rekounts import sounds

    class _Unavailable:
        def __init__(self, *a, **k):
            raise RuntimeError("backend unavailable here")

    # This is the NON-darwin chain (darwin prefers afplay and is covered in
    # test_sounds_macos.py); pin the platform so real macOS CI doesn't take
    # the afplay branch here.
    monkeypatch.setattr(sys, "platform", "win32")

    called = []
    monkeypatch.setattr(sounds, "SineBackend", _Unavailable)
    monkeypatch.setattr(
        sounds, "WinsoundBackend",
        lambda *a, **k: called.append(1) or "beep")   # must never be reached

    assert isinstance(sounds.default_backend(), sounds.NullBackend)
    assert called == [], "Beep must not be in the automatic fallback chain"


def test_default_backend_passes_volume_through(monkeypatch):
    import sys

    from rekounts import sounds

    seen = {}
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(sounds, "SineBackend",
                        lambda **k: seen.update(k) or "sine")
    provider = lambda: 0.5      # noqa: E731
    assert sounds.default_backend(amplitude=provider) == "sine"
    assert seen["amplitude"] is provider


# --------------------------------------------------------------------- volume
def test_sine_backend_reads_volume_live_on_every_cue():
    # The Hub's volume dropdown must apply without rebuilding anything.
    level = {"v": VOLUME_SOFT}
    fw = FakeWinsound()
    SineBackend(fw, amplitude=lambda: level["v"]).play(START_CUE)
    soft = fw.played[0][0]
    level["v"] = VOLUME_LOUD
    SineBackend(fw, amplitude=lambda: level["v"]).play(START_CUE)
    assert max(abs(s) for s in _samples(soft)) < \
        max(abs(s) for s in _samples(fw.played[1][0]))


def test_changing_volume_rerenders_instead_of_replaying_a_stale_cue():
    level = {"v": VOLUME_SOFT}
    fw = FakeWinsound()
    backend = SineBackend(fw, amplitude=lambda: level["v"])
    backend.play(START_CUE)
    level["v"] = VOLUME_LOUD
    backend.play(START_CUE)          # same cue, new volume -> must NOT be cached
    assert fw.played[0][0] != fw.played[1][0]


def test_volume_cache_still_renders_once_per_cue_at_a_steady_volume():
    fw = FakeWinsound()
    backend = SineBackend(fw, amplitude=lambda: VOLUME_NORMAL)
    backend.play(START_CUE)
    backend.play(START_CUE)
    assert fw.played[0][0] is fw.played[1][0]


@pytest.mark.parametrize("bad", [None, "loud", object()])
def test_broken_or_missing_volume_falls_back_to_the_default(bad):
    # A config predating the key (None) or holding junk must not go silent, and
    # must not blare — it plays at the built-in level.
    fw = FakeWinsound()
    SineBackend(fw, amplitude=lambda: bad).play(START_CUE)
    expected = render_wav(START_CUE, amplitude=_AMPLITUDE)
    assert fw.played[0][0] == expected


def test_volume_provider_that_raises_is_survivable():
    def boom():
        raise RuntimeError("config exploded")

    fw = FakeWinsound()
    SineBackend(fw, amplitude=boom).play(START_CUE)      # must not raise
    assert fw.played[0][0] == render_wav(START_CUE, amplitude=_AMPLITUDE)


def test_sounds_wires_volume_provider_into_its_backend(monkeypatch):
    from rekounts import sounds

    seen = {}
    monkeypatch.setattr(sounds, "default_backend",
                        lambda amplitude=None: seen.update(amplitude=amplitude)
                        or NullBackend())
    provider = lambda: VOLUME_LOUD      # noqa: E731
    Sounds(enabled_provider=lambda: True, volume_provider=provider)
    assert seen["amplitude"] is provider


def test_injected_backend_keeps_its_own_volume(monkeypatch):
    """An explicitly injected backend already owns its amplitude — Sounds must
    not reach in and override it (this is what the whole test suite relies on)."""
    from rekounts import sounds

    monkeypatch.setattr(sounds, "default_backend",
                        lambda **k: pytest.fail("should not build a backend"))
    backend = FakeBackend()
    s = Sounds(enabled_provider=lambda: True, backend=backend,
               volume_provider=lambda: VOLUME_LOUD, spawn=lambda fn: fn())
    s.start_cue()
    assert backend.played == [START_CUE]
