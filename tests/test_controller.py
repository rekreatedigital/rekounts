import numpy as np

from rekounts.controller import AppController
from rekounts.state_machine import DictationState
from rekounts.text_cleaner import TextCleaner


class FakeRecorder:
    def __init__(self, audio):
        self._audio = audio
        self.started = False

    def start(self):
        self.started = True

    def stop(self):
        self.started = False
        return self._audio

    def duration(self, a):
        return len(a) / 16000


class FakeTranscriber:
    def __init__(self, text):
        self._text = text
        self.calls = 0

    def transcribe(self, audio):
        self.calls += 1
        return self._text


def make(audio_len=16000, raw_text="um hello"):
    rec = FakeRecorder(np.ones(audio_len, dtype="float32"))
    trans = FakeTranscriber(raw_text)
    inserted = []
    notices = []
    ctrl = AppController(
        recorder=rec, transcriber=trans, cleaner=TextCleaner(),
        inserter=type("I", (), {"insert": lambda self, t: inserted.append(t)})(),
        on_overlay_show=lambda: None, on_overlay_hide=lambda: None,
        on_notice=lambda m: notices.append(m),
        min_seconds=0.3,
    )
    ctrl._notices = notices
    return ctrl, rec, trans, inserted


def test_full_cycle_inserts_cleaned_text():
    ctrl, rec, trans, inserted = make(audio_len=16000, raw_text="um hello world")
    ctrl.start_recording()
    assert ctrl.sm.state == DictationState.RECORDING
    assert rec.started is True
    ctrl.stop_recording()   # runs processing synchronously in test
    assert trans.calls == 1
    assert inserted == ["Hello world"]
    assert ctrl.sm.state == DictationState.IDLE


def test_too_short_audio_skips_transcription():
    ctrl, rec, trans, inserted = make(audio_len=1600, raw_text="hello")  # 0.1s
    ctrl.start_recording()
    ctrl.stop_recording()
    assert trans.calls == 0
    assert inserted == []
    assert ctrl.sm.state == DictationState.IDLE


def test_empty_transcript_inserts_nothing_and_notifies():
    # audio was long enough but produced no text -> user should be told
    # (this is the "mic too quiet / wrong device" case), not silently dropped
    ctrl, rec, trans, inserted = make(audio_len=16000, raw_text="   ")
    ctrl.start_recording()
    ctrl.stop_recording()
    assert inserted == []
    assert ctrl.sm.state == DictationState.IDLE
    assert len(ctrl._notices) == 1
    assert "no speech" in ctrl._notices[0].lower()


def test_too_short_audio_does_not_notify():
    # a quick accidental tap should stay silent - no notice, no error
    ctrl, rec, trans, inserted = make(audio_len=1600, raw_text="hello")  # 0.1s
    ctrl.start_recording()
    ctrl.stop_recording()
    assert inserted == []
    assert ctrl._notices == []


def test_overlapping_start_ignored():
    ctrl, rec, trans, inserted = make()
    ctrl.start_recording()
    ctrl.start_recording()   # second one ignored
    assert ctrl.sm.state == DictationState.RECORDING


# --- on_recording_ended: resync the hotkey gesture on every non-gesture stop
def make_with_ended(audio_len=16000):
    rec = FakeRecorder(np.ones(audio_len, dtype="float32"))
    ended = []
    ctrl = AppController(
        recorder=rec, transcriber=FakeTranscriber("hello"), cleaner=TextCleaner(),
        inserter=type("I", (), {"insert": lambda self, t: None})(),
        min_seconds=0.3, max_recording_seconds=300,
        on_recording_ended=lambda: ended.append(True),
    )
    return ctrl, rec, ended


def test_on_recording_ended_fires_on_stop():
    ctrl, rec, ended = make_with_ended()
    ctrl.start_recording()
    assert ended == []
    ctrl.stop_recording()
    assert ended == [True]


