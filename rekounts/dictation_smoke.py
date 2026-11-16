"""Opt-in packaged pipeline check using a supplied public speech fixture.

Replays the fixture at real-time speed through the controller and background
worker. No microphone, keyboard injection, history, settings or network access.
The expected fixture is faster-whisper's public JFK sample, also used by the
existing native Mac check. Reports contain metrics, never recognized text.
"""
import argparse
import json
from pathlib import Path
import platform
import re
import threading
import time
from types import SimpleNamespace

import numpy as np


class ReplayRecorder:
    sample_rate = 16000

    def __init__(self):
        self.frames = []
        self.lock = threading.Lock()

    def start(self):
        self.frames = []

    def read_frames(self, offset):
        with self.lock:
            return self.frames[offset:], len(self.frames)

    def feed(self, frame):
        with self.lock:
            self.frames.append(frame)

    def stop(self):
        with self.lock:
            frames, self.frames = self.frames, []
        return np.concatenate(frames) if frames else np.zeros(0, dtype="float32")

    def duration(self, audio):
        return len(audio) / self.sample_rate


def run(model_dir, audio_file):
    from rekounts import __version__
    from rekounts.transcriber import Transcriber
    transcriber = Transcriber(str(model_dir), "cpu", "en", beam_size=5)
    transcriber.warm_up()
    from faster_whisper import decode_audio
    clip = decode_audio(str(audio_file), sampling_rate=16000)
    # Pauses provide deterministic safe boundaries; replay still uses the real
    # VAD and recognizer, not an injected split point or a fake model.
    audio = np.concatenate([np.concatenate([clip, np.zeros(16000, dtype="float32")])
                            for _ in range(3)])
    from rekounts.controller import AppController
    from rekounts.text_cleaner import TextCleaner
    recorder = ReplayRecorder()
    delivered, results, errors = [], [], []
    controller = AppController(
        recorder, transcriber, TextCleaner(),
        SimpleNamespace(insert=lambda text: delivered.append(text)),
        on_result=lambda *args: results.append(args), on_error=errors.append)
    assert controller.start_recording(), "Recording did not start"
    start = time.perf_counter()
    try:
        for position in range(0, len(audio), 1600):
            end = min(position + 1600, len(audio))
            time.sleep(max(0, start + end / 16000 - time.perf_counter()))
            recorder.feed(audio[position:end])
            assert not delivered and not results, "Text delivered before stop"
        controller.stop_recording()
        assert not errors, "Pipeline reported an error"
        assert len(delivered) == len(results) == 1, "Expected one complete delivery"
        words = re.findall(r"[a-z]+", results[0][0].lower())
        assert words.count("country") >= 3 and words.count("ask") >= 3, "Speech is incomplete"
        assert controller.last_timings["prepared_audio_s"] >= 15, "Background decode did not run"
        assert controller.sm.state.name == "IDLE", "Pipeline did not return to idle"
        return {"status": "passed", "version": __version__,
                "platform": platform.system(), "architecture": platform.machine(),
                "device": transcriber.device, "deliveries": len(delivered),
                **controller.last_timings}
    finally:
        controller.cancel_recording()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model-dir", type=Path, required=True)
    parser.add_argument("--audio-file", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args(argv)
    report = run(args.model_dir, args.audio_file)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2), flush=True)
    return 0
