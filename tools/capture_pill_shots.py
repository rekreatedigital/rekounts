"""Render the dictation pill's states to PNGs for the README.

Renders the real Overlay widget (no mocks) offscreen at 2x DPI, composites each
state onto a neutral backdrop tile so the translucent pill reads the same on
GitHub's light and dark themes, and writes the results to docs/img/.

No microphone, no speech model, no single-instance mutex — safe to run while
the app itself is running. The widget is rendered without ever being shown, so
nothing flashes on screen. Uses the native Qt platform (not "offscreen") on
purpose: offscreen has no real font database, which turns the hover hint text
into tofu boxes. Regenerate after any change to ui/overlay.py:

    .venv\\Scripts\\python.exe tools\\capture_pill_shots.py

(Or use tools\\overlay_demo.py to eyeball the live animation first.)
"""
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PySide6 import QtCore, QtGui, QtWidgets  # noqa: E402

from rekounts.ui.overlay import Overlay  # noqa: E402

OUT_DIR = Path(__file__).resolve().parents[1] / "docs" / "img"
SCALE = 2                 # devicePixelRatio of the output PNGs
TILE_W, TILE_H = 240, 90  # logical px; every tile the same size for a tidy grid

# The app passes the config hotkey uppercased (see __main__._hotkey_label).
HOTKEY_LABEL = "CTRL+WIN"


def _speech_levels(n):
    """A plausible 'someone is talking' waveform, same recipe as overlay_demo."""
    out = []
    for i in range(n):
        t = i * 0.6
        raw = 0.12 + 0.10 * (0.5 + 0.5 * math.sin(t)) \
            + 0.06 * (0.5 + 0.5 * math.sin(t * 2.7))
        out.append(max(0.0, min(1.0, raw * 4.0)))  # what _tick() stores
    return out


def _grab(widget) -> QtGui.QPixmap:
    """Render a translucent widget to a transparent pixmap at SCALE x."""
    size = widget.size()
    pix = QtGui.QPixmap(size.width() * SCALE, size.height() * SCALE)
    pix.setDevicePixelRatio(SCALE)
    pix.fill(QtCore.Qt.transparent)
    widget.render(pix, QtCore.QPoint(0, 0),
                  QtGui.QRegion(widget.rect()),
                  QtWidgets.QWidget.DrawChildren)
    return pix


def _tile(pill: QtGui.QPixmap) -> QtGui.QPixmap:
    """Center a pill render on a light neutral backdrop card."""
    out = QtGui.QPixmap(TILE_W * SCALE, TILE_H * SCALE)
    out.setDevicePixelRatio(SCALE)
    out.fill(QtCore.Qt.transparent)
    p = QtGui.QPainter(out)
    p.setRenderHint(QtGui.QPainter.Antialiasing)

    r = QtCore.QRectF(0.5, 0.5, TILE_W - 1, TILE_H - 1)
    g = QtGui.QLinearGradient(r.topLeft(), r.bottomLeft())
    g.setColorAt(0.0, QtGui.QColor("#eef0f3"))
    g.setColorAt(1.0, QtGui.QColor("#e2e5e9"))
    p.setBrush(g)
    p.setPen(QtGui.QPen(QtGui.QColor("#d2d5da"), 1))
    p.drawRoundedRect(r, 12, 12)

    w = pill.width() / pill.devicePixelRatio()
    h = pill.height() / pill.devicePixelRatio()
    p.drawPixmap(QtCore.QPointF((TILE_W - w) / 2.0, (TILE_H - h) / 2.0), pill)
    p.end()
    return out


def main():
    app = QtWidgets.QApplication(sys.argv)  # noqa: F841 (Qt needs it alive)
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    overlay = Overlay()
    overlay.set_hotkey_label(HOTKEY_LABEL)

    # Drive the widget's state directly instead of via set_state(): the public
    # slot also show()s the window, and these captures must stay invisible.
    def to_state(state):
        overlay._state = state
        overlay._resize_for_state()

    shots = {}

    # idle — the resting pill
    to_state("idle")
    shots["pill-idle"] = _grab(overlay)

    # idle + hover — widens and names the hotkey
    overlay._hovered = True
    overlay._resize_for_state()
    shots["pill-idle-hover"] = _grab(overlay)
    overlay._hovered = False

    # recording — cancel | live waveform | finish
    to_state("recording")
    overlay._levels.extend(_speech_levels(len(overlay._levels)))
    overlay._phase = 2.0
    shots["pill-recording"] = _grab(overlay)

    # processing — the "thinking" dots mid-pulse
    to_state("processing")
    overlay._phase = 1.2
    shots["pill-processing"] = _grab(overlay)

    for name, pill in shots.items():
        path = OUT_DIR / f"{name}.png"
        _tile(pill).save(str(path), "PNG")
        print(f"wrote {path.relative_to(OUT_DIR.parents[1])}"
              f"  ({TILE_W}x{TILE_H} @{SCALE}x)")


if __name__ == "__main__":
    main()
