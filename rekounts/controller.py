import logging
import threading
import time

from rekounts.audio_utils import normalize_gain
from rekounts.state_machine import StateMachine
from rekounts.text_inserter import undelivered_message
from rekounts.transcriber import is_hallucination

log = logging.getLogger(__name__)

# Outcome tokens a (future) insert() may return to signal it did NOT insert -
# e.g. no text field was focused. Matched case-insensitively against the return
# value's name/str. Anything not in this set (and not None/False) counts as a
# successful insertion. None is the legacy interface and always counts as success.
_INSERT_FAILURE_TOKENS = frozenset({
    "false", "no_target", "notarget", "no_focus", "nofocus", "not_inserted",
    "failed", "failure", "error", "skipped", "none", "", "0",
    # UIPI: the target window is elevated and rejected the injection — the text
    # never landed, so it must count as not-inserted (history is the safety net).
    "blocked",
    # Keystroke delivery stopped part-way because a physical modifier stayed
    # held. Some of the text may have landed, but not the message, so the user
    # gets a notice pointing at History rather than a silent half-sentence.
    "interrupted",
})


def _insertion_succeeded(outcome) -> bool:
    """Interpret inserter.insert()'s return value defensively.

    A parallel session is changing insert() to return an outcome. The old
    interface returns None -> treat as success so this branch works standalone
    before the merge. A bool is taken at face value; any other value is a success
    unless it stringifies to a known failure token.
    """
    if outcome is None:
        return True
    if isinstance(outcome, bool):
        return outcome
    token = str(getattr(outcome, "name", outcome)).strip().lower()
    return token not in _INSERT_FAILURE_TOKENS


