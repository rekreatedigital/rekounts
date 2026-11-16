"""Exercise the real worker/controller seam without a microphone or model."""
import threading
from types import SimpleNamespace

import numpy as np
import pytest

from rekounts.controller import AppController
from rekounts.incremental import BackgroundTranscription
from rekounts.text_cleaner import TextCleaner
from rekounts.transcriber import Transcriber


RATE = 16000


class Recorder:
    sample_rate = RATE

    def __init__(self):
        self.audio = np.ones(20 * RATE, dtype="float32")
        self.frames = []

    def start(self):
        self.frames = [self.audio]

    def read_frames(self, offset):
        return self.frames[offset:], len(self.frames)

    def stop(self):
        self.frames = []
        return self.audio

    def duration(self, audio):
        return len(audio) / RATE


def transcriber(text="Useful words."):
    trans = object.__new__(Transcriber)
    trans.language, trans.beam_size, trans.hotwords_provider = "en", 5, None
    trans._lock = threading.Lock()
    trans.calls = []
    trans.decoded = threading.Event()

    def decode(audio, **kwargs):
        trans.calls.append((len(audio), kwargs))
        trans.decoded.set()
        return [SimpleNamespace(text=text, no_speech_prob=0.01)], None

    trans.model = SimpleNamespace(transcribe=decode)
    return trans


@pytest.fixture
def setup(monkeypatch):
    def background(recorder, transcriber):
        return BackgroundTranscription(recorder, transcriber,
                                       pause_finder=lambda a: 16 * RATE,
                                       poll_seconds=0.001)

    monkeypatch.setattr("rekounts.controller.BackgroundTranscription", background)
    recorder, trans = Recorder(), transcriber()
    inserted, results, errors = [], [], []
    controller = AppController(
        recorder, trans, TextCleaner(collapse_repeats=False),
        SimpleNamespace(insert=lambda text: inserted.append(text)),
        on_result=lambda *args: results.append(args),
        on_error=errors.append)
    return SimpleNamespace(controller=controller, recorder=recorder, trans=trans,
                           inserted=inserted, results=results, errors=errors)


def test_background_never_delivers_until_stop_then_delivers_once(setup):
    s = setup
    assert s.controller.start_recording()
    assert s.trans.decoded.wait(2)
    assert s.inserted == [] and s.results == []
    s.controller.stop_recording()
    s.controller.stop_recording()
    assert s.inserted == ["Useful words. Useful words."]
    assert len(s.results) == 1
    assert s.results[0][2:] == (20, True)
    assert [n for n, _ in s.trans.calls] == [16 * RATE, 4 * RATE]
    assert s.controller.last_timings["prepared_audio_s"] == 16
    assert not s.errors


def test_cancel_then_new_recording_cannot_deliver_the_old_text(setup):
    s = setup
    s.controller.start_recording()
    assert s.trans.decoded.wait(2)
    s.controller.cancel_recording()
    assert s.inserted == [] and s.results == []
    s.controller.transcriber = transcriber("Fresh recording.")
    s.recorder.audio = np.ones(RATE, dtype="float32")
    assert s.controller.start_recording()
    s.controller.stop_recording()
    assert s.inserted == ["Fresh recording."]
    assert len(s.results) == 1 and not s.errors


def test_model_reload_during_recording_uses_new_model_for_the_full_clip(setup):
    s = setup
    s.controller.start_recording()
    assert s.trans.decoded.wait(2)
    replacement = transcriber("New model result.")
    s.controller.transcriber = replacement
    s.controller.stop_recording()
    assert s.inserted == ["New model result."]
    assert [n for n, _ in replacement.calls] == [20 * RATE]
    assert not s.errors


def test_auto_stop_finishes_the_same_background_session(setup):
    s = setup
    s.controller.start_recording()
    assert s.trans.decoded.wait(2)
    s.controller._auto_stop()
    assert len(s.inserted) == len(s.results) == 1
    assert not s.controller.is_recording()
    assert not s.errors


def test_short_tap_cancels_preparation_without_recognition(setup):
    s = setup
    s.recorder.audio = np.ones(100, dtype="float32")
    s.controller.start_recording()
    s.controller.stop_recording()
    assert not s.trans.calls
    assert not s.inserted and not s.results and not s.errors
