import inspect
import logging
import os
import sys
import threading
import traceback
from logging.handlers import RotatingFileHandler

from rekounts import models
from rekounts.audio_recorder import AudioRecorder
from rekounts.config import DEFAULTS, Config, default_config_path
from rekounts.controller import AppController
from rekounts.hotkey_manager import HotkeyManager, hotkey_warning
from rekounts.text_cleaner import TextCleaner
from rekounts.text_inserter import TextInserter
from rekounts.transcriber import Transcriber

# NOTE: PySide6 and the ui.* modules (which import PySide6) are intentionally
# NOT imported at module top. Importing PySide6 loads Qt's bundled runtime
# (incl. OpenMP) which conflicts with ctranslate2's runtime and hard-crashes
# the process (native access violation) if Qt is loaded before the Whisper
# model. We therefore import all Qt-dependent code inside _run(), AFTER the
# Transcriber has loaded the model. Do not move these imports to the top.

log = logging.getLogger("main")


_LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s %(message)s"


def _log_level():
    """INFO by default; set REKOUNTS_LOG_LEVEL=DEBUG to capture the low-level
    hotkey trace (combo edges, gesture transitions, watchdog rebuilds) when
    diagnosing a field report. An unknown value falls back to INFO."""
    import os
    name = (os.environ.get("REKOUNTS_LOG_LEVEL") or "INFO").upper()
    return getattr(logging, name, logging.INFO)


def setup_logging():
    """Configure file logging, degrading instead of failing.

    A read-only/roaming/full %APPDATA% makes mkdir or the file handler raise.
    Losing the log file is an annoyance; losing the app because we could not
    open the log file is a silent startup death under pythonw. So fall back to
    an in-memory-only configuration and carry on — main() still guards the call
    for anything more exotic than an OSError.
    """
    level = _log_level()
    try:
        log_dir = default_config_path().parent / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        handler = RotatingFileHandler(
            log_dir / "rekounts.log", maxBytes=1_000_000, backupCount=3)
        logging.basicConfig(level=level, handlers=[handler],
                            format=_LOG_FORMAT)
        return True
    except Exception:
        # No file handler: a NullHandler keeps logging calls cheap and silent
        # rather than letting logging's "last resort" writer touch a stderr that
        # does not exist under pythonw.
        logging.basicConfig(level=level,
                            handlers=[logging.NullHandler()], format=_LOG_FORMAT)
        return False


class NotificationBuffer:
    """Holds user notifications emitted before there is anywhere to show them.

    The tray is built late in startup (Qt cannot be imported until the Whisper
    model has loaded), but notifications can fire before then — an invalid
    configured hotkey falls back to the default and reports it while the
    Bridge's `notify` signal still has no receiver, and Qt silently drops a
    signal emitted with nothing connected. The user never learned their hotkey
    had changed.

    So every notification goes through here: buffered while there is no sink,
    replayed in order the moment one attaches. Deliberately Qt-free so it can be
    unit-tested and so the buffering rule is one thing, in one place, for every
    notification rather than a special case for the hotkey.
    """

    def __init__(self, limit: int = 20):
        self.limit = limit
        self._sink = None
        self._pending = []
        self.dropped = 0

    def deliver(self, message: str):
        if self._sink is not None:
            self._sink(message)
            return
        if len(self._pending) >= self.limit:
            # Something is very wrong (no sink ever attached); keep the newest.
            self._pending.pop(0)
            self.dropped += 1
        self._pending.append(message)

    def attach(self, sink):
        """Install the real sink and flush anything queued, oldest first."""
        self._sink = sink
        pending, self._pending = self._pending, []
        for message in pending:
            sink(message)


def make_model_progress_reporter(notify):
    """Build an on_progress callback for rekounts.models.ensure_model().

    Two audiences, two levels of detail:
      * the log file gets a line every ~10% (the only place a first-run download
        can be watched, since Qt cannot be imported until the model has loaded —
        see the note at the top of this module);
      * the user gets ONE notification when a fetch starts, not a balloon per
        chunk. `notify` is the buffering sink before the tray exists and the
        live bridge signal afterwards, so the same reporter serves both.

    Returns (on_progress, did_fetch) where did_fetch() reports whether anything
    was actually downloaded or copied — so a normal offline startup, which
    fetches nothing, stays silent.
    """
    state = {"announced": None, "logged_at": -1.0}

    def on_progress(p):
        if state["announced"] != (p.model, p.phase):
            state["announced"] = (p.model, p.phase)
            verb = ("Copying cached" if p.phase == "migrate" else "Downloading")
            notify("%s %s speech model (%s)…"
                   % (verb, p.model, models.human_size(p.bytes_total)))
        frac = p.fraction
        if frac - state["logged_at"] >= 0.1 or frac >= 1.0:
            state["logged_at"] = frac
            log.info("model %s %s %d%% (%s of %s)", p.model, p.phase,
                     int(frac * 100), models.human_size(p.bytes_done),
                     models.human_size(p.bytes_total))

    return on_progress, (lambda: state["announced"] is not None)


