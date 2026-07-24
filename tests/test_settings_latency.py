"""Reproductions for "I changed a setting, dictated, and got the OLD setting".

Ryan's report: changed language + microphone, dictated immediately, and the
dictation ran with the previous settings. Each test here pins one concrete way
that could happen. They are written as reproductions first — every one of them
FAILS on the code as it stood before this branch.
"""
import numpy as np
import pytest

import rekounts.audio_recorder as ar
import rekounts.transcriber
from rekounts.audio_recorder import AudioRecorder
from rekounts.transcriber import Transcriber

from tests.test_audio_recorder import DEVICES, FakeSd


@pytest.fixture
def fake_sd(monkeypatch):
    sd = FakeSd(DEVICES)
    monkeypatch.setattr(ar, "sd", sd)
    return sd


# ----------------------------------------------------- 1. stale pre-roll audio
def test_mic_change_does_not_seed_the_next_recording_with_old_mic_audio(fake_sd):
    """Pre-roll + a mic change used to prepend OLD-microphone audio.

    In pre-roll mode start() seeds the recording from the ring buffer. The
    buffer survived a device switch, so the first `preroll_seconds` of the very
    next dictation were captured on the microphone the user had just moved AWAY
    from — audibly "it used the old mic".
    """
    mic = {"name": None}
    rec = AudioRecorder(device_provider=lambda: mic["name"], preroll_seconds=0.5)
    rec.arm()
    fake_sd.streams[0].feed(8000)         # half a second of OLD-mic audio
    assert rec._preroll_samples > 0

    mic["name"] = "USB Mic"               # user picks a different microphone
    rec.start()

    assert fake_sd.streams[-1].device == 1        # recording on the new mic
    audio = rec.stop()
    assert len(audio) == 0, "recording was seeded with audio from the old mic"


def test_reopening_the_stream_drops_the_pre_roll_buffer(fake_sd):
    """Any stream reopen is an audio discontinuity — the ring must not span it."""
    rec = AudioRecorder(device=None, preroll_seconds=0.5)
    rec.arm()
    fake_sd.streams[0].feed(4000)
    assert rec._preroll_samples == 4000

    rec._open_stream(1)
    assert rec._preroll_samples == 0
    assert len(rec._preroll) == 0


# ------------------------------------------ 2. mic applies while pre-roll armed
def test_resync_device_reopens_an_armed_stream_on_the_new_mic(fake_sd):
    """A mic change must reach the always-open pre-roll stream immediately.

    Without this the continuous stream kept buffering from the old microphone
    until the next start(), so the mic setting only really "took" one dictation
    later.
    """
    mic = {"name": None}
    rec = AudioRecorder(device_provider=lambda: mic["name"], preroll_seconds=0.5)
    rec.arm()
    assert fake_sd.streams[-1].device is None

    mic["name"] = "USB Mic"
    assert rec.resync_device() is True
    assert fake_sd.streams[-1].device == 1        # already on the new mic
    assert rec.resync_device() is False           # idempotent — no needless reopen


def test_resync_device_never_disturbs_a_recording_in_flight(fake_sd):
    """Swapping the stream mid-clip would truncate the user's dictation."""
    mic = {"name": None}
    rec = AudioRecorder(device_provider=lambda: mic["name"], preroll_seconds=0.5)
    rec.arm()
    rec.start()
    opened = len(fake_sd.streams)
    fake_sd.streams[-1].feed(4000)

    mic["name"] = "USB Mic"
    assert rec.resync_device() is False           # deferred, not applied
    assert len(fake_sd.streams) == opened
    assert len(rec.stop()) == 4000                # the clip survived intact


def test_resync_device_is_a_no_op_when_pre_roll_is_off(fake_sd):
    rec = AudioRecorder(device=None, preroll_seconds=0.0)
    assert rec.resync_device() is False
    assert fake_sd.streams == []                  # legacy mode holds no stream


# ---------------------------------------------------- 3. language read per call
class _FakeModel:
    """Records the kwargs faster-whisper would have been called with."""

    def __init__(self):
        self.calls = []

    def transcribe(self, audio, **kw):
        self.calls.append(kw)
        return iter([]), None


@pytest.fixture
def fake_model(monkeypatch):
    """Build REAL Transcribers whose only fake part is the whisper model."""
    model = _FakeModel()
    monkeypatch.setattr(rekounts.transcriber, "load_model_offline_first",
                        lambda *a, **kw: model)
    return model


def _transcriber(**kw):
    return Transcriber(model_name="small", device="cpu", **kw)


AUDIO = np.zeros(16000, dtype="float32")


def test_language_provider_is_read_on_every_transcribe(fake_model):
    """The whole point: no push, no debounce and no model reload can make the
    language stale, because nothing ever captures it."""
    lang = {"v": "en"}
    t = _transcriber(language="en", language_provider=lambda: lang["v"])

    t.transcribe(AUDIO)
    assert fake_model.calls[-1]["language"] == "en"

    lang["v"] = "fr"                      # user changes it in the Hub
    t.transcribe(AUDIO)
    assert fake_model.calls[-1]["language"] == "fr", "language was captured, not read"


def test_language_provider_maps_auto_to_none(fake_model):
    t = _transcriber(language="en", language_provider=lambda: "auto")
    t.transcribe(AUDIO)
    assert fake_model.calls[-1]["language"] is None


def test_beam_size_provider_is_read_on_every_transcribe(fake_model):
    beam = {"v": 5}
    t = _transcriber(language="en", beam_size_provider=lambda: beam["v"])
    t.transcribe(AUDIO)
    assert fake_model.calls[-1]["beam_size"] == 5
    beam["v"] = 1
    t.transcribe(AUDIO)
    assert fake_model.calls[-1]["beam_size"] == 1


def test_a_broken_provider_falls_back_instead_of_losing_the_dictation(fake_model):
    def boom():
        raise RuntimeError("config exploded")

    t = _transcriber(language="de", language_provider=boom)
    t.transcribe(AUDIO)
    assert fake_model.calls[-1]["language"] == "de"


def test_no_provider_keeps_the_plain_attribute_behaviour(fake_model):
    """Back-compat: the attribute is still the source of truth without a provider."""
    t = _transcriber(language="en")
    t.transcribe(AUDIO)
    assert fake_model.calls[-1]["language"] == "en"
    t.language = "it"
    t.transcribe(AUDIO)
    assert fake_model.calls[-1]["language"] == "it"
