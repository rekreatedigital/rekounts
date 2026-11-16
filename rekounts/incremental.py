"""Prepare long dictations locally while recording; deliver text only on stop.

There is one worker per recording and no inference queue. Audio stays in the
recorder until stop, so a failed speculative decode can fall back to the full
clip. A slow worker finishes at most its current piece, then the final pass
decodes the remaining audio together. Silence boundaries never discard samples.
"""
from collections import deque
import logging
import threading

import numpy as np

from rekounts.audio_utils import normalize_gain

log = logging.getLogger(__name__)
SAMPLE_RATE = 16000
MIN_CHUNK_SAMPLES = 15 * SAMPLE_RATE
LOOKBACK_SAMPLES = 30 * SAMPLE_RATE
PAUSE_LOOKAHEAD = int(0.8 * SAMPLE_RATE)


def find_pause(audio, *, minimum_samples=MIN_CHUNK_SAMPLES, vad=None):
    """Find a padded speech boundary with enough following audio to trust it.

Use the same quiet-speech threshold as transcription, with a slightly longer
pause requirement. Never force a cut in continuous speech to meet a time limit.
The final 800 ms is provisional: the VAD can end an unfinished speech interval
at the end of its input, which is not evidence of a real pause.
"""
    if len(audio) < minimum_samples + PAUSE_LOOKAHEAD:
        return None
    if vad is None:
        from faster_whisper.vad import get_speech_timestamps
        vad = get_speech_timestamps
    speeches = vad(normalize_gain(audio), threshold=0.3,
                   min_silence_duration_ms=700, speech_pad_ms=400)
    for i, speech in enumerate(speeches):
        end = max(minimum_samples, speech["end"])
        following = (speeches[i + 1]["start"] if i + 1 < len(speeches)
                     else len(audio) - PAUSE_LOOKAHEAD)
        if end <= following and end <= len(audio) - PAUSE_LOOKAHEAD:
            return end
    return None


def _tail(frames, size):
    """Copy only the bounded VAD window, even after a long unbroken sentence."""
    parts = []
    for frame in reversed(frames):
        part = frame[-size:]
        parts.append(part)
        size -= len(part)
        if size <= 0:
            break
    return np.concatenate(parts[::-1])


def _take(frames, size):
    parts = []
    while size:
        frame = frames.popleft()
        parts.append(frame[:size])
        if len(frame) > size:
            frames.appendleft(frame[size:])
        size -= len(parts[-1])
    return np.concatenate(parts)


class BackgroundTranscription:
    def __init__(self, recorder, transcriber, *, pause_finder=None,
                 poll_seconds=0.25):
        self.recorder = recorder
        self.transcriber = transcriber
        self.options = transcriber.decode_options()
        self.segments = []
        self.completed_samples = 0
        self._failed = False
        self._stop = threading.Event()
        self._cancel = threading.Event()
        self._results_lock = threading.Lock()
        self._pause_finder = pause_finder
        self._poll_seconds = poll_seconds
        self._thread = threading.Thread(target=self._run, daemon=True,
                                        name="dictation-prepare")

    def start(self):
        self._thread.start()

    def stop(self):
        self._stop.set()

    def join(self):
        self._thread.join()

    def cancel(self):
        self._cancel.set()
        self.stop()
        with self._results_lock:
            self.segments.clear()
            self.completed_samples = 0

    def _run(self):
        frames = deque()
        offset = pending_samples = checked_samples = 0
        try:
            while not self._stop.wait(self._poll_seconds):
                new, offset = self.recorder.read_frames(offset)
                for frame in new:
                    flat = frame.reshape(-1)
                    frames.append(flat)
                    pending_samples += len(flat)
                if (pending_samples < MIN_CHUNK_SAMPLES + PAUSE_LOOKAHEAD
                        or pending_samples - checked_samples < SAMPLE_RATE):
                    continue
                checked_samples = pending_samples
                window = _tail(frames, LOOKBACK_SAMPLES)
                window_start = pending_samples - len(window)
                if self._pause_finder is None:
                    split = find_pause(window, minimum_samples=max(
                        0, MIN_CHUNK_SAMPLES - window_start))
                else:
                    split = self._pause_finder(window)
                if split is None or self._stop.is_set():
                    continue
                split += window_start
                if not 0 < split <= pending_samples:
                    raise ValueError("Invalid audio boundary")
                audio = normalize_gain(_take(frames, split))
                segments = self.transcriber.decode_segments(
                    audio, self.options, cancel=self._cancel)
                with self._results_lock:
                    if self._cancel.is_set():
                        return
                    self.segments.extend(segments)
                    self.completed_samples += split
                pending_samples -= split
                checked_samples = 0
        except Exception as error:
            if not self._cancel.is_set():
                self._failed = True
                # Exceptions can quote recognized words. Log the type only.
                log.warning("Background transcription unavailable (%s); "
                            "will decode the full recording", type(error).__name__)

    def finish(self, audio):
        """Drain the current inference, decode the tail, and filter once."""
        self.stop()
        self.join()
        if self._cancel.is_set():
            return ""
        options = self.transcriber.decode_options()
        if self._failed or options != self.options:
            # Settings changed mid-recording: one consistent, current decode.
            self.segments.clear()
            self.completed_samples = 0
        tail = audio[self.completed_samples:]
        if len(tail):
            self.segments.extend(self.transcriber.decode_segments(
                normalize_gain(tail), options))
        try:
            return self.transcriber.finalize_segments(self.segments, options)
        finally:
            self.segments.clear()