class AppController:
    # Breathing room granted when a cap saved mid-recording is already behind
    # the recording (see _grace_for_a_cap_already_past). Long enough to finish a
    # sentence, short enough that the safety net is still a safety net.
    CAP_CHANGE_GRACE_SECONDS = 30

    def __init__(self, recorder, transcriber, cleaner, inserter,
                 on_overlay_show=None, on_overlay_hide=None,
                 on_error=None, on_notice=None, min_seconds=0.3, run_async=None,
                 on_state=None, on_result=None,
                 max_recording_seconds=0, filter_hallucinations=True,
                 on_recording_ended=None, warn_before_seconds=30, clock=None):
        self.recorder = recorder
        self.transcriber = transcriber
        self.cleaner = cleaner
        self.inserter = inserter
        self.on_overlay_show = on_overlay_show or (lambda: None)
        self.on_overlay_hide = on_overlay_hide or (lambda: None)
        self.on_error = on_error or (lambda msg: log.error(msg))
        # on_notice: non-error user feedback (e.g. captured audio but no speech
        # detected - usually a too-quiet or wrong microphone).
        self.on_notice = on_notice or (lambda msg: log.info(msg))
        # on_state(state): called on EVERY state change with one of
        # "idle"/"recording"/"processing". Fired from whatever thread caused the
        # transition (hotkey thread, the run_async worker, or the auto-stop timer
        # thread) - the receiver MUST marshal to its UI thread (as __main__'s
        # Bridge signals already do). Never called re-entrantly for the same state.
        self.on_state = on_state or (lambda state: None)
        # on_result(raw, cleaned, duration_s, inserted): fired after every
        # completed transcription that produced text, whether or not insertion
        # succeeded, so the dashboard history captures dictation even when no text
        # field was focused. Fired from the processing thread; marshal to the UI.
        self.on_result = on_result or (lambda raw, cleaned, duration_s, inserted: None)
        # on_recording_ended(): fired the moment a recording leaves RECORDING for
        # ANY reason — a gesture stop, the overlay ✓/✕, or the auto-stop timer.
        # The hotkey gesture uses it to drop a stale latch (via external_stop) so
        # the next press starts fresh instead of "stopping" a recording that is
        # already gone. Fired from whatever thread caused the transition; the
        # receiver must be idempotent and thread-safe (TapHoldGesture.external_stop
        # is both). No-op for a gesture's own stop, which already reset itself.
        self.on_recording_ended = on_recording_ended or (lambda: None)
        self.min_seconds = min_seconds
        # run_async(fn): schedule heavy work off the caller thread.
        # In tests it's None -> runs synchronously.
        self.run_async = run_async
        self.filter_hallucinations = filter_hallucinations
        # Safety cap (seconds) for a recording the user forgets to stop (toggle
        # mode). 0/None disables it. Enforced by a daemon timer.
        self.max_recording_seconds = max_recording_seconds or 0
        # Warn this many seconds before the cap auto-stops, so a long hands-free
        # recording isn't cut off with no notice. 0 disables the warning; it is
        # also skipped when the cap is too short to lead it.
        self.warn_before_seconds = warn_before_seconds or 0
        self._autostop_timer = None
        self._warn_timer = None
        # Monotonic clock (injectable so tests can drive elapsed time) and the
        # moment the current recording began — used to reschedule the cap live
        # from time already elapsed when the user changes it mid-recording.
        self._clock = clock or time.monotonic
        self._recording_started_at = 0.0
        # When the current recording's one-off grace runs out, or None if a cap
        # change has not landed in the past during this recording.
        self._cap_grace_deadline = None
        self.sm = StateMachine()
        self._last_state = self.sm.state.value

    # --- state notification -------------------------------------------------
    def _sync_state(self):
        """Emit on_state if the machine's state changed since the last emit.
        Called after every transition so consumers see each change exactly once."""
        s = self.sm.state.value
        if s != self._last_state:
            self._last_state = s
            try:
                self.on_state(s)
            except Exception:
                log.exception("on_state callback raised")

    def _notify_recording_ended(self):
        """Tell listeners a recording just left RECORDING (see on_recording_ended)."""
        try:
            self.on_recording_ended()
        except Exception:
            log.exception("on_recording_ended callback raised")

    # --- auto-stop timer ----------------------------------------------------
    @staticmethod
    def _make_timer(delay, fn):
        t = threading.Timer(max(0.0, delay), fn)
        t.daemon = True
        t.start()
        return t

    def _schedule_autostop(self):
        """Arm the auto-stop cap and its pre-warning for a fresh recording."""
        self._cancel_autostop()
        self._recording_started_at = self._clock()
        self._cap_grace_deadline = None
        self._arm_cap_timers(self.max_recording_seconds)

    def _reschedule_autostop(self):
        """Re-arm the cap mid-recording from time already elapsed, so the running
        timer and the notice it will show agree on the current cap value."""
        self._cancel_autostop()
        cap = self.max_recording_seconds
        if not (cap and cap > 0):
            return  # cap cleared mid-recording -> no auto-stop
        remaining = cap - (self._clock() - self._recording_started_at)
        if remaining <= 0:
            remaining = self._grace_for_a_cap_already_past()
            if remaining <= 0:
                self._auto_stop()
                return
        self._arm_cap_timers(remaining)

    def _grace_for_a_cap_already_past(self):
        """Seconds left to a recording whose new cap is ALREADY behind it.

        Saving a setting must not end a dictation the instant it is saved. The
        cap exists to catch a hands-free recording you forgot to stop, not to
        cut off one you are in the middle of: the user changed a setting, they
        did not ask to be interrupted mid-sentence, and there is no undo for
        speech. So a cap that lands in the past buys a short grace instead, with
        a notice, and the user gets to finish the thought.

        The grace is granted once per recording. Nudging the cap down five more
        times re-uses the deadline already set rather than pushing it out each
        time, so this can defer the stop but never cancel it.
        """
        now = self._clock()
        if self._cap_grace_deadline is None:
            self._cap_grace_deadline = now + self.CAP_CHANGE_GRACE_SECONDS
            mins = self.max_recording_seconds / 60
            self.on_notice(
                f"The new {mins:g} min limit is already past — this recording "
                f"stops in {self.CAP_CHANGE_GRACE_SECONDS:g}s.")
        return self._cap_grace_deadline - now

    def _arm_cap_timers(self, remaining):
        """Schedule auto-stop after `remaining` seconds and, when there is room,
        a pre-warning `warn_before_seconds` ahead of it."""
        if not (remaining and remaining > 0):
            return
        self._autostop_timer = self._make_timer(remaining, self._auto_stop)
        lead = self.warn_before_seconds
        if lead and remaining > lead:
            self._warn_timer = self._make_timer(remaining - lead, self._warn)

    def _cancel_autostop(self):
        for attr in ("_autostop_timer", "_warn_timer"):
            timer = getattr(self, attr, None)
            if timer is not None:
                timer.cancel()
                setattr(self, attr, None)

    def set_max_recording_seconds(self, seconds):
        """Live-apply a new cap. If a recording is in flight, reschedule its
        auto-stop (and pre-warning) so the timer's interval and the notice it
        reports stay consistent — a mid-recording change used to leave the timer
        on the old interval while the auto-stop notice announced the new one."""
        seconds = seconds or 0
        if seconds == self.max_recording_seconds:
            return
        self.max_recording_seconds = seconds
        if self.is_recording():
            self._reschedule_autostop()

    def _warn(self):
        """Fired ahead of the cap: warn the user the recording is about to stop.
        No-op if we're no longer recording."""
        if self.sm.state.name != "RECORDING":
            return
        lead = self.warn_before_seconds
        mins = self.max_recording_seconds / 60
        self.on_notice(
            f"Recording will auto-stop in {lead:g}s (the {mins:g} min limit).")

    def _auto_stop(self):
        """Fired by the timer when a recording runs past the max duration."""
        if self.sm.state.name != "RECORDING":
            return
        mins = self.max_recording_seconds / 60
        self.on_notice(f"Recording stopped — reached the {mins:g} min limit.")
        self.stop_recording()

    # --- hotkey entry points ------------------------------------------------
    def start_recording(self) -> bool:
        """Begin a recording. Returns True only if one actually started.

        Returns False when the state machine refuses (we are still PROCESSING
        the previous clip — IDLE is the only state RECORDING can be entered
        from) or when the microphone failed. The hotkey gesture uses this to
        avoid latching itself around a recording that never began.
        """
        if not self.sm.to_recording():
            return False
        self._sync_state()
        try:
            if getattr(self.recorder, "fell_back_to_default", False):
                self.on_notice("Saved microphone not found — using system default.")
            self.recorder.start()
            self._schedule_autostop()
            self.on_overlay_show()
            return True
        except Exception as e:
            self.on_error(f"Microphone error: {e}")
            self._cancel_autostop()
            self.sm.to_idle()
            self._sync_state()
            return False

    def stop_recording(self):
        if self.sm.state.name != "RECORDING":
            return
        if not self.sm.to_processing():
            return
        self._cancel_autostop()
        self._sync_state()
        # We have left RECORDING — resync the hotkey gesture before the (possibly
        # long) processing work, so a hotkey stop and an overlay/auto stop leave
        # the gesture in the same clean state.
        self._notify_recording_ended()
        self.on_overlay_hide()
        if self.run_async:
            self.run_async(self._process)
        else:
            self._process()

    def cancel_recording(self):
        """Abort an in-progress recording: stop the mic, discard the audio, and
        return to IDLE without transcribing or inserting. Safe to call in any
        state (no-op unless currently RECORDING).

        Note: this cancels only a RECORDING, not a PROCESSING transcription. A
        true mid-transcription cancel needs the transcriber to check a flag
        between faster-whisper's (lazy) segments — that lives in transcriber.py,
        which a sibling branch owns — plus a PROCESSING-state affordance on the
        pill (overlay, another branch). It could not be delivered cleanly from
        the controller alone: transcribe() consumes the generator internally and
        blocks, so abandoning it here would still leave the model call running,
        holding its lock and starving the next dictation. Deferred deliberately.
        """
        if self.sm.state.name != "RECORDING":
            return
        self._cancel_autostop()
        try:
            self.recorder.stop()   # discard whatever was captured
        except Exception as e:
            log.warning("cancel: recorder.stop() failed: %s", e)
        self.on_overlay_hide()
        self.sm.to_idle()
        self._sync_state()
        self._notify_recording_ended()

    def toggle(self):
        if self.sm.state.name == "IDLE":
            self.start_recording()
        elif self.sm.state.name == "RECORDING":
            self.stop_recording()
        # PROCESSING: ignore

    # --- heavy pipeline (runs off UI thread in production) ------------------
    def _process(self):
        try:
            audio = self.recorder.stop()
            duration_s = self.recorder.duration(audio)
            if duration_s < self.min_seconds:
                return
            # Boost quiet microphones so low-gain input survives Whisper's VAD.
            audio = normalize_gain(audio)
            raw = self.transcriber.transcribe(audio)
            self._finish_final(raw, duration_s)
        except Exception as e:
            self.on_error(f"Transcription failed: {e}")
        finally:
            self.sm.to_idle()
            self._sync_state()

    def _finish_final(self, raw, duration_s):
        # Suppress Whisper's phantom phrases on silence/noise, but only when the
        # WHOLE result is one - a genuine sentence is never dropped.
        if self.filter_hallucinations and is_hallucination(raw):
            self.on_notice("No speech detected — check your microphone selection/volume.")
            return
        cleaned = self.cleaner.clean(raw)
        if not cleaned:
            # Audio was long enough to process but nothing came back. Almost
            # always a too-quiet or wrong microphone. Surface it instead of
            # silently doing nothing.
            self.on_notice("No speech detected — check your microphone selection/volume.")
            return
        outcome = self.inserter.insert(cleaned)
        inserted = _insertion_succeeded(outcome)
        if not inserted:
            self.on_notice(self._undelivered_notice(outcome))
        # Fire AFTER insertion regardless of outcome: the history is the safety
        # net when the cursor wasn't in a text field.
        self.on_result(raw, cleaned, duration_s, inserted)

    def _undelivered_notice(self, outcome) -> str:
        """Wording for a dictation that did not reach the cursor.

        This is the notice the user actually sees — the app builds its
        TextInserter without an ``on_notice`` hook, so the inserter's own table
        never fires outside tests. It therefore has to be right for EVERY
        outcome, not just "no text field": see
        :func:`rekounts.text_inserter.undelivered_message`, which both surfaces
        now share so they cannot drift.
        """
        return undelivered_message(outcome)

    def is_recording(self) -> bool:
        return self.sm.state.name == "RECORDING"
