"""The log has to actually contain the failure.

Two defects meet here, and they compound, so they are tested together:

  * the log file was opened in the machine's locale codepage (cp1252 on a
    typical Windows install), so ANY record carrying a character outside that
    codepage — a non-Latin microphone name, a non-ASCII Windows username in a
    path, a traceback quoting either — raised inside ``logging`` and wrote
    nothing at all. The "--- Logging error ---" report goes to stderr, and
    under ``pythonw`` (run.bat and the packaged .exe) there is no stderr;

  * nothing installed ``sys.excepthook``, ``threading.excepthook`` or
    ``faulthandler``, so an exception raised in a Qt slot or on a worker thread
    unwound into C / the threading machinery rather than into ``main()``'s
    try/except, and its traceback went to that same absent stderr. The log file
    stayed at 0 bytes while the app misbehaved.

Compounding: a crash traceback is exactly the kind of record most likely to
carry an odd character, so the encoding bug was at its most damaging on the
records the crash handler exists to capture.

These tests assert on the bytes in the real rotating log file rather than on
``caplog``, because "the handler accepted the record" is precisely what was
never in doubt — what failed was the write.
"""
import faulthandler
import logging
import sys
import threading

import pytest

from rekounts import __main__ as app_main


@pytest.fixture
def log_file(monkeypatch, tmp_path):
    """A real rotating log built by setup_logging(), pointed at tmp_path.

    Root is emptied first because basicConfig() is a no-op once the root logger
    has handlers, and pytest's logging plugin has attached one by the time a
    test runs — in production setup_logging() is the first thing to touch it.
    Restored afterwards: basicConfig mutates global state, and a leaked file
    handler on Windows keeps the temp directory locked.
    """
    root = logging.getLogger()
    handlers, level = list(root.handlers), root.level
    root.handlers[:] = []
    monkeypatch.setattr(app_main, "default_config_path",
                        lambda: tmp_path / "config.json")
    assert app_main.setup_logging() is True
    yield tmp_path / "logs" / "rekounts.log"
    for handler in root.handlers:
        if handler not in handlers:
            handler.close()
    root.handlers[:] = handlers
    root.setLevel(level)


@pytest.fixture
def install_handlers():
    """Call ``install_crash_handlers()``, and undo it afterwards.

    The interpreter defaults are dropped in first, so the chaining the handlers
    do lands on CPython's own hook rather than on pytest's reporting plugin —
    chaining is still exercised, but the crashes these tests cause on purpose
    are not also reported as unhandled thread exceptions. That has to happen
    inside the test rather than in fixture setup, because pytest installs its
    own hook around the call phase, i.e. after fixtures are built.
    """
    hooks = sys.excepthook, threading.excepthook
    enable = faulthandler.enable          # captured before any test patches it

    def install(**kwargs):
        sys.excepthook = sys.__excepthook__
        threading.excepthook = threading.__excepthook__
        return app_main.install_crash_handlers(**kwargs)

    yield install
    sys.excepthook, threading.excepthook = hooks
    # pytest arms faulthandler on stderr for the session; put that back rather
    # than leaving it pointed at a tmp file that is about to be deleted.
    enable()


def _text(path):
    return path.read_text(encoding="utf-8", errors="replace")


def _flush():
    for handler in logging.getLogger().handlers:
        handler.flush()


# --- the log file must survive a character the codepage cannot spell -------
def test_a_non_latin_microphone_name_is_written_not_dropped(log_file):
    # device_utils reports whatever Windows calls the device; on a Russian,
    # Greek or Japanese system that is not cp1252-encodable. Before the fix this
    # record vanished entirely — the file did not even grow.
    logging.getLogger("main").info("using microphone %s", "\u041c\u0438\u043a\u0440\u043e\u0444\u043e\u043d (Realtek)")
    _flush()
    assert "\u041c\u0438\u043a\u0440\u043e\u0444\u043e\u043d (Realtek)" in _text(log_file)


def test_a_path_with_a_non_ascii_username_is_written(log_file):
    logging.getLogger("main").warning(
        "could not read %s", "C:\\Users\\Zo\u00eb\\AppData\\Roaming\\Rekounts")
    _flush()
    assert "Zo\u00eb" in _text(log_file)


def test_an_unencodable_character_cannot_break_the_record(log_file):
    # Belt and braces: utf-8 covers every str Python can hold EXCEPT a lone
    # surrogate, which Windows path APIs can hand back. errors= keeps such a
    # record readable instead of losing it the way cp1252 lost everything.
    logging.getLogger("main").info("odd device name: %s", "mic\udcff")
    _flush()
    assert "odd device name" in _text(log_file)


# --- unhandled failures must reach that file ------------------------------
def test_a_worker_thread_traceback_reaches_the_log(log_file, install_handlers):
    install_handlers()

    def boom():
        raise RuntimeError("transcription worker died")

    thread = threading.Thread(target=boom, name="worker")
    thread.start()
    thread.join()
    _flush()

    written = _text(log_file)
    assert "transcription worker died" in written
    assert "RuntimeError" in written
    assert "worker" in written          # which thread it was