def pick_installed_fallback(requested, default, is_installed=None, known=None):
    """A model whose download just failed is useless, but one already on disk
    keeps the app alive: prefer the default, then any other installed model.
    Returns None when nothing is installed — a true first run, where dying
    with the startup error dialog is the honest outcome.
    """
    if is_installed is None:
        is_installed = models.is_installed
    if known is None:
        known = list(models.MANIFEST)
    for candidate in [default] + [k for k in known if k != default]:
        if candidate != requested and is_installed(candidate):
            return candidate
    return None


class ModelReloadGate:
    """Makes the newest model reload the only one that can install itself.

    Two quick Saves that both change the model spawn two loader threads. They
    finish in whatever order the disk and CPU decide, so the LAST to finish won
    — which could be the older one, leaving the app running `medium` while the
    config (and `current_model_sig`) say `base`. Each reload takes a generation
    number up front; only the generation that is still the newest at commit time
    is allowed to swap the transcriber in.
    """

    def __init__(self):
        self._lock = threading.Lock()
        self._generation = 0

    def begin(self) -> int:
        """Claim the next generation. Call this synchronously when scheduling."""
        with self._lock:
            self._generation += 1
            return self._generation

    def commit(self, generation: int, install) -> bool:
        """Run ``install()`` iff ``generation`` is still the newest one.

        Held under the lock so a newer generation cannot slip in between the
        check and the swap. Returns whether the install happened.
        """
        with self._lock:
            if generation != self._generation:
                return False
            install()
            return True

    def is_current(self, generation: int) -> bool:
        with self._lock:
            return generation == self._generation


_MUTEX_NAME = "Rekounts_SingleInstance"
# The mutex the app used under its old name. Renaming the mutex means a still-
# running TalkativeAI no longer blocks us, so the rename would quietly reintroduce
# the exact double-instance bug the mutex exists to prevent — see
# _legacy_instance_running().
_LEGACY_MUTEX_NAME = "TalkativeAI_SingleInstance"


