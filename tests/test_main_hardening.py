"""Startup-hardening regressions for __main__ (wave-1 review findings 1-3).

These cover the pieces that used to live tangled inside _run(): the logging
crash guard, the notification buffer that stops early messages being dropped,
and the generation gate that stops a stale model reload winning a race. Each
helper is deliberately Qt-free so it can be tested without a QApplication.
"""
import logging
import threading

import pytest

from rekounts import __main__ as app_main
from rekounts import models
from rekounts.__main__ import (ModelReloadGate, NotificationBuffer,
                                  _apply_preroll, _attach_provider,
                                  _dictionary_providers, _make_sounds,
                                  _NullSounds, setup_logging)
from rekounts.hotkey_manager import HotkeyManager


@pytest.fixture
def preserve_root_logging():
    """setup_logging() calls logging.basicConfig, which mutates global state."""
    root = logging.getLogger()
    handlers, level = list(root.handlers), root.level
    yield
    root.handlers[:] = handlers
    root.setLevel(level)


# --- finding 1: setup_logging outside the crash guard ---------------------
def test_setup_logging_degrades_instead_of_raising(monkeypatch, preserve_root_logging):
    # A read-only / unavailable %APPDATA% used to raise straight out of main()
    # BEFORE the try/except, so under pythonw (no console) the app just never
    # appeared, with no dialog and no log to explain why.
    def boom():
        raise OSError("APPDATA is read-only")

    monkeypatch.setattr(app_main, "default_config_path", boom)
    assert setup_logging() is False        # degraded, but did not raise


def test_log_level_defaults_to_info(monkeypatch):
    monkeypatch.delenv("REKOUNTS_LOG_LEVEL", raising=False)
    assert app_main._log_level() == logging.INFO


def test_log_level_honours_the_env_var(monkeypatch):
    monkeypatch.setenv("REKOUNTS_LOG_LEVEL", "debug")   # case-insensitive
    assert app_main._log_level() == logging.DEBUG


def test_unknown_log_level_falls_back_to_info(monkeypatch):
    monkeypatch.setenv("REKOUNTS_LOG_LEVEL", "chatty")
    assert app_main._log_level() == logging.INFO


def test_setup_logging_failure_still_reaches_the_fatal_dialog(monkeypatch):
    # Belt and braces: even if setup_logging itself dies, the guard now covers
    # it, so the user gets the dialog rather than a silent non-start.
    shown = []
    ran = []

    def boom():
        raise RuntimeError("logging is broken")

    monkeypatch.setattr(app_main, "setup_logging", boom)
    monkeypatch.setattr(app_main, "_run", lambda: ran.append(True))
    monkeypatch.setattr(app_main, "_show_fatal_dialog", lambda tb: shown.append(tb))

    with pytest.raises(SystemExit) as exc:
        app_main.main()

    assert exc.value.code == 1
    assert ran == [], "_run must not be reached when startup failed"
    assert shown and "logging is broken" in shown[0]


def test_fatal_dialog_still_shown_when_logging_call_also_fails(monkeypatch):
    # log.exception() is itself wrapped: a broken logging subsystem must not
    # swallow the one surface the user can actually see.
    shown = []

    class BrokenLog:
        def exception(self, *a, **k):
            raise RuntimeError("no handlers, no stderr")

    monkeypatch.setattr(app_main, "log", BrokenLog())
    monkeypatch.setattr(app_main, "setup_logging", lambda: True)
    monkeypatch.setattr(app_main, "_run", lambda: (_ for _ in ()).throw(ValueError("nope")))
    monkeypatch.setattr(app_main, "_show_fatal_dialog", lambda tb: shown.append(tb))

    with pytest.raises(SystemExit):
        app_main.main()
    assert shown and "nope" in shown[0]


def test_normal_exit_path_is_not_treated_as_a_crash(monkeypatch):
    # app.exec() ends via sys.exit(code); that must pass straight through.
    shown = []
    monkeypatch.setattr(app_main, "setup_logging", lambda: True)
    monkeypatch.setattr(app_main, "_run", lambda: (_ for _ in ()).throw(SystemExit(0)))
    monkeypatch.setattr(app_main, "_show_fatal_dialog", lambda tb: shown.append(tb))

    with pytest.raises(SystemExit) as exc:
        app_main.main()
    assert exc.value.code == 0
    assert shown == []


# --- finding 2: notifications emitted before the tray exists --------------
def test_notifications_before_a_sink_are_replayed_in_order():
    buf = NotificationBuffer()
    buf.deliver("first")
    buf.deliver("second")
    shown = []
    buf.attach(shown.append)
    assert shown == ["first", "second"]


