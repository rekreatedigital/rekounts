"""Render the Hub's pages to PNGs for the README.

Same spirit as ``tools/capture_pill_shots.py``: build the REAL widget, render it
at 2x without ever showing it, write the result to ``docs/img/``. Nothing
flashes on screen, no single-instance mutex is taken and no keyboard hook is
installed, so this is safe to run while the app itself is running.

Two hard-won details are copied from the pill tool and must stay:

* the **native** Qt platform, never ``offscreen`` — the offscreen plugin ships
  no font database, so every glyph renders as a tofu box;
* rendering with ``QWidget.render()`` instead of ``show()`` + ``grab()``.

Safety: the Hub reads config.json and history.db out of ``%APPDATA%/Rekounts``.
Before a single line of ``rekounts`` is imported, this module repoints
``APPDATA`` at a fresh temp directory — the same seam ``tests/conftest.py``
uses — so the sample data below is written to a throwaway sandbox and the real
history is neither read nor touched. Two things are also swapped out so the
published images can't leak the machine they were captured on:

* the microphone list (real device names) -> two generic placeholders;
* the "Where your data lives" path (the sandbox temp dir) -> the generic
  ``C:\\Users\\you\\AppData\\Roaming\\Rekounts`` a user would see;
* the **Processing** row -> hidden, because this script runs from source and
  the packaged build the README is illustrating has no GPU stack in it.

Everything else on screen is the app rendering its own state.

    .venv\\Scripts\\python.exe tools\\capture_hub_shots.py

Rerun it after any change to ui/dashboard.py, ui/settings_page.py or ui/theme.py
so the README never drifts from the app.
"""
import os
import random
import shutil
import sys
import tempfile
from datetime import datetime, time, timedelta
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

# --- data safety: do this BEFORE importing anything from rekounts ------------
# paths.app_data_dir() re-reads APPDATA on every call, so repointing it here
# moves config.json, history.db, the log folder and the model store into a
# throwaway sandbox for the life of this process.
SANDBOX = Path(tempfile.mkdtemp(prefix="rekounts-hub-shots-"))
os.environ["APPDATA"] = str(SANDBOX)
# Never "offscreen" (no font database -> tofu). Clear an inherited override.
os.environ.pop("QT_QPA_PLATFORM", None)

from PySide6 import QtCore, QtGui, QtWidgets  # noqa: E402

from rekounts import paths, startup  # noqa: E402
from rekounts.config import Config  # noqa: E402
from rekounts.history import History  # noqa: E402
from rekounts.ui import platform_text, settings_page, theme  # noqa: E402
from rekounts.ui.dashboard import Dashboard  # noqa: E402
from scripts.seed_history import SAMPLES  # noqa: E402

OUT_DIR = REPO / "docs" / "img"
SCALE = 2               # devicePixelRatio of the output PNGs
WIN_W, WIN_H = 900, 600  # logical px — near the Hub's own default (880 x 620)
CORNER = 10             # rounded-corner radius of the framed screenshot

# Stand-ins for the capture machine's real hardware and real data folder.
FAKE_MICS = [("Microphone (USB Audio Device)", "Microphone (USB Audio Device)"),
             ("Headset Microphone", "Headset Microphone")]
GENERIC_DATA_DIR = r"C:\Users\you\AppData\Roaming\Rekounts"

# Obviously-generic jargon for the Dictionary page.
DICTIONARY = [("faster-whisper", "faster whisper"),
              ("Kubernetes", "koober-net-ees"),
              ("PostgreSQL", "post-gress-cue-el"),
              ("Rekounts", ""),
              ("webhook", "web hook")]

# Times of day the sample dictations happen at, so every day reads plausibly
# instead of clustering. Sorted; a subset is used per day.
SLOTS = [(9, 14), (10, 41), (11, 58), (13, 22), (15, 7), (16, 49), (18, 33)]
DAYS = 21               # exactly the span of the Insights bar chart
QUIET_DAYS = (5, 11, 12)  # gaps, so streaks and the chart aren't suspiciously perfect


# ------------------------------------------------------------------ sample data
def _sentences(rng):
    """Endless rotation of the sample sentences, reshuffled each time the pool
    empties — the same line never lands twice in one screenful."""
    pool = []
    while True:
        if not pool:
            pool = rng.sample(SAMPLES, len(SAMPLES))
        yield pool.pop()


def seed(history):
    """Fill the throwaway DB with the fake dictations scripts/seed_history.py
    already ships, on a fixed schedule so reruns don't reshuffle the shots."""
    rng = random.Random(11)
    sentences = _sentences(rng)
    now = datetime.now().astimezone()
    today = now.date()
    total = 0
    for back in range(DAYS):
        if back in QUIET_DAYS:
            continue
        day = today - timedelta(days=back)
        slots = SLOTS
        if back == 0:
            # Never dictate in the future: today only uses slots already passed,
            # and falls back to "a few minutes ago" first thing in the morning.
            slots = [s for s in SLOTS if s <= (now.hour, now.minute)]
            if not slots:
                earlier = now - timedelta(minutes=9)
                slots = [(earlier.hour, earlier.minute)]
        n = min(len(slots), rng.randint(2, 5))
        for h, m in sorted(rng.sample(slots, n)):
            text, inserted = next(sentences)
            when = datetime.combine(day, time(h, m), tzinfo=now.tzinfo)
            words = len(text.split())
            duration = round(words / rng.uniform(1.9, 3.0), 1)  # ~115-180 wpm
            history.add(text, text, duration, inserted=inserted, when=when)
            total += 1
    for word, sounds_like in DICTIONARY:
        history.add_dictionary_word(word, sounds_like)
    return total


