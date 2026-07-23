import threading
from collections import deque

import numpy as np
import sounddevice as sd

from rekounts.device_utils import resolve_input_device

SAMPLE_RATE = 16000  # faster-whisper expects 16 kHz mono


def _resolve(name):
    """Resolve a mic NAME to a device index.

    The host-API table is passed along when the backend exposes one: it lets
    device_utils prefer the DirectSound copy of an endpoint over the MME/WASAPI/
    WDM-KS duplicates (only DirectSound and MME can capture at our 16 kHz) and
    refuse to open ASIO or pseudo devices.
    """
    try:
        hostapis = [dict(h) for h in sd.query_hostapis()]
    except Exception:
        hostapis = None
    return resolve_input_device(name, sd.query_devices(), hostapis)


class AudioRecorder:
    """Captures microphone audio for a dictation.

    Two capture modes:

    * Legacy (``preroll_seconds <= 0``): a fresh input stream is opened on
      ``start()`` and closed on ``stop()`` - the mic is only held while
      recording.
    * Pre-roll (``preroll_seconds > 0``): the input stream is kept open
      continuously and the most recent ``preroll_seconds`` of audio are held in
      a bounded, RAM-only ring buffer. ``start()`` seeds the recording with that
      buffer so the first syllable isn't clipped. The buffered audio is never
      written to disk and is dropped on ``close()``. Keeping the stream open
      means the OS mic-in-use indicator stays lit, so pre-roll is opt-in.

    The device name is re-resolved on every ``start()`` (and, in pre-roll mode,
    the stream is reopened if the resolved device changed) so live settings
    changes take effect on the next recording without recreating the recorder.
    """

    def __init__(self, device=None, sample_rate=SAMPLE_RATE, preroll_seconds=0.0,
                 device_provider=None):
        # `device` is a static device NAME (str) or None (system default).
        # `device_provider`, if given, is a callable returning the *current*
        # configured device name; it wins over `device` so settings changes are
        # picked up on the next start() without rebuilding the recorder.
        self._device = device
        self._device_provider = device_provider
        self.sample_rate = sample_rate
        self.preroll_seconds = max(0.0, float(preroll_seconds or 0.0))

        self._lock = threading.Lock()
        self._frames = []            # frames for the in-progress recording
        self._recording = False
        self._stream = None
        self._open_device_index = None  # device index the open stream uses

        # Bounded ring buffer of recent chunks (pre-roll). RAM only.
        self._preroll = deque()
        self._preroll_samples = 0

        # Resolve once up front so fell_back_to_default is meaningful before the
        # first start() (the controller reads it to warn about a missing mic).
        self.device_name = self._resolve_name()
        self._device_index = _resolve(self.device_name)
        self.fell_back_to_default = self.device_name is not None and self._device_index is None

    # --- device resolution -------------------------------------------------
    def _resolve_name(self):
        if self._device_provider is not None:
            try:
                return self._device_provider()
            except Exception:
                pass
        return self._device

    def _resolve_device(self):
        """Re-resolve the configured device NAME to an index. Cheap; called on
        every start() so device/settings changes take effect."""
        name = self._resolve_name()
        self.device_name = name
        idx = _resolve(name)
        self._device_index = idx
        self.fell_back_to_default = name is not None and idx is None
        return idx

    # --- stream plumbing ---------------------------------------------------
    def _callback(self, indata, frames, time, status):
        chunk = indata.copy()
        with self._lock:
            if self._recording:
                self._frames.append(chunk)
            if self.preroll_seconds > 0:
                self._preroll.append(chunk)
                self._preroll_samples += len(chunk)
                max_samples = int(self.preroll_seconds * self.sample_rate)
                # Trim from the front but keep at least `max_samples` retained.
                while (self._preroll
                       and self._preroll_samples - len(self._preroll[0]) >= max_samples):
                    self._preroll_samples -= len(self._preroll.popleft())

    def _open_stream(self, idx):
        self._close_stream()
        self._stream = sd.InputStream(
            samplerate=self.sample_rate, channels=1, dtype="float32",
            device=idx, callback=self._callback,
        )
        self._open_device_index = idx
        self._stream.start()

    def _close_stream(self):
        if self._stream is not None:
            try:
                self._stream.stop()
                self._stream.close()
            except Exception:
                pass
        self._stream = None
        self._open_device_index = None

    def arm(self) -> None:
        """Open the continuous input stream so pre-roll audio is buffered before
        the user starts a recording. Idempotent; a no-op when pre-roll is off.
        Call once at startup so even the first dictation has pre-roll."""
        if self.preroll_seconds <= 0:
            return
        idx = self._resolve_device()
        if self._stream is not None and self._open_device_index == idx:
            return
        self._open_stream(idx)

    # --- recording ---------------------------------------------------------
    def start(self) -> None:
        idx = self._resolve_device()
        if self.preroll_seconds > 0:
            # Ensure the continuous stream is open on the right device, then seed
            # the recording with whatever pre-roll we've buffered so far.
            if self._stream is None or self._open_device_index != idx:
                self._open_stream(idx)
            with self._lock:
                self._frames = list(self._preroll)
                self._recording = True
        else:
            with self._lock:
                self._frames = []
                self._recording = True
            self._open_stream(idx)

    def stop(self) -> np.ndarray:
        with self._lock:
            self._recording = False
            frames = self._frames
            self._frames = []
        # In pre-roll mode keep the stream open for the next recording; in legacy
        # mode release the mic as soon as we stop.
        if self.preroll_seconds <= 0:
            self._close_stream()
        if not frames:
            return np.zeros(0, dtype="float32")
        return np.concatenate(frames, axis=0).flatten()

    def close(self) -> None:
        """Fully release the mic and drop all buffered audio from RAM."""
        self._close_stream()
        with self._lock:
            self._recording = False
            self._frames = []
            self._preroll.clear()
            self._preroll_samples = 0

    def snapshot(self) -> np.ndarray:
        """Audio captured so far WITHOUT stopping the stream (for live preview)."""
        with self._lock:
            if not self._frames:
                return np.zeros(0, dtype="float32")
            return np.concatenate(list(self._frames), axis=0).flatten()

    def current_level(self, window_frames: int = 8) -> float:
        """RMS amplitude of the most recent captured chunks (0.0 if none).
        Cheap; used to drive the live level meter."""
        from rekounts.audio_utils import rms_level
        with self._lock:
            if not self._frames:
                return 0.0
            recent = np.concatenate(self._frames[-window_frames:], axis=0).flatten()
        return rms_level(recent)

    def duration(self, audio: np.ndarray) -> float:
        return len(audio) / self.sample_rate