def test_notifications_after_attach_go_straight_through():
    buf = NotificationBuffer()
    shown = []
    buf.attach(shown.append)
    buf.deliver("live")
    assert shown == ["live"]


def test_buffer_is_bounded_and_keeps_the_newest():
    buf = NotificationBuffer(limit=3)
    for i in range(6):
        buf.deliver(str(i))
    shown = []
    buf.attach(shown.append)
    assert shown == ["3", "4", "5"]
    assert buf.dropped == 3


def test_invalid_startup_hotkey_notice_survives_until_the_tray_exists():
    # The reported bug end to end: HotkeyManager reports the fallback during
    # startup, long before the tray is built. Qt drops a signal emitted with
    # nothing connected, so the user never learned their hotkey had changed.
    notices = NotificationBuffer()
    manager = HotkeyManager("f88", on_start=lambda: None, on_stop=lambda: None,
                            on_config_error=notices.deliver)
    assert manager.hotkey != "f88"          # it did fall back

    shown = []
    notices.attach(shown.append)            # tray comes up later
    assert shown and "f88" in shown[0]


# --- finding 3: model reload race -----------------------------------------
def test_only_the_newest_model_reload_installs():
    # Two quick Saves: #1 selects medium, #2 selects base. #2 loads first, then
    # the slower #1 finishes — and used to overwrite it, leaving the app on
    # medium while the config said base.
    gate = ModelReloadGate()
    installed = []

    first = gate.begin()      # Save #1 (medium)
    second = gate.begin()     # Save #2 (base)

    assert gate.commit(second, lambda: installed.append("base")) is True
    assert gate.commit(first, lambda: installed.append("medium")) is False
    assert installed == ["base"]


def test_reload_gate_reports_staleness_without_installing():
    gate = ModelReloadGate()
    stale = gate.begin()
    current = gate.begin()
    assert gate.is_current(stale) is False
    assert gate.is_current(current) is True


def test_single_reload_installs_normally():
    gate = ModelReloadGate()
    installed = []
    gen = gate.begin()
    assert gate.commit(gen, lambda: installed.append("base")) is True
    assert installed == ["base"]


