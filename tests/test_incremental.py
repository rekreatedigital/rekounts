"""Long dictations prepare work in RAM without inserting partial text."""
import threading
from types import SimpleNamespace

import numpy as np
import pytest

from rekounts.incremental import BackgroundTranscription, find_pause


RATE = 16000


def test_split_is_inside_a_confirmed_pause_and_keeps_context():
    audio = np.ones(22 * RATE, dtype="float32")
    calls = []

    def vad(audio, **kwargs):
        calls.append(kwargs)
        return [{"start": 0, "end": 16 * RATE},
                {"start": 17 * RATE, "end": len(audio)}]

    assert find_pause(audio, vad=vad) == 16 * RATE
    assert calls[0]["threshold"] == 0.3


def test_continuous_speech_is_never_cut_at_a_time_limit():
    audio = np.ones(30 * RATE, dtype="float32")
    assert find_pause(audio, vad=lambda a, **k: [{"start": 0, "end": len(a)}]) is None


def test_unfinished_tail_is_not_mistaken_for_a_pause():
    audio = np.ones(20 * RATE, dtype="float32")
    assert find_pause(audio, vad=lambda a, **k: [
        {"start": 0, "end": len(a) - RATE // 10}]) is None


class Recorder:
    def __init__(self, audio):
        self.frames = [audio[:16 * RATE], audio[16 * RATE:]]

    def read_frames(self, offset):
        return self.frames[offset:], len(self.frames)


class Transcriber:
    def __init__(self):
        self.options = ("en", 5, None)
        self.calls = []
        self.decoded = threading.Event()
        self.finish_calls = []

    def decode_options(self):
        return self.options

    def decode_segments(self, audio, options, cancel=None):
        self.calls.append(audio.copy())
        self.decoded.set()
        return [SimpleNamespace(text="Words.", no_speech_prob=0.01)]

    def finalize_segments(self, segments, options):
        self.finish_calls.append(list(segments))
        return " ".join(s.text for s in segments)


def test_finished_prefix_is_not_decoded_again_and_every_sample_is_kept():
    # Already-loud audio makes gain normalization a no-op, so the exact seam
    # can be checked without relying on recognizer output or wall-clock speed.
    audio = np.linspace(0.6, 0.9, 20 * RATE, dtype="float32")
    trans = Transcriber()
    session = BackgroundTranscription(Recorder(audio), trans,
                                      pause_finder=lambda a: 16 * RATE,
                                      poll_seconds=0.001)
    session.start()
    assert trans.decoded.wait(2)
    result = session.finish(audio)
    assert result == "Words. Words."
    assert len(trans.calls) == 2
    np.testing.assert_array_equal(np.concatenate(trans.calls), audio)
    assert session.completed_samples == 16 * RATE
    assert len(trans.finish_calls) == 1  # filter only once, at the real end


def test_cancel_discards_inflight_results_without_waiting_for_inference():
    audio = np.ones(20 * RATE, dtype="float32")
    trans = Transcriber()
    release = threading.Event()

    def blocked(audio, options, cancel=None):
        trans.decoded.set()
        assert release.wait(2)
        return [SimpleNamespace(text="Cancelled words.")]

    trans.decode_segments = blocked
    session = BackgroundTranscription(Recorder(audio), trans,
                                      pause_finder=lambda a: 16 * RATE,
                                      poll_seconds=0.001)
    session.start()
    assert trans.decoded.wait(2)
    session.cancel()
    release.set()
    session.join()
    assert session.completed_samples == 0
    assert session.segments == []
    assert trans.finish_calls == []


def test_background_failure_falls_back_to_the_complete_recording(caplog):
    audio = np.ones(20 * RATE, dtype="float32")
    trans = Transcriber()

    def broken(*args, **kwargs):
        trans.decoded.set()
        raise RuntimeError("private words must not reach the log")

    trans.decode_segments = broken
    session = BackgroundTranscription(Recorder(audio), trans,
                                      pause_finder=lambda a: 16 * RATE,
                                      poll_seconds=0.001)
    session.start()
    assert trans.decoded.wait(2)
    session.stop()
    session.join()
    trans.decode_segments = Transcriber.decode_segments.__get__(trans)
    assert session.finish(audio) == "Words."
    assert len(trans.calls) == 1
    np.testing.assert_array_equal(trans.calls[0], audio)
    assert "private words" not in caplog.text
    assert "RuntimeError" in caplog.text


@pytest.mark.parametrize("options", [("tl", 5, None), ("en", 1, None),
                                    ("en", 5, "Glossary: Updated.")])
def test_changed_settings_discard_cached_decode_and_use_current_settings(options):
    audio = np.ones(20 * RATE, dtype="float32")
    trans = Transcriber()
    session = BackgroundTranscription(Recorder(audio), trans,
                                      pause_finder=lambda a: 16 * RATE,
                                      poll_seconds=0.001)
    session.start()
    assert trans.decoded.wait(2)
    session.stop()
    session.join()
    trans.options = options
    trans.calls.clear()
    assert session.finish(audio) == "Words."
    assert len(trans.calls) == 1
    np.testing.assert_array_equal(trans.calls[0], audio)


def test_slow_worker_stops_after_current_piece_and_decodes_backlog_once():
    audio = np.ones(65 * RATE, dtype="float32")
    recorder = Recorder(audio[:20 * RATE])
    trans = Transcriber()
    release = threading.Event()
    original = trans.decode_segments

    def slow(audio, options, cancel=None):
        if not trans.calls:
            trans.decoded.set()
            assert release.wait(2)
        return original(audio, options, cancel)

    trans.decode_segments = slow
    session = BackgroundTranscription(recorder, trans,
                                      pause_finder=lambda a: 16 * RATE,
                                      poll_seconds=0.001)
    session.start()
    assert trans.decoded.wait(2)
    recorder.frames.append(audio[20 * RATE:])
    session.stop()
    release.set()
    assert session.finish(audio) == "Words. Words."
    assert [len(a) // RATE for a in trans.calls] == [16, 49]


def test_voice_detector_only_copies_a_bounded_window(monkeypatch):
    audio = np.ones(90 * RATE, dtype="float32")
    recorder = Recorder(audio)
    trans = Transcriber()
    scanned = threading.Event()
    windows = []

    def pause(window):
        windows.append(len(window))
        scanned.set()
        return None

    session = BackgroundTranscription(recorder, trans, pause_finder=pause,
                                      poll_seconds=0.001)
    session.start()
    assert scanned.wait(2)
    session.cancel()
    session.join()
    assert windows == [30 * RATE]
    assert not trans.calls


def test_real_transcriber_filters_only_the_final_tail():
    from rekounts.transcriber import Transcriber as RealTranscriber
    trans = object.__new__(RealTranscriber)
    trans.language, trans.beam_size, trans.hotwords_provider = "en", 5, None
    trans._lock = threading.Lock()
    batches = iter([
        [SimpleNamespace(text="First sentence.", no_speech_prob=0.01),
         SimpleNamespace(text="Thank you.", no_speech_prob=0.99)],
        [SimpleNamespace(text="Next sentence.", no_speech_prob=0.02),
         SimpleNamespace(text="Thank you.", no_speech_prob=0.99)],
    ])
    trans.model = SimpleNamespace(transcribe=lambda a, **k: (next(batches), None))
    options = trans.decode_options()
    first = trans.decode_segments(np.ones(RATE, dtype="float32"), options)
    second = trans.decode_segments(np.ones(RATE, dtype="float32"), options)
    result = trans.finalize_segments(first + second, options)
    assert result == "First sentence. Thank you. Next sentence."
    assert result.no_speech_prob == 0.01


def test_cancelled_decode_does_not_enter_the_native_model():
    from rekounts.transcriber import Transcriber as RealTranscriber, TranscriptionCancelled
    trans = object.__new__(RealTranscriber)
    trans._lock = threading.Lock()
    cancelled = threading.Event()
    cancelled.set()
    with pytest.raises(TranscriptionCancelled):
        trans.decode_segments(np.ones(RATE, dtype="float32"), None, cancelled)
