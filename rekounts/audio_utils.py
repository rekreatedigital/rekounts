import numpy as np


def rms_level(audio) -> float:
    """Root-mean-square amplitude of an audio buffer (0.0 for empty)."""
    if audio is None or len(audio) == 0:
        return 0.0
    return float(np.sqrt(np.mean(np.square(audio, dtype="float64"))))


def normalize_gain(audio: np.ndarray, target_peak: float = 0.6,
                   max_gain: float = 50.0) -> np.ndarray:
    """Boost quiet audio toward a target peak so a low-gain microphone still
    survives Whisper's VAD.

    - Scales so the loudest sample approaches ``target_peak``.
    - Gain is capped at ``max_gain`` so near-silence isn't blown up into noise.
    - Never boosts already-loud audio past the target, and always clips to
      [-1, 1] so the result can't distort the codec.
    """
    if audio is None or len(audio) == 0:
        return audio if audio is not None else np.zeros(0, dtype="float32")
    peak = float(np.abs(audio).max())
    if peak <= 0.0:
        return audio
    gain = min(target_peak / peak, max_gain)
    # don't attenuate audio that's already at/above the target
    gain = max(gain, 1.0) if peak < target_peak else 1.0
    return np.clip(audio * gain, -1.0, 1.0).astype("float32")