def test_a_main_thread_traceback_reaches_the_log(log_file, install_handlers):
    install_handlers()
    try:
        raise ValueError("nothing caught this")
    except ValueError:
        sys.excepthook(*sys.exc_info())
    _flush()
    assert "nothing caught this" in _text(log_file)


def test_a_crashing_traceback_with_odd_characters_still_lands(log_file,
                                                              install_handlers):
    # The two defects together: the crash handler is worthless if the record it
    # writes is the kind the file handler used to throw away.
    install_handlers()

    def boom():
        raise RuntimeError("mic \u041c\u0438\u043a\u0440\u043e\u0444\u043e\u043d disappeared")

    thread = threading.Thread(target=boom, name="worker")
    thread.start()
    thread.join()
    _flush()
    assert "\u041c\u0438\u043a\u0440\u043e\u0444\u043e\u043d" in _text(log_file)


def test_a_normal_thread_exit_is_not_logged_as_a_crash(log_file, install_handlers):
    install_handlers()

    def quit_quietly():
        raise SystemExit(0)

    thread = threading.Thread(target=quit_quietly, name="worker")
    thread.start()
    thread.join()
    _flush()
    assert "unhandled exception" not in _text(log_file)


def test_keyboard_interrupt_is_left_to_the_default_hook(log_file,
                                                        install_handlers):
    install_handlers()
    try:
        raise KeyboardInterrupt
    except KeyboardInterrupt:
        sys.excepthook(*sys.exc_info())
    _flush()
    assert "unhandled exception" not in _text(log_file)


# --- hard native crashes get their own file -------------------------------
def test_faulthandler_is_armed_against_its_own_file(log_file, install_handlers,
                                                    tmp_path):
    # A separate file from rekounts.log on purpose: faulthandler writes raw
    # bytes to a file descriptor from a dying process, so it must not be able to
    # interleave half a traceback into a normal log line.
    assert install_handlers() is True
    assert faulthandler.is_enabled()
    assert (tmp_path / "logs" / "rekounts-crash.log").exists()


def test_an_old_crash_file_survives_the_relaunch_after_it(log_file, tmp_path,
                                                          install_handlers):
    # The user restarts, THEN reports the crash. Truncating on every launch
    # would delete the evidence before anyone could read it.
    crash = tmp_path / "logs" / "rekounts-crash.log"
    crash.parent.mkdir(parents=True, exist_ok=True)
    crash.write_text("Windows fatal exception: access violation\n",
                     encoding="utf-8")
    install_handlers()
    assert "access violation" in crash.read_text(encoding="utf-8")


def test_a_runaway_crash_file_is_not_allowed_to_grow_forever(log_file, tmp_path,
                                                             install_handlers):
    crash = tmp_path / "logs" / "rekounts-crash.log"
    crash.parent.mkdir(parents=True, exist_ok=True)
    crash.write_text("x" * (app_main._MAX_CRASH_LOG_BYTES + 1), encoding="utf-8")
    install_handlers()
    assert crash.stat().st_size == 0


def test_a_broken_crash_file_does_not_stop_startup(log_file, install_handlers,
                                                   monkeypatch):
    # Losing native-crash capture is an annoyance; refusing to start because of
    # it would be the silent startup death setup_logging() already avoids.
    monkeypatch.setattr(app_main.faulthandler, "enable",
                        lambda *a, **k: (_ for _ in ()).throw(OSError("nope")))
    assert install_handlers() is False
    # The Python-level hooks are still installed — they are the valuable half.
    assert sys.excepthook is not sys.__excepthook__
    assert threading.excepthook is not threading.__excepthook__


# --- Qt's own complaints -------------------------------------------------
def test_qt_warnings_reach_the_log(log_file):
    QtCore = pytest.importorskip("PySide6.QtCore")
    previous = QtCore.qInstallMessageHandler(None)
    try:
        app_main.install_qt_message_handler()
        QtCore.qWarning("QObject::connect: No such slot")
        _flush()
        assert "No such slot" in _text(log_file)
    finally:
        QtCore.qInstallMessageHandler(previous)


def test_a_qt_slot_exception_reaches_the_log(log_file, install_handlers):
    """The case that motivated all of this.

    Qt invokes a slot from C++, so an exception raised inside one never unwinds
    into main()'s try/except — PySide6 hands it to sys.excepthook instead, which
    until now was the default hook writing to a stderr that does not exist under
    pythonw.
    """
    QtCore = pytest.importorskip("PySide6.QtCore")
    install_handlers()

    class Emitter(QtCore.QObject):
        fired = QtCore.Signal()

    def slot():
        raise RuntimeError("slot blew up")

    emitter = Emitter()
    emitter.fired.connect(slot)
    try:
        emitter.fired.emit()
    except RuntimeError:
        # Some PySide6 builds re-raise into the emitting frame as well; what
        # this test is about is what the LOG got, either way.
        pass
    _flush()
    assert "slot blew up" in _text(log_file)