def _acquire_posix_lock(path):
    """Hold an exclusive ``flock`` on ``path``; the open file IS the claim.

    Returns the open file object while we are the first instance (the caller
    must keep it referenced for the process lifetime — closing it releases the
    lock), or None when another live process already holds it. Like the Windows
    mutex, the kernel releases the lock automatically when the owner exits or
    crashes, so a stale lock file left on disk never blocks the next launch.
    """
    import fcntl
    path = str(path)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    f = open(path, "a")
    try:
        fcntl.flock(f.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        return f
    except OSError:
        f.close()
        return None


def _acquire_single_instance():
    """Return a truthy instance claim if we're the first instance, else None.

    Some launch paths (and this machine's --copies venv) can start the app twice;
    two instances mean duplicate tray icons and fighting hotkey listeners.
    Windows: a named mutex (atomic, auto-released when the owner exits).
    macOS/POSIX: an ``flock``-ed lock file in the app data folder (same
    auto-release-on-exit property). The caller keeps the returned object
    referenced for the process lifetime.
    """
    try:
        if sys.platform != "win32":
            from rekounts.paths import app_data_dir
            return _acquire_posix_lock(app_data_dir() / ".rekounts.lock")
        import ctypes
        kernel32 = ctypes.windll.kernel32
        handle = kernel32.CreateMutexW(None, False, _MUTEX_NAME)
        ERROR_ALREADY_EXISTS = 183
        if kernel32.GetLastError() == ERROR_ALREADY_EXISTS:
            return None
        return handle
    except Exception:
        return True   # if the check fails, don't block startup


def _legacy_instance_running() -> bool:
    """True if a pre-rename TalkativeAI is still running in the tray.

    Our own mutex cannot see it: the name changed, so both apps happily start and
    the user gets two tray icons and two hotkey hooks racing for the same key —
    worse than either app alone, and baffling to diagnose.

    OpenMutexW, NOT CreateMutexW: opening is a pure existence probe. Creating the
    legacy mutex would make US its owner, which would then block the old app the
    user may be deliberately going back to, and would report "running" to the
    next Rekounts launch forever.
    """
    try:
        import ctypes
        kernel32 = ctypes.windll.kernel32
        SYNCHRONIZE = 0x00100000
        handle = kernel32.OpenMutexW(SYNCHRONIZE, False, _LEGACY_MUTEX_NAME)
        if not handle:
            return False
        kernel32.CloseHandle(handle)
        return True
    except Exception:
        return False   # a failed probe must never block startup


def _report_missing_permissions(notify):
    """Surface missing OS permissions as actionable notices (macOS).

    On macOS the hotkey listener, the paste synthesis and the microphone each
    sit behind a separate user consent (Input Monitoring / Accessibility /
    Microphone), and the OS denies silently — no dialog, no error, the events
    simply never arrive. Without this, a missing permission is
    indistinguishable from a broken app. Elsewhere this is a no-op. Never
    raises: a failed check must not stop startup.
    """
    try:
        from rekounts.permissions import missing_permission_messages
        for message in missing_permission_messages():
            log.warning(message)
            notify(message)
    except Exception:
        log.exception("permission check failed (non-fatal)")


def _hotkey_label(cfg) -> str:
    return (cfg.get("hotkey") or "").upper()


class _NullSounds:
    """Stand-in for rekounts.sounds until feat/settings-redesign lands it.

    Same three methods, all no-ops, so the wiring below is unconditional and
    this branch still runs standalone.
    """

    def start_cue(self):
        pass

    def stop_cue(self):
        pass

    def error_cue(self):
        pass


def _make_sounds(enabled_provider):
    """Build the audio-cue player, or a silent stand-in if it is not there yet.

    Contract (feat/settings-redesign): Sounds(enabled_provider) exposes
    thread-safe non-blocking start_cue/stop_cue/error_cue, and re-reads
    enabled_provider() on every cue so the toggle applies live.
    """
    try:
        from rekounts.sounds import Sounds
    except ImportError:
        log.info("rekounts.sounds not present; audio cues disabled")
        return _NullSounds()
    try:
        try:
            return Sounds(enabled_provider=enabled_provider)
        except TypeError:
            return Sounds(enabled_provider)   # positional-only signature
    except Exception:
        log.exception("could not initialise sound cues; continuing silently")
        return _NullSounds()


# Names the dictionary contract (feat/dictionary-offline) might use for
# "give me the sounds-like replacement pairs". Tried in order; if none exist we
# derive the pairs from the dictionary table History already has, so this works
# before that PR lands too.
_REPLACEMENT_METHODS = ("dictionary_replacements", "replacements",
                        "sounds_like_pairs", "dictionary_pairs")


def _dictionary_providers(history):
    """(hotwords_provider, replacements_provider) reading live from `history`.

    Both are callables, not snapshots: a word added in the Hub applies to the
    next dictation with nothing rebuilt. Every read is defensive — a broken
    dictionary must never take down a transcription.
    """

    def hotwords():
        try:
            return [w for w in ((row.get("word") or "").strip()
                                for row in history.dictionary_words()) if w]
        except Exception:
            log.exception("reading dictionary hotwords failed")
            return []

    def replacements():
        for name in _REPLACEMENT_METHODS:
            fn = getattr(history, name, None)
            if callable(fn):
                try:
                    return [(str(a), str(b)) for a, b in fn()]
                except Exception:
                    log.exception("history.%s() failed", name)
                    return []
        # Fallback from the existing schema: sounds_like is what Whisper hears,
        # word is what it should have been.
        try:
            pairs = []
            for row in history.dictionary_words():
                heard = (row.get("sounds_like") or "").strip()
                want = (row.get("word") or "").strip()
                if heard and want:
                    pairs.append((heard, want))
            return pairs
        except Exception:
            log.exception("deriving dictionary replacements failed")
            return []

    return hotwords, replacements


def _attach_provider(obj, name, provider):
    """Set a sibling-contract provider attribute if that contract has landed.

    Guarded by hasattr so this branch does not sprout attributes nothing reads
    while the sibling PR is still in flight; once merged, every rebuilt
    Transcriber/TextCleaner gets the provider re-attached here.
    """
    if provider is None or not hasattr(obj, name):
        return False
    try:
        setattr(obj, name, provider)
        return True
    except Exception:
        log.exception("could not attach %s", name)
        return False


def _apply_preroll(recorder, enabled, seconds, is_recording):
    """Live-apply the pre-roll setting to an already-built recorder.

    Turning it ON arms the continuous mic stream so even the next dictation gets
    pre-roll; turning it OFF releases that stream and drops the buffer — unless a
    recording is in flight, in which case ``preroll_seconds`` is now 0 and that
    recording's ``stop()`` releases the mic on the legacy path. Best-effort and
    Qt-free so ``apply_settings`` stays thin and this stays unit-testable.
    Returns True if it changed anything.
    """
    target = float(seconds or 0.0) if enabled else 0.0
    if target == recorder.preroll_seconds:
        return False
    recorder.preroll_seconds = target
    if enabled:
        try:
            recorder.arm()
        except Exception as e:
            log.warning("pre-roll arm failed (non-fatal): %s", e)
    elif not is_recording():
        try:
            recorder.close()   # release the continuously-open stream + buffer
        except Exception:
            log.exception("releasing the pre-roll stream failed")
    return True


def _show_fatal_dialog(tb: str):
    """Last-resort error surface. Under pythonw there is no console, so a silent
    exception would just make the app 'never start' with no clue. A QMessageBox
    works even if the tray never came up."""
    try:
        from PySide6 import QtWidgets
        app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv)
        QtWidgets.QMessageBox.critical(
            None, "Rekounts failed to start",
            "Rekounts hit an error and could not start.\n\n"
            + tb.strip().splitlines()[-1]
            + "\n\nFull details are in:\n"
            + str(default_config_path().parent / "logs" / "rekounts.log"))
        app  # keep ref
    except Exception:
        log.exception("could not show fatal error dialog")


def _show_legacy_running_dialog():
    """Tell the user to quit the old app, since we cannot safely run beside it."""
    try:
        from PySide6 import QtWidgets
        app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv)
        QtWidgets.QMessageBox.information(
            None, "TalkativeAI is still running",
            "TalkativeAI has been renamed to Rekounts, and the old version is "
            "still running.\n\nRunning both at once makes them fight over the "
            "dictation hotkey, so Rekounts has not started.\n\nRight-click the "
            "TalkativeAI icon in your system tray, choose Quit, then start "
            "Rekounts again. Your settings and history come across "
            "automatically.")
        app  # keep ref
    except Exception:
        log.exception("could not show the legacy-instance dialog")


