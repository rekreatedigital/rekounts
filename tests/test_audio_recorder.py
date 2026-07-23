"""AudioRecorder tests with a fake sounddevice backend (no real hardware).

Exercises the pre-roll ring buffer and per-start device re-resolution without
touching PortAudio.
"""
import numpy as np
import pytest

import rekounts.audio_recorder as ar
from rekounts.audio_recorder import AudioRecorder


class FakeStream:
    def __init__(self, samplerate, channels, dtype, device, callback):
        self.callback = callback
        self.device = device
        self.started = False
        self.closed = False

    def start(self):
        self.started = True

    def stop(self):
        self.started = False

    def close(self):
        self.closed = True

    # helper for tests: push an audio chunk through the callback
    def feed(self, samples):
        chunk = np.full((samples, 1), 0.2, dtype="float32")
        self.callback(chunk, samples, None, None)


class FakeSd:
    def __init__(self, devices):
        self._devices = devices
        self.streams = []

    def query_devices(self):
        return self._devices

    def InputStream(self, **kw):
        s = FakeStream(**kw)
        self.streams.append(s)
        return s


DEVICES = [
    {"name": "Default Mic", "max_input_channels": 2},
    {"name": "USB Mic", "max_input_channels": 1},
    {"name": "Speakers", "max_input_channels": 0},
]


@pytest.fixture
def fake_sd(monkeypatch):
    sd = FakeSd(DEVICES)
    monkeypatch.setattr(ar, "sd", sd)
    return sd


def test_legacy_mode_opens_on_start_closes_on_stop(fake_sd):
    rec = AudioRecorder(device=None, preroll_seconds=0.0)
    assert fake_sd.streams == []          # nothing open until start
    rec.start()
    assert len(fake_sd.streams) == 1
    stream = fake_sd.streams[0]
    assert stream.started is True
    stream.feed(16000)
    audio = rec.stop()
    assert len(audio) == 16000
    assert stream.closed is True          # mic released on stop


def test_preroll_keeps_stream_open_and_seeds_recording(fake_sd):
    rec = AudioRecorder(device=None, preroll_seconds=0.5)  # 8000 samples @16k
    rec.arm()
    assert len(fake_sd.streams) == 1
    stream = fake_sd.streams[0]
    # buffer some pre-roll audio before "recording" starts
    stream.feed(4000)
    stream.feed(4000)
    rec.start()                           # should seed with buffered pre-roll
    stream.feed(4000)                     # live recording audio
    audio = rec.stop()
    # pre-roll (~8000, bounded) + 4000 live; at least the live + one pre-roll chunk
    assert len(audio) >= 8000
    assert stream.closed is False         # stream stays open for next dictation
    assert rec._stream is stream


def test_preroll_ring_buffer_is_bounded(fake_sd):
    rec = AudioRecorder(device=None, preroll_seconds=0.5)  # cap ~8000 samples
    rec.arm()
    stream = fake_sd.streams[0]
    for _ in range(20):                   # feed 20 * 2000 = 40000 samples
        stream.feed(2000)
    # ring buffer must not grow unbounded; stays close to the 8000 cap
    assert rec._preroll_samples <= 8000 + 2000


def test_start_reresolves_device_each_time(fake_sd):
    current = {"name": None}
    rec = AudioRecorder(device_provider=lambda: current["name"], preroll_seconds=0.0)
    rec.start()
    assert fake_sd.streams[-1].device is None      # system default
    rec.stop()
    current["name"] = "USB Mic"                     # user changes mic in settings
    rec.start()
    assert fake_sd.streams[-1].device == 1          # index of USB Mic, re-resolved
    rec.stop()


def test_missing_named_device_sets_fell_back_flag(fake_sd):
    rec = AudioRecorder(device="Nonexistent Mic", preroll_seconds=0.0)
    assert rec.fell_back_to_default is True
    rec.start()
    assert fake_sd.streams[-1].device is None       # falls back to default index
    rec.stop()


def test_close_releases_stream_and_clears_preroll(fake_sd):
    rec = AudioRecorder(device=None, preroll_seconds=0.5)
    rec.arm()
    fake_sd.streams[0].feed(4000)
    rec.close()
    assert fake_sd.streams[0].closed is True
    assert rec._preroll_samples == 0
    assert len(rec._preroll) == 0
