"""Tests for the pure scoring/dataset helpers in tools/asr_bench.py.

The heavy ML paths (run_config / _build_model) need faster-whisper + audio and
are exercised by hand via the CLI; here we lock down the maths and the dataset
loader, which are what a wrong benchmark number would come from.
"""
import importlib.util
import sys
from pathlib import Path

import pytest

# tools/ isn't an installed package, so load the module straight from its path.
_ASR_BENCH = Path(__file__).resolve().parent.parent / "tools" / "asr_bench.py"
_spec = importlib.util.spec_from_file_location("asr_bench", _ASR_BENCH)
asr_bench = importlib.util.module_from_spec(_spec)
# Register before exec: asr_bench uses `from __future__ import annotations`, and
# @dataclass resolves those string annotations via sys.modules[cls.__module__].
sys.modules["asr_bench"] = asr_bench
_spec.loader.exec_module(asr_bench)


# ------------------------------------------------------------- normalize_text
def test_normalize_folds_case_and_strips_punctuation():
    assert asr_bench.normalize_text("Tuesday, at 5 PM!") == "tuesday at 5 pm"


def test_normalize_collapses_whitespace():
    assert asr_bench.normalize_text("  hello   world \n there ") == "hello world there"


def test_normalize_handles_empty_and_none():
    assert asr_bench.normalize_text("") == ""
    assert asr_bench.normalize_text(None) == ""


# --------------------------------------------------------------- word_error_rate
def test_perfect_match_is_zero():
    assert asr_bench.word_error_rate("hello world", "hello world") == 0.0


def test_case_and_punctuation_do_not_count_as_errors():
    assert asr_bench.word_error_rate("Hello, world.", "hello world") == 0.0


def test_single_substitution():
    # one of two words wrong -> 0.5
    assert asr_bench.word_error_rate("hello world", "hello there") == 0.5


def test_deletion_and_insertion():
    # ref 3 words, hyp drops one -> one deletion / 3
    assert asr_bench.word_error_rate("a b c", "a c") == pytest.approx(1 / 3)
    # hyp adds one -> one insertion / 3
    assert asr_bench.word_error_rate("a b c", "a b c d") == pytest.approx(1 / 3)


def test_empty_reference_scores_by_hypothesis():
    assert asr_bench.word_error_rate("", "") == 0.0
    assert asr_bench.word_error_rate("", "anything here") == 1.0


def test_hallucination_can_exceed_one():
    # short reference, long spurious hypothesis -> WER > 1.0 on purpose
    assert asr_bench.word_error_rate("yes", "yes and a whole lot more text") > 1.0


# ------------------------------------------------------------------ tokenize
def test_tokenize_empty_is_empty_list():
    assert asr_bench.tokenize("   ") == []
    assert asr_bench.tokenize("one two") == ["one", "two"]


# --------------------------------------------------------------------- median
def test_median_odd_and_even():
    assert asr_bench._median([3, 1, 2]) == 2
    assert asr_bench._median([4, 1, 3, 2]) == 2.5
    assert asr_bench._median([]) == 0.0


# ------------------------------------------------------------------ load_dataset
def test_load_dataset_pairs_audio_with_reference(tmp_path):
    (tmp_path / "a.wav").write_bytes(b"RIFF")
    (tmp_path / "a.txt").write_text("hello there", encoding="utf-8")
    clips = asr_bench.load_dataset(tmp_path)
    assert len(clips) == 1
    assert clips[0].name == "a"
    assert clips[0].reference == "hello there"


def test_load_dataset_skips_audio_without_reference(tmp_path, capsys):
    (tmp_path / "a.wav").write_bytes(b"RIFF")
    (tmp_path / "a.txt").write_text("ok", encoding="utf-8")
    (tmp_path / "b.wav").write_bytes(b"RIFF")  # no b.txt
    clips = asr_bench.load_dataset(tmp_path)
    assert [c.name for c in clips] == ["a"]
    assert "skipping b.wav" in capsys.readouterr().err


def test_load_dataset_strips_utf8_bom_from_reference(tmp_path):
    (tmp_path / "a.wav").write_bytes(b"RIFF")
    (tmp_path / "a.txt").write_bytes(b"\xef\xbb\xbfwith bom")
    clips = asr_bench.load_dataset(tmp_path)
    assert clips[0].reference == "with bom"


def test_load_dataset_raises_when_no_pairs(tmp_path):
    (tmp_path / "loose.wav").write_bytes(b"RIFF")
    with pytest.raises(SystemExit):
        asr_bench.load_dataset(tmp_path)


def test_load_dataset_missing_folder_raises(tmp_path):
    with pytest.raises(SystemExit):
        asr_bench.load_dataset(tmp_path / "nope")


# ------------------------------------------------------------------- Config
def test_config_label_is_stable_and_descriptive():
    cfg = asr_bench.Config(model="small", device="cpu", beam_size=5,
                           language="en", vad=True)
    assert cfg.label() == "small/cpu/beam5/en/vad"


def test_config_label_auto_language_and_no_vad():
    cfg = asr_bench.Config(model="base", device="cuda", beam_size=1,
                           language=None, vad=False)
    assert cfg.label() == "base/cuda/beam1/auto/novad"


# --------------------------------------------------------- configs_from_args
def test_configs_from_args_sweeps_the_cross_product():
    args = asr_bench.parse_args(
        ["--data", "x", "--models", "base", "small",
         "--beam", "1", "5", "--language", "en", "auto"])
    configs = asr_bench.configs_from_args(args)
    # 2 models * 2 beams * 2 languages = 8
    assert len(configs) == 8
    assert any(c.model == "small" and c.beam_size == 5 and c.language is None
               for c in configs)