def _migrate_legacy_state():
    """Bring old-name user data across. Runs BEFORE anything reads or writes it.

    Ordering matters twice over: setup_logging() creates the log folder inside
    the new data directory, and Config() reads config.json from it. Either one
    running first would find an empty new folder and quietly start the user from
    scratch while their real data sat under the old name.
    """
    try:
        from rekounts.migrate import migrate_app_data
        return migrate_app_data()
    except Exception:
        return None   # never let a migration problem stop the app from starting


def _reconcile_startup(cfg, backend=None):
    """Reconcile launch-at-login with the config flag, honoring Task Manager.

    Three records meet here on the first post-rename launch: the migrated
    config's ``launch_on_startup``, the legacy TalkativeAI Run entry, and Task
    Manager's StartupApproved flags — where a user's enable/disable lives in
    the registry, never in our config. The order below is load-bearing:

    1. Read the LEGACY entry's Task Manager state BEFORE anything registers or
       purges. A user who disabled TalkativeAI in Task Manager and upgrades
       with a stale ``launch_on_startup: true`` must not get autostart silently
       resurrected under the new name — the registry disable is their actual
       last word, so sync config OFF and register nothing.
    2. The same honesty for OUR OWN entry: registered but disabled in Task
       Manager means Windows skips us at login — sync config OFF (so the Hub's
       toggle is honest) rather than silently re-enabling ourselves at every
       launch. Otherwise (re)register, which also heals a stale command path
       after the repo/venv moved.
    3. Purge the legacy entry only AFTER the (re)registration above, so a crash
       between the two leaves the user with the old entry still working rather
       than with no launch-at-login at all. Left in place it would start a
       stale second copy at every login (it points at the old checkout).

    ``backend`` exists for tests (the in-memory registry fake); production
    passes None and every startup call resolves the real platform backend.
    Never raises: losing launch-at-login must not stop the app.
    """
    try:
        from rekounts import startup as startup_mod
        want = bool(cfg.get("launch_on_startup"))
        if want and startup_mod.legacy_startup_was_disabled(backend=backend):
            want = False
            cfg.set("launch_on_startup", False)
            cfg.save()
            log.info("the old entry is disabled in Task Manager; honoring that "
                     "over the migrated config and leaving launch-at-login off")
        registered = startup_mod.current_command(backend=backend) is not None
        if want and registered and not startup_mod.is_enabled(backend=backend):
            cfg.set("launch_on_startup", False)
            cfg.save()
        else:
            startup_mod.set_enabled(want, backend=backend)
        if startup_mod.purge_legacy(backend=backend):
            log.info("removed the pre-rename launch-at-login entry")
    except Exception as e:
        log.warning("startup registration check failed (non-fatal): %s", e)


def main():
    try:
        # Probed FIRST — before the data migration, not only inside _run(). A
        # pre-rename TalkativeAI still sitting in the tray can be mid-write to
        # the very history.db the migration is about to copy; copying under a
        # live writer risks carrying across a torn database. The probe needs
        # neither logging nor config, so nothing forces it later: if the old
        # app is live, explain and leave WITHOUT touching its data — the next
        # launch (old app quit) migrates safely.
        if _legacy_instance_running():
            _show_legacy_running_dialog()
            return
        # Before setup_logging(): see _migrate_legacy_state(). Its result is
        # logged below, once there are handlers to log to.
        migration = _migrate_legacy_state()
        # Inside the guard: setup_logging() degrades on its own, but if it dies
        # anyway the user must still get the dialog rather than a process that
        # silently never appears (there is no console under pythonw).
        setup_logging()
        if migration is not None and migration.attempted:
            log.info("data-folder migration: %s", migration.summary())
            for item, error in migration.failed:
                log.warning("could not migrate %r from %%APPDATA%%\\TalkativeAI: "
                            "%s (will retry on the next launch)", item, error)
        elif migration is None:
            log.warning("legacy data migration could not run; continuing")
        _run()
    except SystemExit:
        raise  # normal app.exec() exit path
    except Exception:
        try:
            log.exception("Fatal error during startup")
        except Exception:
            pass  # logging itself is what failed — the dialog still matters
        _show_fatal_dialog(traceback.format_exc())
        sys.exit(1)