def test_generations_are_unique_under_concurrent_begins():
    gate = ModelReloadGate()
    seen, lock = [], threading.Lock()

    def worker():
        gen = gate.begin()
        with lock:
            seen.append(gen)

    threads = [threading.Thread(target=worker) for _ in range(50)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert sorted(seen) == list(range(1, 51))   # no generation handed out twice


# --- sibling contract A: sounds -------------------------------------------
def test_missing_sounds_module_yields_a_silent_stand_in(monkeypatch):
    # This branch must run standalone, before feat/settings-redesign lands.
    import builtins
    real_import = builtins.__import__

    def no_sounds(name, *args, **kwargs):
        if name == "rekounts.sounds":
            raise ImportError("not merged yet")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", no_sounds)
    sounds = _make_sounds(lambda: True)
    assert isinstance(sounds, _NullSounds)
    sounds.start_cue()      # all three must be safe no-ops
    sounds.stop_cue()
    sounds.error_cue()


# --- sibling contract B: dictionary providers ------------------------------
class FakeHistory:
    def __init__(self, rows):
        self._rows = rows

    def dictionary_words(self):
        return self._rows


def test_hotwords_provider_reads_words_live():
    history = FakeHistory([{"word": "Kubernetes", "sounds_like": "cuber netties"},
                           {"word": "  ", "sounds_like": "x"},
                           {"word": "pytest", "sounds_like": ""}])
    hotwords, _ = _dictionary_providers(history)
    assert hotwords() == ["Kubernetes", "pytest"]

    # "live": a word added later shows up without rebuilding anything.
    history._rows.append({"word": "PySide", "sounds_like": ""})
    assert "PySide" in hotwords()


def test_replacements_derived_from_the_existing_dictionary_table():
    history = FakeHistory([{"word": "Kubernetes", "sounds_like": "cuber netties"},
                           {"word": "pytest", "sounds_like": ""}])
    _, replacements = _dictionary_providers(history)
    assert replacements() == [("cuber netties", "Kubernetes")]


def test_replacements_prefer_the_history_contract_method_when_present():
    class HistoryWithContract(FakeHistory):
        def dictionary_replacements(self):
            return [("cuber netties", "Kubernetes")]

    history = HistoryWithContract([{"word": "ignored", "sounds_like": "ignored"}])
    _, replacements = _dictionary_providers(history)
    assert replacements() == [("cuber netties", "Kubernetes")]


def test_dictionary_providers_never_raise_into_the_pipeline():
    class BrokenHistory:
        def dictionary_words(self):
            raise RuntimeError("db is locked")

    hotwords, replacements = _dictionary_providers(BrokenHistory())
    assert hotwords() == []
    assert replacements() == []


# --- sibling contract C: pre-roll live-apply ------------------------------
class _PrerollRecorder:
    def __init__(self, preroll_seconds=0.0):
        self.preroll_seconds = preroll_seconds
        self.armed = 0
        self.closed = 0

    def arm(self):
        self.armed += 1

    def close(self):
        self.closed += 1


def test_apply_preroll_arms_when_turned_on():
    rec = _PrerollRecorder(preroll_seconds=0.0)
    assert _apply_preroll(rec, True, 0.5, lambda: False) is True
    assert rec.preroll_seconds == 0.5
    assert rec.armed == 1 and rec.closed == 0


def test_apply_preroll_releases_the_stream_when_turned_off_and_idle():
    rec = _PrerollRecorder(preroll_seconds=0.5)
    assert _apply_preroll(rec, False, 0.5, lambda: False) is True
    assert rec.preroll_seconds == 0.0
    assert rec.closed == 1 and rec.armed == 0


def test_apply_preroll_off_mid_recording_defers_the_release():
    # A recording is in flight: leave the stream open now — that recording's
    # stop() releases the mic on the legacy path (preroll_seconds is now 0).
    rec = _PrerollRecorder(preroll_seconds=0.5)
    assert _apply_preroll(rec, False, 0.5, lambda: True) is True
    assert rec.preroll_seconds == 0.0
    assert rec.closed == 0


def test_apply_preroll_is_a_noop_when_unchanged():
    rec = _PrerollRecorder(preroll_seconds=0.5)
    assert _apply_preroll(rec, True, 0.5, lambda: False) is False
    assert rec.armed == 0 and rec.closed == 0


def test_apply_preroll_arm_failure_is_non_fatal():
    class DeadMic(_PrerollRecorder):
        def arm(self):
            raise OSError("mic busy")

    rec = DeadMic(preroll_seconds=0.0)
    assert _apply_preroll(rec, True, 0.5, lambda: False) is True   # must not raise
    assert rec.preroll_seconds == 0.5                              # value still applied


def test_attach_provider_only_sets_declared_attributes():
    class WithContract:
        def __init__(self):
            self.hotwords_provider = None

    class WithoutContract:
        pass

    target = WithContract()
    assert _attach_provider(target, "hotwords_provider", lambda: ["x"]) is True
    assert target.hotwords_provider() == ["x"]

    other = WithoutContract()
    assert _attach_provider(other, "hotwords_provider", lambda: ["x"]) is False
    assert not hasattr(other, "hotwords_provider")


# --- model download progress reporting ------------------------------------
def _tick(model="base", phase="download", done=0, total=1000):
    return models.Progress(model, phase, "model.bin", done, total)


def test_a_fetch_announces_itself_exactly_once():
    """One notification per fetch, not one per chunk — the sink is a tray
    balloon, so a message per megabyte would be unusable."""
    seen = []
    on_progress, _ = app_main.make_model_progress_reporter(seen.append)
    for done in range(0, 1001, 100):
        on_progress(_tick(done=done))
    assert len(seen) == 1
    assert "Downloading" in seen[0] and "base" in seen[0]


def test_a_cache_copy_is_described_as_copying_not_downloading():
    seen = []
    on_progress, _ = app_main.make_model_progress_reporter(seen.append)
    on_progress(_tick(phase="migrate", done=10))
    assert "Copying cached" in seen[0]


def test_a_startup_that_fetches_nothing_stays_silent():
    """The normal case — model already installed — must not notify at all."""
    seen = []
    _, did_fetch = app_main.make_model_progress_reporter(seen.append)
    assert did_fetch() is False
    assert seen == []


def test_did_fetch_reports_true_once_progress_arrived():
    on_progress, did_fetch = app_main.make_model_progress_reporter(lambda m: None)
    on_progress(_tick(done=1))
    assert did_fetch() is True


def test_switching_phase_announces_the_new_phase():
    """A migration that falls through to a download tells the user both times."""
    seen = []
    on_progress, _ = app_main.make_model_progress_reporter(seen.append)
    on_progress(_tick(phase="migrate", done=5))
    on_progress(_tick(phase="download", done=5))
    assert len(seen) == 2
    assert "Copying cached" in seen[0]
    assert "Downloading" in seen[1]


def test_progress_notifications_survive_having_no_tray_yet():
    """First-run download happens before Qt exists; those notices must be
    buffered and replayed, not dropped."""
    buffer = NotificationBuffer()
    on_progress, _ = app_main.make_model_progress_reporter(buffer.deliver)
    on_progress(_tick(done=1))

    delivered = []
    buffer.attach(delivered.append)
    assert len(delivered) == 1
    assert "Downloading" in delivered[0]


def test_a_failed_download_falls_back_to_an_installed_model():
    from rekounts.__main__ import pick_installed_fallback

    picked = pick_installed_fallback(
        "small", "base",
        is_installed=lambda n: n == "base", known=["base", "small", "medium"])
    assert picked == "base"


def test_no_installed_model_means_no_fallback():
    from rekounts.__main__ import pick_installed_fallback

    assert pick_installed_fallback(
        "small", "base",
        is_installed=lambda n: False, known=["base", "small"]) is None


def test_fallback_never_retries_the_model_that_just_failed():
    from rekounts.__main__ import pick_installed_fallback

    picked = pick_installed_fallback(
        "base", "base",
        is_installed=lambda n: True, known=["base", "medium"])
    assert picked == "medium"


# --------------------------------------------------------------------------
# Live-typing stream tick
#
# The per-tick insertion runs every ~0.8s while the user speaks. It MUST be
# marked streaming=True: without that flag an undeliverable increment gets
# parked on the clipboard (silently overwriting whatever the user had copied,
# once per tick) and a long one escalates to Ctrl+V, contradicting the reason
# live typing forces keystroke mode in the first place.
# --------------------------------------------------------------------------
class _RecordingInserter:
    def __init__(self, outcome="typed"):
        self.calls = []
        self.outcome = outcome

    def insert(self, text, target=None, *, streaming=False):
        self.calls.append((text, streaming))
        return self.outcome


class _FakeLiveTyper:
    def __init__(self, words, emitted=0):
        self._emitted = emitted
        self._words = words

    def feed(self, raw):
        return self._words


class _FakeStreamController:
    def __init__(self, words="hello there", emitted=0, recording=True,
                 active=True, snapshot=None):
        import numpy as np
        self.live_typing_active = active
        self._recording = recording
        self.inserter = _RecordingInserter()
        self.live_typer = _FakeLiveTyper(words, emitted)
        self._snapshot = (np.zeros(16000, dtype="float32")
                          if snapshot is None else snapshot)

        class _T:
            def transcribe_stream(self, audio):
                return "hello there"

        self.transcriber = _T()

    def is_recording(self):
        return self._recording

    def preview_snapshot(self):
        return self._snapshot


def test_stream_tick_marks_the_insert_as_a_streaming_increment():
    c = _FakeStreamController()
    assert app_main.stream_tick(c) == "typed"
    assert c.inserter.calls == [("hello there", True)]


def test_stream_tick_prefixes_a_space_once_words_have_been_streamed():
    c = _FakeStreamController(emitted=3)
    app_main.stream_tick(c)
    assert c.inserter.calls == [(" hello there", True)]


def test_stream_tick_is_a_noop_when_live_typing_is_not_active():
    c = _FakeStreamController(active=False)
    assert app_main.stream_tick(c) is None
    assert c.inserter.calls == []


def test_stream_tick_is_a_noop_when_not_recording():
    c = _FakeStreamController(recording=False)
    assert app_main.stream_tick(c) is None
    assert c.inserter.calls == []


def test_stream_tick_is_a_noop_without_enough_audio():
    import numpy as np
    c = _FakeStreamController(snapshot=np.zeros(100, dtype="float32"))
    assert app_main.stream_tick(c) is None
    assert c.inserter.calls == []


def test_stream_tick_is_a_noop_when_no_new_words_were_emitted():
    c = _FakeStreamController(words="")
    assert app_main.stream_tick(c) is None
    assert c.inserter.calls == []


# --------------------------------------------------------------------------
# Inserter construction reads the documented config keys
# --------------------------------------------------------------------------
def test_inserter_honours_the_long_text_via_paste_config_key():
    from rekounts.config import DEFAULTS

    assert DEFAULTS["long_text_via_paste"] is True
    built = app_main._build_inserter({"live_typing": False,
                                      "insertion_mode": "keystroke",
                                      "long_text_via_paste": False})
    assert built.long_text_via_paste is False
    assert built.mode == "keystroke"


def test_inserter_forces_keystroke_mode_while_live_typing_is_on():
    built = app_main._build_inserter({"live_typing": True,
                                      "insertion_mode": "paste",
                                      "long_text_via_paste": True})
    assert built.mode == "keystroke"
    assert built.long_text_via_paste is True
