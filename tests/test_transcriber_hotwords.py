"""Dictionary words -> Whisper hotword biasing, and the offline-first loader.

No real model is loaded anywhere here: Transcriber instances are built with
object.__new__ and given a fake model, so these run in milliseconds.
"""
import numpy as np
import pytest

from rekounts.transcriber import (
    MAX_HOTWORDS,
    Transcriber,
    format_hotwords,
    load_model_offline_first,
)


class FakeSegment:
    def __init__(self, text):
        self.text = text


class FakeModel:
    """Records the kwargs of every transcribe() call."""

    def __init__(self, text="hello world"):
        self.text = text
        self.calls = []

    def transcribe(self, audio, **kwargs):
        self.calls.append(kwargs)
        return [FakeSegment(self.text)], None


def make_transcriber(provider=None, text="hello world"):
    t = object.__new__(Transcriber)
    t.language = "en"
    t.beam_size = 5
    t.hotwords_provider = provider
    t.device = "cpu"
    import threading
    t._lock = threading.Lock()
    t.model = FakeModel(text)
    return t


AUDIO = np.zeros(16000, dtype="float32")


# ------------------------------------------------------------ prompt building
def test_empty_dictionary_produces_no_prompt():
    assert format_hotwords([]) is None
    assert format_hotwords(None) is None
    assert format_hotwords(["", "   "]) is None


def test_prompt_is_a_glossary_line():
    assert format_hotwords(["Kubernetes", "Grafana"]) == "Glossary: Kubernetes, Grafana."


def test_prompt_dedupes_case_insensitively_keeping_first_spelling():
    assert format_hotwords(["Grafana", "grafana", "GRAFANA"]) == "Glossary: Grafana."


def test_prompt_trims_and_drops_junk_entries():
    assert format_hotwords(["  Grafana  ", None, 7, "", "Loki"]) == \
        "Glossary: Grafana, Loki."


def test_commas_inside_a_word_cannot_break_the_list():
    # A comma separates entries in the prompt, so it can't survive inside one.
    assert format_hotwords(["Smith, Jones"]) == "Glossary: Smith Jones."


def test_word_count_is_capped():
    prompt = format_hotwords([f"word{i}" for i in range(MAX_HOTWORDS + 20)])
    assert prompt.count(",") + 1 <= MAX_HOTWORDS


def test_total_length_is_capped():
    prompt = format_hotwords(["averyverylongtermindeed%d" % i for i in range(200)])
    assert len(prompt) < 400


# --------------------------------------------------------- transcribe() wiring
def test_no_provider_means_todays_behaviour_exactly():
    t = make_transcriber()
    t.transcribe(AUDIO)
    kwargs = t.model.calls[0]
    assert kwargs["hotwords"] is None          # faster-whisper's own default
    assert kwargs["beam_size"] == 5
    assert kwargs["vad_filter"] is True
    assert kwargs["condition_on_previous_text"] is False


def test_empty_word_list_means_todays_behaviour_exactly():
    t = make_transcriber(provider=lambda: [])
    t.transcribe(AUDIO)
    assert t.model.calls[0]["hotwords"] is None


def test_words_reach_the_model_as_hotwords():
    t = make_transcriber(provider=lambda: ["Kubernetes"])
    t.transcribe(AUDIO)
    assert t.model.calls[0]["hotwords"] == "Glossary: Kubernetes."


def test_provider_is_re_read_on_every_call():
    words = ["Grafana"]
    t = make_transcriber(provider=lambda: list(words))
    t.transcribe(AUDIO)
    words.append("Loki")          # user adds a word in the dashboard
    t.transcribe(AUDIO)
    assert t.model.calls[0]["hotwords"] == "Glossary: Grafana."
    assert t.model.calls[1]["hotwords"] == "Glossary: Grafana, Loki."


def test_setter_installs_and_clears_the_provider():
    t = make_transcriber()
    t.set_hotwords_provider(lambda: ["Loki"])
    t.transcribe(AUDIO)
    t.set_hotwords_provider(None)
    t.transcribe(AUDIO)
    assert t.model.calls[0]["hotwords"] == "Glossary: Loki."
    assert t.model.calls[1]["hotwords"] is None