def _run():
    # Checked before our own mutex: an old TalkativeAI in the tray is invisible
    # to the renamed mutex, and the two would fight over the hotkey. Exiting with
    # an explanation beats starting into a broken state — the fix is one click in
    # the old app's tray menu, and this can only ever happen once, on upgrade.
    # main() already probed BEFORE the data migration (the ordering that keeps a
    # live old instance's history.db from being copied mid-write); this re-check
    # is belt-and-suspenders for an old app started in the window since, and is
    # the layer that can log it — logging exists by now.
    if _legacy_instance_running():
        log.info("A pre-rename TalkativeAI instance is running; exiting.")
        _show_legacy_running_dialog()
        return

    instance = _acquire_single_instance()
    if instance is None:
        log.info("Another instance is already running; exiting.")
        return

    cfg = Config()

    # Created BEFORE the model load, not inside Bridge, because the first-run
    # model download happens before Qt exists (see the import note above) and its
    # notifications would otherwise have nowhere to go. Buffered here, replayed
    # the moment the tray attaches.
    notices = NotificationBuffer()

    def active_model_name():
        # When live typing is on, use the faster stream_model for everything so
        # words appear quickly; otherwise use the user's chosen (accurate) model.
        return cfg.get("stream_model") if cfg.get("live_typing") else cfg.get("model")

    # Dictionary providers are wired into every Transcriber/TextCleaner built
    # below. They read the History, which needs Qt-free construction — History
    # imports only sqlite3, so it is safe to build here, before Qt.
    from rekounts.history import History
    history = History(enabled=bool(cfg.get("history_enabled")))
    hotwords_provider, replacements_provider = _dictionary_providers(history)

    def build_transcriber(name, device, notify=None):
        """Make sure the model is on disk, then load it from that directory.

        Delivery happens HERE, before the model is handed to faster-whisper: the
        transcriber only ever sees an absolute local path, so no faster-whisper
        code path can reach the network (rekounts/models.py has the manifest,
        the downloader and the Hugging Face-cache migration).
        """
        notify = notify or (lambda m: None)
        on_progress, did_fetch = make_model_progress_reporter(notify)
        loaded = name
        try:
            model_dir = models.ensure_model(name, on_progress=on_progress)
        except models.ModelUnavailable:
            # A config naming a model we cannot serve (hand-edited, or one that
            # left the manifest) must not be a dead app — fall back to the
            # default and say so.
            loaded = DEFAULTS["model"]
            log.warning("model %r is not available; falling back to %r",
                        name, loaded)
            notify("Model %r is not available — using %s instead." % (name, loaded))
            model_dir = models.ensure_model(loaded, on_progress=on_progress)
        except RuntimeError as e:
            # A failed download (offline, unreachable host, missing release
            # asset) must not be a dead app when a model already sits on disk —
            # run with what we have and say so. ensure_model on an installed
            # model touches no network, so this retry cannot fail the same way.
            loaded = pick_installed_fallback(name, DEFAULTS["model"])
            if loaded is None:
                raise
            log.warning("could not fetch model %r (%s); using installed %r",
                        name, e, loaded)
            notify("Couldn't download %s — using installed %s instead." % (name, loaded))
            model_dir = models.ensure_model(loaded, on_progress=on_progress)
        if did_fetch():
            # Name the model actually loaded, which is not `name` on the
            # fallback path above.
            notify("Speech model ready (%s)." % loaded)
        t = Transcriber(str(model_dir), device, cfg.get("language"),
                        beam_size=cfg.get("beam_size"))
        _attach_provider(t, "hotwords_provider", hotwords_provider)
        return t

    def build_cleaner():
        c = TextCleaner(cfg.get("strip_fillers"), cfg.get("auto_capitalize"),
                        cfg.get("fix_punctuation_spacing"),
                        collapse_repeats=cfg.get("collapse_repeats"),
                        strip_discourse_fillers=cfg.get("strip_discourse_fillers"))
        _attach_provider(c, "replacements_provider", replacements_provider)
        return c

    # 1) Fetch (if needed) and load the model FIRST, before any Qt import (see
    # note above). Progress goes to the log live and to the notice buffer for
    # replay once the tray exists.
    transcriber = build_transcriber(active_model_name(), cfg.get("device"),
                                    notify=notices.deliver)
    # Only the model name and device require a reload; language and beam_size are
    # read per transcribe() call, so live-apply just sets those attributes.
    current_model_sig = (active_model_name(), cfg.get("device"))
    # The hotkey value the live listener is currently built for. apply_settings
    # rebuilds the listener ONLY when this actually changes — rebuilding it on
    # every Save would hand a fresh IDLE gesture to a recording already in
    # flight, and that recording could then never be stopped by the hotkey.
    current_hotkey = cfg.get("hotkey")
    reload_gate = ModelReloadGate()
    # Warm the model on a background thread while Qt initializes, so the first
    # real dictation is as fast as the rest (no first-use warm-up lag).
    threading.Thread(target=transcriber.warm_up, daemon=True).start()
    cleaner = build_cleaner()
    # device_provider lets tray/settings mic changes apply on the NEXT recording
    # without rebuilding the recorder.
    recorder = AudioRecorder(
        device=cfg.get("microphone"),
        preroll_seconds=cfg.get("preroll_seconds") if cfg.get("preroll_enabled") else 0.0,
        device_provider=lambda: cfg.get("microphone"))
    if cfg.get("preroll_enabled"):
        # Pre-roll keeps the mic stream open; a busy/missing mic must not stop
        # startup, so arm best-effort.
        try:
            recorder.arm()
        except Exception as e:
            log.warning("pre-roll arm failed (non-fatal): %s", e)
    # Live typing streams words via keystrokes (paste-per-chunk would clobber the
    # clipboard repeatedly), so force keystroke mode when live typing is on.
    inserter = TextInserter(
        mode="keystroke" if cfg.get("live_typing") else cfg.get("insertion_mode"))

    # 2) Now it is safe to import and initialize Qt.
    from PySide6 import QtCore, QtWidgets
    from rekounts.languages import LANGUAGES
    from rekounts.ui.dashboard import Dashboard
    from rekounts.ui.overlay import Overlay
    from rekounts.ui.tray import TrayApp

    class Bridge(QtCore.QObject):
        # Controller callbacks fire on worker/hotkey threads; these signals
        # marshal them onto the Qt GUI thread.
        state = QtCore.Signal(str)              # "idle" | "recording" | "processing"
        result = QtCore.Signal(str, str, float, bool)  # raw, cleaned, duration_s, inserted
        notify = QtCore.Signal(str)

        def __init__(self, notices):
            super().__init__()
            # notify goes to a buffer, not straight to the tray, so messages
            # raised before the tray exists are replayed instead of dropped.
            # The buffer is created before the model load (it already holds any
            # first-run download notices) and adopted here.
            # _deliver is a slot on this QObject (which lives on the GUI thread),
            # so worker-thread emits are queued onto the GUI thread as usual.
            self.notices = notices
            self.notify.connect(self._deliver)

        @QtCore.Slot(str)
        def _deliver(self, message):
            self.notices.deliver(message)

    app = QtWidgets.QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)  # keep running with only the tray

    bridge = Bridge(notices)

    # Audio cues. enabled_provider is read live on every cue, so the settings
    # toggle applies without a restart. A config that predates the setting
    # (the key is simply absent) counts as enabled — the sibling PR ships the
    # key and the sound files together, and until then _NullSounds is silent.
    def sound_effects_enabled():
        value = cfg.get("sound_effects")
        return True if value is None else bool(value)

    sounds = _make_sounds(sound_effects_enabled)

    overlay = Overlay()
    overlay.level_provider = recorder.current_level
    overlay.set_hotkey_label(_hotkey_label(cfg))
    overlay.set_pill_enabled(bool(cfg.get("show_pill")))
    bridge.state.connect(overlay.set_state)

    bridge.result.connect(history.add)

    def run_async(fn):
        threading.Thread(target=fn, daemon=True).start()

    def on_state(state):
        # Fires on the hotkey/worker thread. bridge.state marshals to Qt; the
        # cues are thread-safe and non-blocking by contract, so they are played
        # from here directly — "recording" is the moment the mic opens and
        # "processing" the moment it closes, which is exactly the start/stop
        # feedback the user is listening for.
        bridge.state.emit(state)
        if state == "recording":
            sounds.start_cue()
        elif state == "processing":
            sounds.stop_cue()

    def on_error(message):
        log.error(message)
        sounds.error_cue()
        bridge.notify.emit(message)

    # Assigned below once the hotkey manager is built. Declared here so the
    # controller's on_recording_ended can reach whatever manager is current
    # (apply_settings may swap it), without the controller importing the manager.
    hotkeys = None

    def reset_hotkey_gesture():
        """Drop any stale hotkey-gesture latch after a recording ends by a
        non-gesture route (overlay ✓/✕, auto-stop). Without this, the gesture
        stays latched in hands-free and the next hotkey press is swallowed
        'stopping' a recording that is already gone."""
        hk = hotkeys
        if hk is None:
            return
        try:
            hk.gesture.external_stop()
        except Exception:
            log.exception("resetting the hotkey gesture failed")

    controller = AppController(
        recorder=recorder, transcriber=transcriber, cleaner=cleaner, inserter=inserter,
        on_error=on_error,
        on_notice=lambda m: (log.info(m), bridge.notify.emit(m)),
        run_async=run_async,
        live_typing=cfg.get("live_typing"),
        on_state=on_state,
        on_result=bridge.result.emit,
        max_recording_seconds=cfg.get("max_recording_seconds"),
        filter_hallucinations=cfg.get("filter_hallucinations"),
        on_recording_ended=reset_hotkey_gesture,
    )
    # Pill buttons: ✕ discards the recording, ✓ finishes it. Both controller
    # entry points are thread-safe and no-op outside the RECORDING state.
    overlay.on_cancel = controller.cancel_recording
    overlay.on_finish = controller.stop_recording
    # Show the idle pill (set_state is a no-op while the pill is disabled).
    overlay.set_state("idle")

    warned_hotkeys = set()

    def build_hotkeys():
        """One hotkey, three gestures: hold = push-to-talk, double-tap = hands-free,
        tap-while-recording = stop.

        A lone idle tap CANCELS (discards the audio without transcribing) rather
        than stopping: that clip is tap-duration + the double-tap window (~0.4-0.65s),
        which clears the 0.3s min-duration guard, so stopping it would transcribe
        and paste ambient audio.
        """
        manager = HotkeyManager(
            cfg.get("hotkey"),
            on_start=controller.start_recording,
            on_stop=controller.stop_recording,
            on_cancel=controller.cancel_recording,
            # Lets a freshly-built gesture stop a recording it never started
            # (e.g. the hotkey was changed mid-recording): a refused start while
            # RECORDING is routed to stop instead of being swallowed.
            is_recording=controller.is_recording,
            on_hint=lambda: bridge.notify.emit(
                "Double-tap or hold %s to dictate." % cfg.get("hotkey")),
            on_config_error=lambda m: (log.error(m), bridge.notify.emit(m)),
        )
        # Legal but collides with a common app shortcut (we do not suppress
        # keys, so Ctrl+A would also "select all" in the focused window and the
        # dictation would replace the selection). Warn, don't refuse — it is
        # the user's keyboard.
        # Once per distinct hotkey per session — apply_settings rebuilds the
        # manager on every Save, and repeating the warning for a choice the user
        # has already made is nagging, not helping.
        warning = hotkey_warning(manager.hotkey)
        if warning and manager.hotkey not in warned_hotkeys:
            warned_hotkeys.add(manager.hotkey)
            log.warning(warning)
            bridge.notify.emit(warning)
        return manager

    hotkeys = build_hotkeys()
    hotkeys.start()

    def stream_loop():
        import time
        from rekounts.audio_utils import normalize_gain
        while True:
            time.sleep(0.8)
            try:
                # Gate on the mode the CURRENT recording was started in, not on
                # the config. Live-apply keeps controller.live_typing fresh, but
                # a recording already in flight finishes in the mode it began
                # with (see AppController.start_recording), and the streamer has
                # to agree with it: streaming into a recording that will finish
                # via _finish_final types the text twice.
                if not controller.live_typing_active:
                    continue
                if not controller.is_recording():
                    continue
                snap = controller.preview_snapshot()
                if snap is None or len(snap) < int(0.5 * 16000):
                    continue
                # transcribe_stream serializes on the model lock, so the live
                # preview can't race the warm-up or the final release pass. Read
                # the transcriber/inserter off the controller so a live model or
                # insertion-mode change is picked up here too.
                raw = controller.transcriber.transcribe_stream(normalize_gain(snap))
                # LiveTyper tracks emitted word count -> emits each word once, no doubling.
                had_streamed = controller.live_typer._emitted > 0
                new_words = controller.live_typer.feed(raw)
                if new_words:
                    controller.inserter.insert((" " if had_streamed else "") + new_words)
            except Exception:
                pass  # streaming is best-effort; final release pass still runs

    threading.Thread(target=stream_loop, daemon=True).start()

    def apply_settings():
        """Live-apply saved settings in-process — no restart, so there is no
        single-instance race and no lost dictation."""
        nonlocal hotkeys, current_model_sig, current_hotkey

        # Hotkey: rebuild the global listener ONLY when the hotkey itself
        # changed. Any other Save (a toggle, the model, the mic) must leave the
        # live gesture untouched — otherwise changing a setting mid-recording
        # would strand that recording with a fresh IDLE gesture that can never
        # stop it. (A hotkey change mid-recording is still safe: the new
        # gesture's is_recording toggle fallback stops the in-flight clip.)
        new_hotkey = cfg.get("hotkey")
        if new_hotkey != current_hotkey:
            current_hotkey = new_hotkey
            try:
                hotkeys.stop()
            except Exception:
                log.exception("stopping old hotkey listener failed")
            hotkeys = build_hotkeys()
            hotkeys.start()
        overlay.set_hotkey_label(_hotkey_label(cfg))

        # Text pipeline: cheap to rebuild in place (build_cleaner re-attaches
        # the dictionary replacements provider to the new instance).
        controller.cleaner = build_cleaner()
        controller.inserter = TextInserter(
            mode="keystroke" if cfg.get("live_typing") else cfg.get("insertion_mode"))
        controller.live_typing = cfg.get("live_typing")
        controller.filter_hallucinations = cfg.get("filter_hallucinations")
        # Reschedules the running cap timer (and its warning) from elapsed time,
        # so a mid-recording change keeps the interval and the notice in step.
        controller.set_max_recording_seconds(cfg.get("max_recording_seconds"))

        # Language and beam size are read per transcribe() call -> live, no reload.
        lang = cfg.get("language")
        controller.transcriber.language = None if lang == "auto" else lang
        controller.transcriber.beam_size = cfg.get("beam_size")

        # Microphone: the recorder's device_provider re-resolves on the next
        # start(), so a mic change needs nothing rebuilt here.

        # Pre-roll: live-apply the toggle — arm the continuous stream when on,
        # release it when off — instead of only honoring it at the next launch.
        _apply_preroll(recorder, bool(cfg.get("preroll_enabled")),
                       cfg.get("preroll_seconds"), controller.is_recording)

        # Toggles the Hub exposes. Each is applied independently and
        # best-effort: one failure must not swallow the rest of the Save.
        try:
            overlay.set_pill_enabled(bool(cfg.get("show_pill")))
        except Exception:
            log.exception("applying show_pill failed")
        try:
            history.enabled = bool(cfg.get("history_enabled"))
        except Exception:
            log.exception("applying history_enabled failed")
        # Launch-at-login is applied by the Settings switch itself (its handler
        # calls startup.set_enabled, which also clears a Task Manager disable).
        # Re-applying it from config on every unrelated Save would silently
        # re-enable us over a disable the user made in Task Manager, so it is
        # deliberately NOT reapplied here.

        # Model: reload on a background thread only if name/device changed.
        new_sig = (active_model_name(), cfg.get("device"))
        if new_sig != current_model_sig:
            current_model_sig = new_sig
            # Claim the generation NOW, on the UI thread, so the ordering of
            # rapid Saves is the ordering the user made them in.
            generation = reload_gate.begin()
            bridge.notify.emit("Loading model…")

            def reload_model(sig=new_sig, generation=generation):
                nonlocal current_model_sig
                name, device = sig
                try:
                    # The tray exists by now, so download/copy progress for a
                    # newly chosen model is reported live rather than buffered.
                    new_trans = build_transcriber(
                        name, device, notify=bridge.notify.emit)
                    new_trans.warm_up()
                except Exception as e:
                    log.exception("model reload failed")
                    if reload_gate.is_current(generation):
                        # Nothing was installed, so the recorded signature is a
                        # lie — clear it or a Save back to the previous model
                        # would look like "no change" and never reload.
                        current_model_sig = None
                        bridge.notify.emit("Model reload failed: %s" % e)
                    return

                def install():
                    controller.transcriber = new_trans

                if reload_gate.commit(generation, install):
                    bridge.notify.emit("Model ready (%s)." % name)
                else:
                    # A newer Save superseded this one while it was loading.
                    # Installing now would leave the app running a model the
                    # config no longer names.
                    log.info("discarding superseded model reload (%s)", name)

            run_async(reload_model)
        else:
            bridge.notify.emit("Settings applied.")

    # The Hub (feat/unified-hub) folds Settings INTO the Dashboard:
    #   Dashboard(config, history, on_settings_saved=...) plus .open_settings().
    # That PR may delete SettingsWindow outright, so try the Hub contract first
    # and only fall back to master's separate settings window — which means this
    # branch runs standalone and needs no edit after the Hub merges.
    # Detected from the signature rather than by catching TypeError, so a real
    # TypeError raised inside the Hub's own constructor is not mistaken for
    # "the Hub isn't here yet" and quietly swallowed.
    try:
        dashboard_params = inspect.signature(Dashboard).parameters
    except (TypeError, ValueError):
        dashboard_params = {}

    settings = None
    if "on_settings_saved" in dashboard_params:
        dashboard = Dashboard(cfg, history, on_settings_saved=apply_settings)
    else:
        from rekounts.ui.settings_window import SettingsWindow
        settings = SettingsWindow(cfg, on_saved=apply_settings)
        dashboard = Dashboard(cfg, history, on_open_settings=settings.show)

    open_settings = getattr(dashboard, "open_settings", None)
    if not callable(open_settings):
        open_settings = settings.show if settings is not None else dashboard.open_and_raise

    # A finished dictation should appear in an open Hub without a page switch.
    # bridge.result is GUI-thread-marshaled and is already connected to
    # history.add above, so connecting here runs AFTER it — the row is written
    # before the visible page re-queries the store.
    on_recorded = getattr(dashboard, "on_result_recorded", None)
    if callable(on_recorded):
        bridge.result.connect(on_recorded)

    def mic_changed(name):
        cfg.set("microphone", name)
        cfg.save()
        # device_provider re-resolves on the next start(); nothing to rebuild.
        bridge.notify.emit("Microphone: %s — applies to the next dictation."
                           % (name or "System default"))

    def language_changed(code):
        cfg.set("language", code)
        cfg.save()
        # Transcriber reads .language per transcribe() call, so this is live.
        # Read it off the controller so a live model reload isn't clobbered.
        controller.transcriber.language = None if code == "auto" else code
        bridge.notify.emit("Language changed — applies to the next dictation.")

    tray = TrayApp(
        app, on_open_settings=open_settings, on_quit=app.quit,
        on_open_dashboard=dashboard.open_and_raise,
        config=cfg, languages=LANGUAGES,
        on_mic_changed=mic_changed, on_language_changed=language_changed,
        # The one gate for EVERY toast, read live so toggling "Tray
        # notifications" in Settings applies at once. Living inside TrayApp.notify
        # means tray-originated toasts (mic/language/update-check) are gated too,
        # instead of only the ones routed through the bridge.
        notifications_enabled=lambda: bool(cfg.get("show_notifications")))
    # The tray is the first real notification sink; anything raised earlier in
    # startup (an invalid hotkey falling back to the default, a risky-combo
    # warning) is replayed now instead of having been dropped. The switch is
    # enforced inside tray.notify, so the sink hands everything straight to it.
    bridge.notices.attach(tray.notify)

    # Launch-at-login: reconcile the registry with the config flag, honor any
    # Task Manager disable (of the old name AND ours), and clear the pre-rename
    # entry. The full rules and their ordering live on _reconcile_startup.
    _reconcile_startup(cfg)

    # macOS permission onboarding — after the tray is attached so the notices
    # actually show as toasts rather than sitting in the buffer.
    _report_missing_permissions(bridge.notify.emit)

    def cleanup():
        # Release the mic (pre-roll holds it open) and the history db cleanly.
        try:
            recorder.close()
        except Exception:
            pass
        try:
            history.close()
        except Exception:
            pass

    app.aboutToQuit.connect(cleanup)

    log.info("Rekounts started (device=%s, hotkey=%s)",
             transcriber.device, cfg.get("hotkey"))
    # tray.notify enforces the notifications switch itself now.
    tray.notify("Rekounts is running. Hold or double-tap %s to dictate."
                % cfg.get("hotkey"))
    code = app.exec()
    hotkeys.stop()
    sys.exit(code)


if __name__ == "__main__":
    main()
