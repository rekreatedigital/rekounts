"""Render the Send Feedback dialog and the tray menu to PNGs.

Same rules as ``tools/capture_hub_shots.py`` — build the REAL widget, render it
at 2x without ever showing it, write to ``docs/img/``. Nothing flashes on
screen, no single-instance mutex is taken, no keyboard hook is installed, and
the tray icon is hidden the moment it is created, so this is safe to run while
the app itself is running.

    .venv\\Scripts\\python.exe tools\\capture_feedback_shots.py

Safety, which matters more here than anywhere else in the repo: this is a
picture of the window whose whole job is to prove it leaks nothing. ``APPDATA``
is repointed at a throwaway sandbox before ``rekounts`` is imported, and the
capture machine's own identity is pinned to the same generic stand-ins the
scrubber would produce anyway — so a shot taken on any machine looks identical
and names none of them. If the dialog ever did leak something, the assertion at
the end of ``main()`` fails rather than publishing it.

Rerun after any change to ui/feedback_dialog.py, feedback.py or ui/tray.py.
"""
import os
import shutil
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

# --- data safety: do this BEFORE importing anything from rekounts ------------
SANDBOX = Path(tempfile.mkdtemp(prefix="rekounts-feedback-shots-"))
os.environ["APPDATA"] = str(SANDBOX)
# Never "offscreen" (no font database -> tofu). Clear an inherited override.
os.environ.pop("QT_QPA_PLATFORM", None)
# The capture machine's own name and folders, replaced by the generic ones a
# reader should see. The dialog scrubs these anyway; pinning them means the
# image is byte-identical wherever it is regenerated.
os.environ["USERNAME"] = "you"
os.environ["USERPROFILE"] = r"C:\Users\you"
os.environ["COMPUTERNAME"] = "PC"
# 2x output, asked for at the Qt level rather than by rendering into an
# oversized pixmap. The tray menu is drawn by the Windows theme engine, which
# ignores a manually scaled render target and hands back a blank rectangle;
# widget.grab() at a device pixel ratio the app itself was started with is the
# one path that photographs it. Must be set before QApplication exists.
SCALE = 2
os.environ["QT_SCALE_FACTOR"] = str(SCALE)
# The capture must not inherit the monitor's own scaling on top of that, or the
# same script would produce different-sized images on different machines.
os.environ["QT_ENABLE_HIGHDPI_SCALING"] = "0"

from PySide6 import QtCore, QtGui, QtWidgets  # noqa: E402

from rekounts import paths  # noqa: E402
from rekounts.config import Config  # noqa: E402
from rekounts.ui import theme  # noqa: E402
from rekounts.ui.feedback_dialog import FeedbackDialog  # noqa: E402
from rekounts.ui.tray import TrayApp  # noqa: E402

OUT_DIR = REPO / "docs" / "img"
DIALOG_W, DIALOG_H = 600, 560
CORNER = 10

LANGUAGES = [("Auto-detect", "auto"), ("English", "en"), ("Tagalog", "tl")]

# Where the tray menu is popped up: far outside any real monitor, so it lays
# itself out properly without ever being seen. See capture_menu().
OFFSCREEN = QtCore.QPoint(-8000, -8000)


def _grab(widget) -> QtGui.QPixmap:
    """The widget's own pixels, at the app's 2x device pixel ratio."""
    return widget.grab()


def _framed(pix: QtGui.QPixmap) -> QtGui.QPixmap:
    """Rounded corners and a hairline, so the near-black window does not bleed
    into GitHub's dark canvas."""
    w = pix.width() / pix.devicePixelRatio()
    h = pix.height() / pix.devicePixelRatio()
    out = QtGui.QPixmap(pix.size())
    out.setDevicePixelRatio(pix.devicePixelRatio())
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
    app.processEvents()
    app.sendPostedEvents(None, QtCore.QEvent.DeferredDelete)
    app.processEvents()


def _save(pix, name, framed=True):
    path = OUT_DIR / f"{name}.png"
    (_framed(pix) if framed else pix).save(str(path), "PNG")
    print(f"wrote {path.relative_to(REPO)}  ({path.stat().st_size / 1024:.0f} KB)")


def capture_dialog(app, config):
    dialog = FeedbackDialog(config, slug="rekreatedigital/rekounts")
    dialog.resize(DIALOG_W, DIALOG_H)
    _settle(app)
    _grab(dialog)          # first render activates the layouts; throw it away
    _settle(app)
    _save(_grab(dialog), "feedback-dialog")
    block = dialog.diagnostics()
    dialog.deleteLater()
    return block


def capture_menu(app, config):
    tray = TrayApp(app, on_open_settings=lambda: None, on_quit=lambda: None,
                   on_open_dashboard=lambda: None,
                   on_open_scratchpad=lambda: None,
                   config=config, languages=LANGUAGES)
    tray.tray.hide()       # created and hidden before the event loop paints it
    menu = tray.menu
    # The one widget here that cannot be rendered unshown: a QMenu computes its
    # action rects on the way to being popped up, so render() on a never-shown
    # menu returns an empty rectangle (WA_DontShowOnScreen does not help — the
    # Windows style still paints nothing). So it is popped up far outside every
    # monitor instead: fully laid out and painted, and never visible.
    menu.popup(OFFSCREEN)
    _settle(app)
    # Native-styled rather than part of the Hub's dark theme: it paints its own
    # background and keeps its own frame.
    _save(_grab(menu), "feedback-menu", framed=False)
    menu.hide()
    tray.tray.deleteLater()


def main():
    if paths.app_data_dir() != SANDBOX / "Rekounts":
        raise SystemExit(
            f"refusing to run: app data resolves to {paths.app_data_dir()}, "
            f"not the sandbox {SANDBOX / 'Rekounts'}")

    app = QtWidgets.QApplication(sys.argv)
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    config = Config(path=SANDBOX / "Rekounts" / "config.json")
    block = capture_dialog(app, config)
    capture_menu(app, config)

    # The shot is of the privacy promise, so check it before publishing: the
    # real machine's name must not have survived into the image's text.
    import getpass
    import platform
    for secret in (getpass.getuser(), platform.node(), str(Path.home())):
        if secret and secret.lower() in block.lower():
            raise SystemExit(f"refusing to publish: {secret!r} is in the shot")
    print("checked: the captured block names neither this machine nor its user")

    _settle(app)
    shutil.rmtree(SANDBOX, ignore_errors=True)


if __name__ == "__main__":
    main()