def test_on_recording_ended_fires_on_cancel():
    ctrl, rec, ended = make_with_ended()
    ctrl.start_recording()
    ctrl.cancel_recording()
    assert ended == [True]
    assert ctrl.sm.state == DictationState.IDLE


def test_on_recording_ended_fires_on_auto_stop():
    # The auto-stop timer path (a recording the user forgot to stop) must also
    # resync the gesture, else hands-free would stay latched after auto-stop.
    ctrl, rec, ended = make_with_ended()
    ctrl.start_recording()
    ctrl._auto_stop()                    # simulate the safety-cap timer firing
    assert ended == [True]
    assert ctrl.sm.state == DictationState.IDLE


def test_on_recording_ended_not_fired_outside_recording():
    ctrl, rec, ended = make_with_ended()
    ctrl.stop_recording()                # nothing recording
    ctrl.cancel_recording()              # nothing recording
    assert ended == []


def test_on_recording_ended_failure_does_not_break_stop():
    rec = FakeRecorder(np.ones(16000, dtype="float32"))
    ctrl = AppController(
        recorder=rec, transcriber=FakeTranscriber("hi"), cleaner=TextCleaner(),
        inserter=type("I", (), {"insert": lambda self, t: None})(),
        min_seconds=0.3,
        on_recording_ended=lambda: (_ for _ in ()).throw(RuntimeError("boom")),
    )
    ctrl.start_recording()
    ctrl.stop_recording()                # must not raise
    assert ctrl.sm.state == DictationState.IDLE


def test_transcription_error_returns_to_idle():
    ctrl, rec, _, inserted = make()
    def boom(a):
        raise RuntimeError("gpu exploded")
    ctrl.transcriber = type("T", (), {"transcribe": staticmethod(boom)})()
    ctrl.start_recording()
    ctrl.stop_recording()
    assert ctrl.sm.state == DictationState.IDLE
    assert inserted == []


def test_release_types_the_cleaned_full_transcript():
    rec = FakeRecorder(np.ones(16000, dtype="float32"))
    trans = FakeTranscriber("um hello world")
    inserted = []
    ctrl = AppController(
        recorder=rec, transcriber=trans, cleaner=TextCleaner(),
        inserter=type("I", (), {"insert": lambda self, t: inserted.append(t)})(),
        min_seconds=0.3,
    )
    ctrl.start_recording()
    ctrl.stop_recording()
    assert inserted == ["Hello world"]   # cleaned full text


def test_insertion_outcome_mapping_covers_full_inserter_vocabulary():
    # Cross-module seam: every outcome TextInserter can return must map to the
    # correct inserted flag (BLOCKED = admin window rejected the paste -> False).
    from rekounts.controller import _insertion_succeeded
    from rekounts.text_inserter import InsertResult
    expected = {
        InsertResult.PASTED: True,
        InsertResult.TYPED: True,
        InsertResult.NO_TARGET: False,
        InsertResult.BLOCKED: False,
        # Typing stopped part-way (a modifier stayed held). Some text may have
        # landed but not the message, so it counts as not-inserted and the user
        # gets the clipboard copy plus the notice.
        InsertResult.INTERRUPTED: False,
        InsertResult.FAILED: False,
        InsertResult.SKIPPED: False,
    }
    assert set(expected) == set(InsertResult), "new outcome value needs a mapping decision"
    for outcome, ok in expected.items():
        assert _insertion_succeeded(outcome) is ok, outcome
    assert _insertion_succeeded(None) is True   # legacy no-return inserters


# --- callbacks, cancel, auto-stop, hallucination (feat/pipeline-quality) ---

class RecordingInserter:
    """Inserter whose insert() returns a configurable outcome and records calls."""
    def __init__(self, outcome=None):
        self.outcome = outcome
        self.calls = []

    def insert(self, text):
        self.calls.append(text)
        return self.outcome


