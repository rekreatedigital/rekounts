"""Tests for the start/stop/error audio cues.

Everything runs against a fake backend and a synchronous spawn, so the suite
never makes the machine beep and never depends on thread timing.
"""
import pytest

from rekounts.sounds import (ERROR_CUE, START_CUE, STOP_CUE, NullBackend,
                                SineBackend, Sounds, WinsoundBackend,
                                default_backend, render_wav)


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


def test_start_cue_is_a_single_minimal_note():
    # "Start sound should be minimal, nothing fancy" -> one note, not an arpeggio.
    assert len(START_CUE) == 1


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


def test_render_wav_stays_soft():
    import array
    import io
    import wave

    data = render_wav(((440, 120),), amplitude=0.22)
    with wave.open(io.BytesIO(data), "rb") as w:
        samples = array.array("h")
        samples.frombytes(w.readframes(w.getnframes()))
    peak = max(abs(s) for s in samples)
    assert 0 < peak <= int(0.22 * 32767) + 1   # audible, but never above amplitude


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


def test_default_backend_falls_back_beep_then_null(monkeypatch):
    from rekounts import sounds

    class _Unavailable:
        def __init__(self, *a, **k):
            raise RuntimeError("backend unavailable here")

    # sine down, beep up -> WinsoundBackend
    monkeypatch.setattr(sounds, "SineBackend", _Unavailable)
    monkeypatch.setattr(sounds, "WinsoundBackend", lambda *a, **k: "beep")
    assert sounds.default_backend() == "beep"

    # both down -> silent NullBackend, never raises
    monkeypatch.setattr(sounds, "WinsoundBackend", _Unavailable)
    assert isinstance(sounds.default_backend(), sounds.NullBackend)
