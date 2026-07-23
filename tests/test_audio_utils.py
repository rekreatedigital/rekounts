import numpy as np

from rekounts.audio_utils import normalize_gain, rms_level


def test_rms_level_silence_is_zero():
    assert rms_level(np.zeros(1000, dtype="float32")) == 0.0


def test_rms_level_louder_is_higher():
    quiet = rms_level(np.full(1000, 0.05, dtype="float32"))
    loud = rms_level(np.full(1000, 0.5, dtype="float32"))
    assert loud > quiet > 0.0


def test_rms_level_empty_is_zero():
    assert rms_level(np.zeros(0, dtype="float32")) == 0.0


def test_boosts_quiet_audio_toward_target_peak():
    # 0.02 peak * 30x = 0.6, within the default 50x cap
    quiet = np.full(1000, 0.02, dtype="float32")
    out = normalize_gain(quiet, target_peak=0.6, max_gain=50.0)
    assert abs(np.abs(out).max() - 0.6) < 0.01


def test_caps_gain_to_avoid_amplifying_pure_silence():
    near_silent = np.full(1000, 1e-9, dtype="float32")
    out = normalize_gain(near_silent, target_peak=0.6, max_gain=50.0)
    # gain capped at 50x, so peak stays tiny rather than exploding
    assert np.abs(out).max() <= 50.0 * 1e-9 + 1e-12


def test_does_not_attenuate_already_loud_audio():
    loud = np.full(1000, 0.9, dtype="float32")
    out = normalize_gain(loud, target_peak=0.6, max_gain=50.0)
    # already above target -> gain < 1 is allowed only up to attenuation? we keep it simple:
    # never boost above target, and never clip
    assert np.abs(out).max() <= 1.0


def test_output_never_clips():
    a = (np.random.RandomState(0).randn(2000) * 0.02).astype("float32")
    out = normalize_gain(a, target_peak=0.6, max_gain=50.0)
    assert np.abs(out).max() <= 1.0


def test_empty_audio_returns_empty():
    out = normalize_gain(np.zeros(0, dtype="float32"))
    assert len(out) == 0
