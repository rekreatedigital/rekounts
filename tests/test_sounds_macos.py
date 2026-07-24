"""AfplayBackend: the macOS audio-cue path, tested with fakes on every OS."""
import array
import sys
import wave

import pytest

import rekounts.sounds as sounds
from rekounts.sounds import (_AMPLITUDE, START_CUE, STOP_CUE, VOLUME_LOUD,
                             VOLUME_SOFT, AfplayBackend, Sounds)


def make_backend(played=None):
    played = played if played is not None else []
    return AfplayBackend(runner=played.append,
                         which=lambda name: "/usr/bin/afplay"), played


def test_requires_afplay_on_path():
    with pytest.raises(RuntimeError):
        AfplayBackend(runner=lambda p: None, which=lambda name: None)


def test_play_renders_a_valid_wav_and_runs_afplay():
    backend, played = make_backend()
    backend.play(START_CUE)
    assert len(played) == 1
    with wave.open(played[0], "rb") as w:
        assert w.getnchannels() == 1
        assert w.getsampwidth() == 2
        assert w.getnframes() > 0


def test_cue_files_are_cached_per_tone_sequence():
    backend, played = make_backend()
    backend.play(START_CUE)
    backend.play(START_CUE)
    backend.play(STOP_CUE)
    assert played[0] == played[1]          # same cue -> same file
    assert played[2] != played[0]          # different cue -> different file


def test_wav_content_matches_render_wav():
    backend, played = make_backend()
    backend.play(START_CUE)
    with open(played[0], "rb") as f:
        assert f.read() == sounds.render_wav(START_CUE)


def test_runner_failure_disables_sounds_not_the_app():
    """A broken afplay must follow the existing one-failure-goes-quiet rule."""
    def boom(path):
        raise RuntimeError("afplay exploded")

    backend = AfplayBackend(runner=boom, which=lambda name: "/usr/bin/afplay")
    s = Sounds(enabled_provider=lambda: True, backend=backend,
               spawn=lambda fn: fn())    # synchronous for the test
    s.start_cue()                        # must not raise
    assert s._available is False
    s.stop_cue()                         # silent, still no raise


def test_default_backend_on_darwin_prefers_afplay(monkeypatch):
    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setattr(sounds.shutil, "which",
                        lambda name: "/usr/bin/afplay" if name == "afplay" else None)
    assert isinstance(sounds.default_backend(), AfplayBackend)


def test_default_backend_on_darwin_without_afplay_is_silent(monkeypatch):
    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setattr(sounds.shutil, "which", lambda name: None)
    assert isinstance(sounds.default_backend(), sounds.NullBackend)


def test_windows_preference_is_unchanged(monkeypatch):
    """On non-darwin the chain is Sine -> Null (regression guard: the platform
    split must not have rerouted Windows through afplay)."""
    monkeypatch.setattr(sys, "platform", "win32")
    backend = sounds.default_backend()
    assert not isinstance(backend, AfplayBackend)


# --------------------------------------------------------------------- volume
def test_afplay_backend_reads_volume_live_on_every_cue():
    """macOS gets the same live volume as Windows — one shared render path."""
    def peak(path):
        with wave.open(path, "rb") as w:
            s = array.array("h")
            s.frombytes(w.readframes(w.getnframes()))
        return max(abs(x) for x in s)

    level = {"v": VOLUME_SOFT}
    played = []
    backend = AfplayBackend(runner=played.append,
                            which=lambda name: "/usr/bin/afplay",
                            amplitude=lambda: level["v"])
    backend.play(START_CUE)
    level["v"] = VOLUME_LOUD
    backend.play(START_CUE)           # same cue, new volume -> a new file
    assert played[0] != played[1]
    assert peak(played[0]) < peak(played[1])


def test_afplay_cue_files_still_cache_at_a_steady_volume():
    played = []
    backend = AfplayBackend(runner=played.append,
                            which=lambda name: "/usr/bin/afplay",
                            amplitude=lambda: VOLUME_SOFT)
    backend.play(START_CUE)
    backend.play(START_CUE)
    assert played[0] == played[1]


def test_afplay_missing_volume_falls_back_to_the_default():
    played = []
    AfplayBackend(runner=played.append, which=lambda name: "/usr/bin/afplay",
                  amplitude=lambda: None).play(START_CUE)
    with open(played[0], "rb") as f:
        assert f.read() == sounds.render_wav(START_CUE, amplitude=_AMPLITUDE)