def build(raw_text="hello world", audio_len=16000, inserter=None, **kw):
    rec = FakeRecorder(np.ones(audio_len, dtype="float32"))
    trans = FakeTranscriber(raw_text)
    inserter = inserter if inserter is not None else RecordingInserter()
    states, results, notices, errors = [], [], [], []
    ctrl = AppController(
        recorder=rec, transcriber=trans, cleaner=TextCleaner(), inserter=inserter,
        on_state=lambda s: states.append(s),
        on_result=lambda raw, cleaned, dur, ins: results.append((raw, cleaned, dur, ins)),
        on_notice=lambda m: notices.append(m),
        on_error=lambda m: errors.append(m),
        min_seconds=0.3, **kw,
    )
    return ctrl, rec, trans, inserter, states, results, notices, errors


def test_on_state_fires_each_transition_in_order():
    ctrl, *_ , states, results, notices, errors = build()
    ctrl.start_recording()
    ctrl.stop_recording()   # synchronous processing
    assert states == ["recording", "processing", "idle"]


def test_on_result_success_fires_with_inserted_true():
    ctrl, rec, trans, inserter, states, results, notices, errors = build(
        raw_text="hello world", inserter=RecordingInserter(outcome=None))
    ctrl.start_recording()
    ctrl.stop_recording()
    assert results == [("hello world", "Hello world", 1.0, True)]
    assert inserter.calls == ["Hello world"]
    assert notices == []


def test_on_result_fires_inserted_false_when_no_text_field():
    # insert() returns a non-success outcome -> still saved to history, user told
    ctrl, rec, trans, inserter, states, results, notices, errors = build(
        raw_text="hello world", inserter=RecordingInserter(outcome="no_target"))
    ctrl.start_recording()
    ctrl.stop_recording()
    assert len(results) == 1
    assert results[0][3] is False           # inserted flag
    assert results[0][1] == "Hello world"   # cleaned text still captured
    assert any("history" in n.lower() for n in notices)


def test_undelivered_notice_never_mentions_the_clipboard():
    # An undeliverable dictation goes to the dashboard, not the clipboard —
    # taking someone's clipboard without asking is the bug, not the fallback.
    ctrl, rec, trans, inserter, states, results, notices, errors = build(
        inserter=RecordingInserter(outcome="no_target"))
    ctrl.start_recording()
    ctrl.stop_recording()
    assert notices
    assert not any("clipboard" in n.lower() for n in notices)
    assert any("history" in n.lower() for n in notices)


def test_on_result_treats_false_bool_as_not_inserted():
    ctrl, rec, trans, inserter, states, results, notices, errors = build(
        inserter=RecordingInserter(outcome=False))
    ctrl.start_recording()
    ctrl.stop_recording()
    assert results[0][3] is False


def test_on_result_not_fired_on_empty_transcript():
    ctrl, *rest = build(raw_text="   ")
    results, notices = rest[4], rest[5]
    ctrl.start_recording()
    ctrl.stop_recording()
    assert results == []
    assert any("no speech" in n.lower() for n in notices)


def test_hallucination_only_result_is_suppressed():
    ctrl, rec, trans, inserter, states, results, notices, errors = build(
        raw_text="Thank you.")
    ctrl.start_recording()
    ctrl.stop_recording()
    assert inserter.calls == []          # phantom phrase not inserted
    assert results == []                 # nothing saved to history
    assert any("no speech" in n.lower() for n in notices)


def test_hallucination_phrase_inside_real_sentence_is_kept():
    ctrl, rec, trans, inserter, states, results, notices, errors = build(
        raw_text="Thank you for the detailed report you sent.")
    ctrl.start_recording()
    ctrl.stop_recording()
    assert len(inserter.calls) == 1
    assert results[0][3] is True


def test_hallucination_filter_can_be_disabled():
    ctrl, rec, trans, inserter, states, results, notices, errors = build(
        raw_text="Thank you.", filter_hallucinations=False)
    ctrl.start_recording()
    ctrl.stop_recording()
    assert inserter.calls == ["Thank you."]   # not suppressed when disabled