def test_broken_provider_never_costs_the_user_their_dictation():
    def boom():
        raise RuntimeError("db gone")

    t = make_transcriber(provider=boom)
    assert t.transcribe(AUDIO) == "hello world"
    assert t.model.calls[0]["hotwords"] is None


def test_empty_audio_short_circuits_without_calling_the_model():
    t = make_transcriber(provider=lambda: ["Loki"])
    assert t.transcribe(np.array([], dtype="float32")) == ""
    assert t.transcribe(None) == ""
    assert t.model.calls == []


# ------------------------------------------------------------- prompt echo
def test_prompt_echoed_back_verbatim_is_dropped():
    t = make_transcriber(provider=lambda: ["Grafana", "Loki"],
                         text="Glossary: Grafana, Loki.")
    assert t.transcribe(AUDIO) == ""


def test_dictating_a_single_dictionary_word_still_works():
    # The obvious way to test the feature by hand - it must never be suppressed.
    t = make_transcriber(provider=lambda: ["Grafana", "Loki"], text="Grafana")
    assert t.transcribe(AUDIO) == "Grafana"


def test_echo_guard_is_inert_without_hotwords():
    t = make_transcriber(text="Glossary: Grafana, Loki.")
    assert t.transcribe(AUDIO) == "Glossary: Grafana, Loki."


# ------------------------------------------------------------ offline-ONLY loading
# Model delivery moved out of faster-whisper and into rekounts/models.py (our
# own host + Hugging Face-cache migration), so the loader here is handed an
# already-populated local directory. These tests pin the guarantee that follows:
# a load is offline-only, and there is no code path left that could download.
class RecordingLoader:
    """Stands in for WhisperModel; optionally fails the local-only attempt."""

    def __init__(self, fail_local=False):
        self.fail_local = fail_local
        self.calls = []

    def __call__(self, name, device=None, compute_type=None, local_files_only=False):
        self.calls.append(dict(name=name, device=device, compute_type=compute_type,
                               local_files_only=local_files_only))
        if local_files_only and self.fail_local:
            raise OSError("not cached")
        return "model:%s" % name


def test_warm_cache_loads_locally_and_never_asks_the_network():
    loader = RecordingLoader()
    assert load_model_offline_first("small", "cpu", "int8", loader) == "model:small"
    assert len(loader.calls) == 1
    assert loader.calls[0]["local_files_only"] is True


def test_a_local_directory_is_passed_through_verbatim(tmp_path):
    """Production passes an absolute directory from models.ensure_model(); given
    a directory faster-whisper uses it as-is and cannot reach the hub."""
    loader = RecordingLoader()
    model_dir = tmp_path / "base"
    model_dir.mkdir()
    load_model_offline_first(str(model_dir), "cpu", "int8", loader)
    assert loader.calls[0]["name"] == str(model_dir)
    assert loader.calls[0]["local_files_only"] is True


def test_a_failed_local_load_never_retries_with_downloads_enabled():
    """The old behavior fell back to a downloading load, which is exactly the
    huggingface.co contact this app must never make. A local failure now
    propagates (Transcriber.__init__ retries on CPU — itself still offline)."""
    loader = RecordingLoader(fail_local=True)
    with pytest.raises(OSError):
        load_model_offline_first("small", "cpu", "int8", loader)
    assert len(loader.calls) == 1
    assert loader.calls[0]["local_files_only"] is True
    assert not any(c["local_files_only"] is False for c in loader.calls)


def test_cuda_probe_subprocess_is_offline_only_too():
    from rekounts.transcriber import _PROBE_CODE
    code = _PROBE_CODE.format(name=r"C:\models\base")
    compile(code, "<probe>", "exec")               # it must be valid Python
    assert "local_files_only=True" in code
    # No except-branch reload: the probe must not be able to download either.
    assert "except" not in code
