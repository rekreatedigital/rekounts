"""Manual visual demo for the monochrome dictation pill.

Cycles idle -> recording -> processing -> idle on a loop and feeds the waveform
a fake audio level so the overlay can be reviewed WITHOUT dictating (no model,
no microphone). Hover the pill to see the hint text and button highlights.

Run from the repo root:

    .venv\\Scripts\\python.exe tools\\overlay_demo.py

Ctrl+C in the console (or close via the printed instructions) to quit.
"""
import math
import sys

from PySide6 import QtCore, QtWidgets

from rekounts.ui.overlay import Overlay


def main():
    app = QtWidgets.QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)

    overlay = Overlay()
    overlay.set_hotkey_label("F8")

    # Fake, breathing audio level so the recording waveform has something to show.
    phase = {"t": 0.0}

    def fake_level():
        phase["t"] += 0.15
        return 0.12 + 0.10 * (0.5 + 0.5 * math.sin(phase["t"])) \
            + 0.06 * (0.5 + 0.5 * math.sin(phase["t"] * 2.7))

    overlay.level_provider = fake_level
    overlay.on_cancel = lambda: print("[demo] cancel clicked")
    overlay.on_finish = lambda: print("[demo] finish clicked")

    # State machine: idle (3s) -> recording (5s) -> processing (2s) -> repeat.
    sequence = [("idle", 3000), ("recording", 5000), ("processing", 2000)]
    step = {"i": 0}

    def advance():
        state, _ = sequence[step["i"] % len(sequence)]
        print(f"[demo] state -> {state}")
        overlay.set_state(state)
        _, hold = sequence[step["i"] % len(sequence)]
        step["i"] += 1
        QtCore.QTimer.singleShot(hold, advance)

    print("Rekounts overlay demo running. Hover the pill; click x / check while")
    print("recording. It cycles idle -> recording -> processing automatically.")
    print("Move the mouse to another monitor to see the pill follow. Ctrl+C to quit.")
    advance()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
