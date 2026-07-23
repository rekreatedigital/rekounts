"""Tests for the pure helpers in transcriber.py (no model load required)."""
import os
import sys
import types

from rekounts.transcriber import (
    _register_cuda_dlls,
    is_hallucination,
    join_segments,
    resolve_model_id,
)


def test_bare_thank_you_is_hallucination():
    assert is_hallucination("Thank you.") is True
    assert is_hallucination("thank you") is True
    assert is_hallucination("  Thanks for watching!  ") is True


def test_punctuation_and_glyphs_stripped_before_match():
    assert is_hallucination("♪ Thank you ♪") is True
    assert is_hallucination('"Thank you."') is True
    assert is_hallucination("Thank  you") is True   # double space collapses


def test_real_sentence_starting_with_phrase_is_kept():
    assert is_hallucination("Thank you for the report you sent me.") is False
    assert is_hallucination("Bye week is next week for the team.") is False


def test_normal_dictation_is_not_hallucination():
    assert is_hallucination("Let's schedule the meeting for Tuesday.") is False


def test_empty_is_not_flagged_as_hallucination():
    # empty/no-speech is handled by a separate notice, not the blocklist
    assert is_hallucination("") is False
    assert is_hallucination("   ") is False
    assert is_hallucination(None) is False


# ---------------------------------------------------------------- segment join
# With condition_on_previous_text=False each segment is punctuated in
# isolation, so the seam between two segments can lose its sentence break.

def test_join_inserts_missing_period_before_new_sentence():
    assert (join_segments(["so that's done", "Now the next part"])
            == "so that's done. Now the next part")


def test_join_trusts_existing_punctuation():
    assert (join_segments(["Hello there.", "How are you?"])
            == "Hello there. How are you?")
    assert (join_segments(["we could go,", "and then eat"])
            == "we could go, and then eat")


def test_join_lowercase_continuation_stays_a_plain_join():
    assert join_segments(["and then we", "went home"]) == "and then we went home"


def test_join_capital_I_is_no_sentence_evidence():
    # "I" is capitalized wherever it sits — a run-on is better than a false split
    assert (join_segments(["and then", "I think we should"])
            == "and then I think we should")
    assert join_segments(["and then", "I'm off"]) == "and then I'm off"


def test_join_stutter_seam_is_left_for_the_repeat_collapse():
    # the right side restarts the left side's words: that's a stutter for the
    # cleaner's repeat collapse, and a period here would hide it from that pass
    assert (join_segments(["and at the", "At the same time"])
            == "and at the At the same time")


def test_join_skips_empty_segments():
    assert join_segments(["", "  ", "Hello."]) == "Hello."


def test_join_single_and_none():
    assert join_segments(["Hello."]) == "Hello."
    assert join_segments([]) == ""


def test_join_ellipsis_end_is_punctuated_enough():
    assert join_segments(["I wonder…", "Maybe"]) == "I wonder… Maybe"


# ------------------------------------------------------------ resolve_model_id
def test_builtin_model_names_pass_through_unchanged():
    # faster-whisper already knows these, so we must not rewrite them.
    for name in ("base", "small", "medium", "large-v3", "distil-large-v3"):
        assert resolve_model_id(name) == name


def test_turbo_aliases_map_to_a_pinned_ct2_repo():
    repo = "deepdml/faster-whisper-large-v3-turbo-ct2"
    assert resolve_model_id("large-v3-turbo") == repo
    assert resolve_model_id("turbo") == repo


def test_alias_lookup_tolerates_surrounding_whitespace():
    assert resolve_model_id("  large-v3-turbo ") == \
        "deepdml/faster-whisper-large-v3-turbo-ct2"


def test_unknown_names_pass_through_so_raw_repo_ids_still_work():
    assert resolve_model_id("some-org/custom-ct2-model") == \
        "some-org/custom-ct2-model"
    assert resolve_model_id("") == ""


# -------------------------------------------------------- _register_cuda_dlls
# Regression cover for a bug that silently disabled GPU entirely: `nvidia` is a
# namespace package (__file__ is None), and ctranslate2 loads cuBLAS lazily via
# plain LoadLibrary, which ignores os.add_dll_directory - so PATH is what
# actually matters.
def _fake_nvidia(tmp_path, subdirs):
    mod = types.ModuleType("nvidia")
    mod.__path__ = [str(tmp_path)]
    mod.__file__ = None          # exactly what a namespace package looks like
    for sub in subdirs:
        (tmp_path / sub / "bin").mkdir(parents=True)
    return mod


def test_registers_cuda_dirs_on_path_despite_namespace_package(tmp_path,
                                                               monkeypatch):
    monkeypatch.setitem(sys.modules, "nvidia",
                        _fake_nvidia(tmp_path, ["cublas", "cudnn"]))
    monkeypatch.setenv("PATH", "/pre-existing")
    _register_cuda_dlls()
    path = os.environ["PATH"]
    assert str(tmp_path / "cublas" / "bin") in path
    assert str(tmp_path / "cudnn" / "bin") in path
    assert "/pre-existing" in path       # never clobber the inherited PATH


def test_only_existing_subdirs_are_registered(tmp_path, monkeypatch):
    monkeypatch.setitem(sys.modules, "nvidia",
                        _fake_nvidia(tmp_path, ["cublas"]))
    monkeypatch.setenv("PATH", "")
    _register_cuda_dlls()
    assert str(tmp_path / "cublas" / "bin") in os.environ["PATH"]
    assert "cudnn" not in os.environ["PATH"]


def test_no_nvidia_package_is_a_safe_noop(monkeypatch):
    """CPU-only installs: must not raise and must not touch PATH."""
    monkeypatch.setitem(sys.modules, "nvidia", None)  # import nvidia -> raises
    monkeypatch.setenv("PATH", "/unchanged")
    _register_cuda_dlls()
    assert os.environ["PATH"] == "/unchanged"
