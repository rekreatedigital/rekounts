"""Render the Scratchpad to PNGs for the README and the PR.

Same spirit — and the same two hard-won details — as ``tools/capture_hub_shots.py``
and ``tools/capture_pill_shots.py``: build the REAL widget, render it at 2x
without ever showing it, write the result to ``docs/img/``. Nothing flashes on
screen, no single-instance mutex is taken and no keyboard hook is installed, so
this is safe to run while the app itself is running.

  * the **native** Qt platform, never ``offscreen`` — the offscreen plugin ships
    no font database, so every glyph renders as a tofu box;
  * rendering with ``QWidget.render()`` instead of ``show()`` + ``grab()``.

The pad paints its own drop shadow (rather than using a QGraphicsDropShadowEffect)
precisely so that it survives ``render()`` — see the note in
``rekounts/ui/scratchpad.py``. The shadow needs something to fall on, so each
shot is composited onto a slice of the Hub's own background colour.

Safety: the pad reads and writes ``%APPDATA%/Rekounts/scratchpad.json``. Before a
single line of ``rekounts`` is imported, this module repoints ``APPDATA`` at a
fresh temp directory — the same seam ``tests/conftest.py`` uses — so the real
note is neither read nor overwritten by a screenshot run.

    .venv\\Scripts\\python.exe tools\\capture_scratchpad_shots.py

Rerun it after any change to ui/scratchpad.py so the docs never drift from the app.
"""
import os
import shutil
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

# --- data safety: do this BEFORE importing anything from rekounts ------------
SANDBOX = Path(tempfile.mkdtemp(prefix="rekounts-pad-shots-"))
os.environ["APPDATA"] = str(SANDBOX)
# Never "offscreen" (no font database -> tofu). Clear an inherited override.
os.environ.pop("QT_QPA_PLATFORM", None)

from PySide6 import QtCore, QtGui, QtWidgets  # noqa: E402

from rekounts import paths  # noqa: E402
from rekounts.scratchpad_store import ScratchpadStore  # noqa: E402
from rekounts.ui import theme  # noqa: E402
from rekounts.ui.scratchpad import Scratchpad  # noqa: E402

OUT_DIR = REPO / "docs" / "img"
SCALE = 2               # devicePixelRatio of the output PNGs
PAD_W, PAD_H = 330, 380  # the pad's own default size
# Room around the note so its shadow has somewhere to fall.
MARGIN = 26

# A note that shows every control doing something, without saying anything about
# the machine it was captured on.
HEADING = "Launch notes"
BULLETS = ["Sign the installer before Friday",
           "Reply to the three beta testers",
           "Re-record the demo voice-over"]
TAIL = "Dictated straight into the pad — no Notepad, no copy-paste."


def _compose_note(pad):
    """Type the sample note through the pad's OWN formatting API.

    Building it with the real toolbar handlers rather than with a blob of
    canned HTML means the screenshot can only ever show formatting the app can
    actually produce — if a button breaks, the picture breaks with it.
    """
    edit = pad.edit
    cursor = edit.textCursor()
    edit.setTextCursor(cursor)

    pad.format_buttons["bold"].setChecked(True)
    cursor = edit.textCursor()
    cursor.insertText(HEADING, edit.currentCharFormat())
    pad.format_buttons["bold"].setChecked(False)

    cursor = edit.textCursor()
    cursor.insertBlock()
    edit.setTextCursor(cursor)
    pad.format_buttons["bullets"].setChecked(True)
    for i, line in enumerate(BULLETS):
        cursor = edit.textCursor()
        if i:
            cursor.insertBlock()
        cursor.insertText(line, edit.currentCharFormat())
        edit.setTextCursor(cursor)

    # Leave the list on a FRESH block before switching bullets off: unchecking
    # removes whichever block the caret is in, so doing it here would silently
    # strip the bullet from the last item.
    cursor = edit.textCursor()
    cursor.insertBlock()
    edit.setTextCursor(cursor)
    pad.format_buttons["bullets"].setChecked(False)
    # The tail is what a dictation looks like when it lands: plain text that
    # inherited the caret's formatting.
    pad.append_dictation(TAIL)


def _grab(pad) -> QtGui.QPixmap:
    """Render the never-shown pad onto the app's background colour."""
    w, h = pad.width() + MARGIN * 2, pad.height() + MARGIN * 2
    out = QtGui.QPixmap(w * SCALE, h * SCALE)
    out.setDevicePixelRatio(SCALE)
    out.fill(QtGui.QColor(theme.BG))

    painter = QtGui.QPainter(out)
    pad.render(painter, QtCore.QPoint(MARGIN, MARGIN),
               QtGui.QRegion(pad.rect()), QtWidgets.QWidget.DrawChildren)
    painter.end()
    return out


def _settle(app):
    app.processEvents()
    app.sendPostedEvents(None, QtCore.QEvent.DeferredDelete)
    app.processEvents()


def capture(pad, app, name, chrome):
    """Write one shot. ``chrome`` is the hover fade position, 0.0 or 1.0."""
    pad._set_chrome(chrome)
    _settle(app)
    # The first render is what activates the layouts of a never-shown widget;
    # throw it away so the saved one is drawn against settled geometry.
    _grab(pad)
    _settle(app)
    path = OUT_DIR / f"{name}.png"
    _grab(pad).save(str(path), "PNG")
    print(f"wrote {path.relative_to(REPO)}  "
          f"({PAD_W}x{PAD_H} @{SCALE}x, {path.stat().st_size / 1024:.0f} KB)")


def main():
    # Belt and braces: prove the sandbox took before anything opens a file. If
    # it ever doesn't, the next lines would overwrite the developer's own note.
    if paths.app_data_dir() != SANDBOX / "Rekounts":
        raise SystemExit(
            f"refusing to run: app data resolves to {paths.app_data_dir()}, "
            f"not the sandbox {SANDBOX / 'Rekounts'}")

    app = QtWidgets.QApplication(sys.argv)
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    store = ScratchpadStore(path=SANDBOX / "Rekounts" / "scratchpad.json")

    # 1) An empty pad, at rest — the placeholder and the quiet toolbar.
    blank = Scratchpad(store=store)
    blank.resize(PAD_W, PAD_H)
    _settle(app)
    capture(blank, app, "scratchpad-empty", chrome=0.0)
    blank.deleteLater()
    _settle(app)

    # 2) A written note, at rest — no window controls, one clean surface.
    pad = Scratchpad(store=store)
    pad.resize(PAD_W, PAD_H)
    _compose_note(pad)
    _settle(app)
    capture(pad, app, "scratchpad", chrome=0.0)

    # 3) The same note with the pointer over it — close and minimize faded in.
    capture(pad, app, "scratchpad-hover", chrome=1.0)

    pad.deleteLater()
    _settle(app)
    shutil.rmtree(SANDBOX, ignore_errors=True)


if __name__ == "__main__":
    main()
