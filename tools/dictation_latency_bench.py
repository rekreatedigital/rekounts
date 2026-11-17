"""Replay local audio through the real background worker at microphone speed.

Usage: python -m tools.dictation_latency_bench --audio sample.wav
       --reference sample.txt --model C:/path/to/models/small --output report.json

Never uploads audio or transcripts. The JSON contains durations and word error
rates only. Unlike an accelerated chunk simulation, replay takes the recording's
actual duration and includes background inference still running at stop.
"""
import argparse
import json
from pathlib import Path
import threading
import time

import numpy as np

from rekounts.audio_utils import normalize_gain
from rekounts.incremental import BackgroundTranscription
from rekounts.transcriber import Transcriber
from tools.asr_bench import word_error_rate


class ReplayRecorder:
    def __init__(self):
        self.frames = []
        self.lock = threading.Lock()

    def read_frames(self, offset):
        with self.lock:
            return self.frames[offset:], len(self.frames)

    def append(self, frame):
        with self.lock:
            self.frames.append(frame)


def benchmark(audio, reference, transcriber):
    start = time.perf_counter()
    baseline = transcriber.transcribe(normalize_gain(audio))
    baseline_s = time.perf_counter() - start
    print(f"Whole clip: {baseline_s:.3f}s; starting real-time replay", flush=True)

    recorder = ReplayRecorder()
    session = BackgroundTranscription(recorder, transcriber)
    session.start()
    start = time.perf_counter()
    step = 1600  # 100 ms, including a shorter final block
    try:
        for position in range(0, len(audio), step):
            end = min(position + step, len(audio))
            time.sleep(max(0, start + end / 16000 - time.perf_counter()))
            recorder.append(audio[position:end])
        stopped = time.perf_counter()
        result = session.finish(audio)
        wait_s = time.perf_counter() - stopped
        prepared_s = session.completed_samples / 16000
    finally:
        session.cancel()
        session.join()
    return {
        "audio_s": len(audio) / 16000,
        "device": transcriber.device,
        "beam_size": transcriber.beam_size,
        "language": transcriber.language,
        "whole_clip_wait_s": baseline_s,
        "background_wait_s": wait_s,
        "prepared_audio_s": prepared_s,
        "whole_clip_wer": word_error_rate(reference, baseline),
        "background_wer": word_error_rate(reference, result),
        "word_difference_from_whole_clip": word_error_rate(baseline, result),
        "replay": "real_time",
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--audio", type=Path, required=True)
    parser.add_argument("--reference", type=Path, required=True)
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    from faster_whisper import decode_audio
    audio = decode_audio(str(args.audio), sampling_rate=16000)
    assert np.isfinite(audio).all(), "Invalid input audio"
    transcriber = Transcriber(str(args.model), device="cpu", language="en", beam_size=5)
    transcriber.warm_up()
    report = benchmark(audio, args.reference.read_text(encoding="utf-8"), transcriber)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2), flush=True)


if __name__ == "__main__":
    main()