def test_cancel_recording_discards_and_returns_to_idle():
    ctrl, rec, trans, inserter, states, results, notices, errors = build()
    ctrl.start_recording()
    assert rec.started is True
    ctrl.cancel_recording()
    assert ctrl.sm.state == DictationState.IDLE
    assert rec.started is False        # recorder was stopped
    assert trans.calls == 0            # never transcribed
    assert inserter.calls == []        # never inserted
    assert results == []
    assert states == ["recording", "idle"]


def test_cancel_recording_noop_when_idle():
    ctrl, rec, trans, inserter, states, results, notices, errors = build()
    ctrl.cancel_recording()            # nothing recording
    assert ctrl.sm.state == DictationState.IDLE
    assert states == []
    assert errors == []


def test_autostop_timer_scheduled_and_cancelled():
    ctrl, *_ = build(max_recording_seconds=300)
    ctrl.start_recording()
    assert ctrl._autostop_timer is not None
    assert ctrl._autostop_timer.interval == 300
    ctrl.stop_recording()
    assert ctrl._autostop_timer is None


def test_no_autostop_timer_when_disabled():
    ctrl, *_ = build(max_recording_seconds=0)
    ctrl.start_recording()
    assert ctrl._autostop_timer is None
    ctrl.stop_recording()


def test_auto_stop_notifies_and_processes():
    ctrl, rec, trans, inserter, states, results, notices, errors = build(
        raw_text="hello world", max_recording_seconds=300)
    ctrl.start_recording()
    ctrl._auto_stop()                  # simulate the timer firing
    assert any("limit" in n.lower() for n in notices)
    assert ctrl.sm.state == DictationState.IDLE
    assert inserter.calls == ["Hello world"]   # captured audio was still processed


def test_auto_stop_noop_when_not_recording():
    ctrl, rec, trans, inserter, states, results, notices, errors = build()
    ctrl._auto_stop()                  # never started
    assert notices == []
    assert ctrl.sm.state == DictationState.IDLE


# --- finding 5: start_recording must report whether it actually started ----
def test_start_recording_reports_success():
    ctrl, *_ = build()
    assert ctrl.start_recording() is True


def test_start_recording_refuses_while_processing():
    # RECORDING can only be entered from IDLE. While PROCESSING the previous
    # clip the start is refused — and the hotkey gesture needs to hear that, or
    # it latches a gesture around a recording that does not exist.
    pending = []
    ctrl, *_ = build(run_async=pending.append)   # hold processing open
    ctrl.start_recording()
    ctrl.stop_recording()
    assert ctrl.sm.state == DictationState.PROCESSING
    assert ctrl.start_recording() is False
    assert ctrl.sm.state == DictationState.PROCESSING


def test_start_recording_reports_failure_on_microphone_error():
    class DeadMic(FakeRecorder):
        def start(self):
            raise OSError("device in use")

    ctrl, rec, trans, inserter, states, results, notices, errors = build()
    ctrl.recorder = DeadMic(np.ones(16000, dtype="float32"))
    assert ctrl.start_recording() is False
    assert ctrl.sm.state == DictationState.IDLE
    assert errors and "Microphone error" in errors[0]


# --- finding 5a: warn the user before the cap auto-stops -------------------
def test_warn_timer_is_armed_ahead_of_the_cap():
    ctrl, *_ = build(max_recording_seconds=300)          # default 30s lead
    ctrl.start_recording()
    assert ctrl._autostop_timer.interval == 300
    assert ctrl._warn_timer is not None
    assert ctrl._warn_timer.interval == 270              # 300 - 30
    ctrl.stop_recording()
    assert ctrl._warn_timer is None and ctrl._autostop_timer is None


def test_no_warn_timer_when_the_cap_is_shorter_than_the_lead():
    ctrl, *_ = build(max_recording_seconds=20, warn_before_seconds=30)
    ctrl.start_recording()
    assert ctrl._autostop_timer is not None              # the cap still fires
    assert ctrl._warn_timer is None                      # but there's no room to warn
    ctrl.stop_recording()