# --------------------------------------------------------------------- render
def _grab(widget) -> QtGui.QPixmap:
    """Render a never-shown widget tree to a pixmap at SCALE x."""
    size = widget.size()
    pix = QtGui.QPixmap(size.width() * SCALE, size.height() * SCALE)
    pix.setDevicePixelRatio(SCALE)
    pix.fill(QtGui.QColor(theme.BG))
    widget.render(pix, QtCore.QPoint(0, 0),
                  QtGui.QRegion(widget.rect()),
                  QtWidgets.QWidget.DrawChildren)
    return pix


def _framed(pix: QtGui.QPixmap) -> QtGui.QPixmap:
    """Round the corners and add a hairline border.

    The Hub's background (#0e0f13) is a near-match for GitHub's dark canvas, so
    without an edge the screenshot bleeds into the page there.
    """
    w = pix.width() / pix.devicePixelRatio()
    h = pix.height() / pix.devicePixelRatio()
    out = QtGui.QPixmap(pix.size())
    out.setDevicePixelRatio(SCALE)
    out.fill(QtCore.Qt.transparent)
    p = QtGui.QPainter(out)
    p.setRenderHint(QtGui.QPainter.Antialiasing)
    clip = QtGui.QPainterPath()
    clip.addRoundedRect(QtCore.QRectF(0, 0, w, h), CORNER, CORNER)
    p.setClipPath(clip)
    p.drawPixmap(0, 0, pix)
    p.setClipping(False)
    p.setPen(QtGui.QPen(QtGui.QColor(theme.BORDER), 1))
    p.setBrush(QtCore.Qt.NoBrush)
    p.drawRoundedRect(QtCore.QRectF(0.5, 0.5, w - 1, h - 1), CORNER, CORNER)
    p.end()
    return out


def _settle(app):
    """Let queued work (layout, deleteLater from a page refresh) finish.

    There is no event loop here, so widgets a refresh() dropped would otherwise
    linger as children and paint over the new ones.
    """
    app.processEvents()
    app.sendPostedEvents(None, QtCore.QEvent.DeferredDelete)
    app.processEvents()


def _generalize_data_dir(page):
    """Swap the sandbox temp path in Settings for the path a user would see."""
    sandbox = str(SANDBOX)
    for label in page.findChildren(QtWidgets.QLabel):
        if label.text().startswith(sandbox):
            label.setText(GENERIC_DATA_DIR)


def capture(dash, app, page_name, name):
    # Looked up by nav name, not by index, so reordering the Hub's pages can
    # never silently capture the wrong one.
    index, page = next((i, p) for i, (n, p) in enumerate(dash.pages)
                       if n == page_name)
    dash.show_page(index)
    refresh = getattr(page, "refresh", None)
    if callable(refresh):
        refresh()          # showEvent never fires — nothing is ever shown
    _settle(app)
    # The first render is what activates the layouts (QWidget.render() does that
    # for a never-shown widget); throw it away so the saved one is drawn against
    # settled geometry — scroll bars included.
    _grab(dash)
    _settle(app)
    path = OUT_DIR / f"{name}.png"
    _framed(_grab(dash)).save(str(path), "PNG")
    size_kb = path.stat().st_size / 1024
    print(f"wrote {path.relative_to(REPO)}  "
          f"({WIN_W}x{WIN_H} @{SCALE}x, {size_kb:.0f} KB)")


def main():
    # Belt and braces: prove the sandbox took before anything opens a DB. If it
    # ever doesn't, the next lines would seed the user's real history.
    if paths.app_data_dir() != SANDBOX / "Rekounts":
        raise SystemExit(
            f"refusing to run: app data resolves to {paths.app_data_dir()}, "
            f"not the sandbox {SANDBOX / 'Rekounts'}")

    app = QtWidgets.QApplication(sys.argv)
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    # No real device scan (the names would ship in the screenshot) and no
    # registry read for launch-at-login — this is a picture, not a diagnosis.
    settings_page.microphone_options = lambda: FAKE_MICS
    startup.is_enabled = lambda *a, **k: False
    startup.set_enabled = lambda *a, **k: None
    # Capture the app as a DOWNLOADER sees it. This script necessarily runs
    # from source, where the Processing row exists; the packaged build it
    # illustrates has no GPU stack in it and so has no such row. Same reasoning
    # as the fake mics and the generic data folder above — the published image
    # must not show something that is only true of the capture machine.
    platform_text.gpu_choice_applies = lambda *a, **k: False

    config = Config(path=SANDBOX / "Rekounts" / "config.json")
    history = History(path=SANDBOX / "Rekounts" / "history.db")
    n = seed(history)
    print(f"seeded {n} sample dictations into {history.path}")

    dash = Dashboard(config, history)
    dash.resize(WIN_W, WIN_H)
    _generalize_data_dir(dash.settings)
    _settle(app)

    for page_name, name in (("Dictation", "hub-dictation"),
                            ("Insights", "hub-insights"),
                            ("Dictionary", "hub-dictionary"),
                            ("Settings", "hub-settings")):
        capture(dash, app, page_name, name)

    dash.deleteLater()
    history.close()
    _settle(app)
    shutil.rmtree(SANDBOX, ignore_errors=True)


if __name__ == "__main__":
    main()