def test_warn_before_zero_disables_the_pre_warning():
    ctrl, *_ = build(max_recording_seconds=300, warn_before_seconds=0)
    ctrl.start_recording()
    assert ctrl._autostop_timer is not None
    assert ctrl._warn_timer is None
    ctrl.stop_recording()


def test_warn_notifies_without_stopping_the_recording():
    ctrl, rec, trans, inserter, states, results, notices, errors = build(
        max_recording_seconds=300)
    ctrl.start_recording()
    ctrl._warn()                                         # simulate the warn timer firing
    assert ctrl.sm.state == DictationState.RECORDING     # still recording — just warned
    assert any("auto-stop" in n.lower() for n in notices)
    ctrl.stop_recording()


def test_warn_is_a_noop_once_recording_has_ended():
    ctrl, rec, trans, inserter, states, results, notices, errors = build(
        max_recording_seconds=300)
    ctrl.start_recording()
    ctrl.stop_recording()
    notices.clear()
    ctrl._warn()                                         # late timer after stop
    assert notices == []


# --- finding 5b: a mid-recording cap change reschedules the running timer ---
def test_cap_change_mid_recording_reschedules_the_running_timer():
    now = [1000.0]
    ctrl, *_ = build(max_recording_seconds=300, clock=lambda: now[0])
    ctrl.start_recording()
    assert ctrl._autostop_timer.interval == 300
    now[0] = 1060.0                                      # 60s elapsed
    ctrl.set_max_recording_seconds(120)                 # lower the cap to 2 min
    assert ctrl._autostop_timer.interval == 60          # remaining = 120 - 60
    assert ctrl._warn_timer.interval == 30              # 60 - 30 lead
    ctrl.stop_recording()


def test_auto_stop_notice_matches_the_rescheduled_cap():
    # 5b's core symptom: the timer fired on the OLD interval while the notice
    # announced the NEW value. After rescheduling they agree.
    now = [0.0]
    ctrl, rec, trans, inserter, states, results, notices, errors = build(
        raw_text="hello world", max_recording_seconds=300, clock=lambda: now[0])
    ctrl.start_recording()
    now[0] = 30.0
    ctrl.set_max_recording_seconds(120)                 # 2 min cap
    ctrl._auto_stop()                                   # as the rescheduled timer would
    assert any("2 min" in n for n in notices)
    assert not any("5 min" in n for n in notices)


def test_cap_lowered_below_elapsed_stops_immediately():
    now = [0.0]
    ctrl, rec, trans, inserter, states, results, notices, errors = build(
        raw_text="hello world", max_recording_seconds=300, clock=lambda: now[0])
    ctrl.start_recording()
    now[0] = 100.0                                       # 100s elapsed
    ctrl.set_max_recording_seconds(60)                  # already past a 1-min cap
    assert ctrl.sm.state == DictationState.IDLE          # stopped and processed
    assert any("limit" in n.lower() for n in notices)
    assert inserter.calls == ["Hello world"]            # captured audio still transcribed


def test_cap_change_while_idle_only_updates_the_value():
    ctrl, *_ = build(max_recording_seconds=300)
    ctrl.set_max_recording_seconds(600)
    assert ctrl.max_recording_seconds == 600
    assert ctrl._autostop_timer is None                 # nothing scheduled while idle
    ctrl.start_recording()
    assert ctrl._autostop_timer.interval == 600         # next recording honours it
    ctrl.stop_recording()


def test_cap_cleared_mid_recording_cancels_the_autostop():
    ctrl, *_ = build(max_recording_seconds=300)
    ctrl.start_recording()
    assert ctrl._autostop_timer is not None
    ctrl.set_max_recording_seconds(0)                   # "No limit" chosen mid-recording
    assert ctrl._autostop_timer is None
    assert ctrl._warn_timer is None
    ctrl.stop_recording()
