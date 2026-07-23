> **Historical document** — an original design/plan kept for the record. It no longer matches the shipped app (see [docs/archive/README.md](../../README.md) for what changed). Do not use it as documentation.

# Overlay Upgrade Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans.

**Goal:** Overlay shows live mic level bars and sits fixed at bottom-center of the primary screen.

**Architecture:** Add `rms_level()` (pure, tested) + `AudioRecorder.current_level()`. Overlay polls a `level_provider` callback via a QTimer, keeps a rolling history, and paints bars in `paintEvent`. Entry point wires the provider and positions the overlay bottom-center.

**Tech Stack:** existing (PySide6, numpy, pytest). Run tests with `.venv\Scripts\python3.exe -m pytest`.

---

## Task 1: rms_level helper + recorder.current_level (TDD)

**Files:**
- Modify: `talkativeai/audio_utils.py` (add `rms_level`)
- Modify: `talkativeai/audio_recorder.py` (add `current_level`)
- Test: `tests/test_audio_utils.py` (add cases)

- [ ] **Step 1: Add failing tests to tests/test_audio_utils.py**

```python
def test_rms_level_silence_is_zero():
    from talkativeai.audio_utils import rms_level
    import numpy as np
    assert rms_level(np.zeros(1000, dtype="float32")) == 0.0

def test_rms_level_louder_is_higher():
    from talkativeai.audio_utils import rms_level
    import numpy as np
    quiet = rms_level(np.full(1000, 0.05, dtype="float32"))
    loud = rms_level(np.full(1000, 0.5, dtype="float32"))
    assert loud > quiet > 0.0

def test_rms_level_empty_is_zero():
    from talkativeai.audio_utils import rms_level
    import numpy as np
    assert rms_level(np.zeros(0, dtype="float32")) == 0.0
```

- [ ] **Step 2: Run — expect fail**

Run: `.venv\Scripts\python3.exe -m pytest tests/test_audio_utils.py -q`
Expected: FAIL — `ImportError: cannot import name 'rms_level'`.

- [ ] **Step 3: Add rms_level to audio_utils.py**

```python
def rms_level(audio) -> float:
    """Root-mean-square amplitude of an audio buffer (0.0 for empty)."""
    if audio is None or len(audio) == 0:
        return 0.0
    import numpy as np
    return float(np.sqrt(np.mean(np.square(audio, dtype="float64"))))
```

- [ ] **Step 4: Add current_level to AudioRecorder**

In `talkativeai/audio_recorder.py`, add this method (after `snapshot`):
```python
    def current_level(self, window_frames: int = 8) -> float:
        """RMS amplitude of the most recent captured chunks (0.0 if none).
        Cheap; used to drive the live level meter."""
        from talkativeai.audio_utils import rms_level
        if not self._frames:
            return 0.0
        recent = self._frames[-window_frames:]
        import numpy as np
        return rms_level(np.concatenate(recent, axis=0).flatten())
```

- [ ] **Step 5: Run — expect pass**

Run: `.venv\Scripts\python3.exe -m pytest tests/test_audio_utils.py -q`
Expected: PASS.

- [ ] **Step 6: Full suite + commit**

Run: `.venv\Scripts\python3.exe -m pytest -q` (expect all pass)
```bash
git add talkativeai/audio_utils.py talkativeai/audio_recorder.py tests/test_audio_utils.py
git commit -m "feat: rms_level helper and recorder.current_level for meter"
```

---

## Task 2: Overlay — level bars + fixed bottom-center

**Files:**
- Modify: `talkativeai/ui/overlay.py`

- [ ] **Step 1: Rewrite overlay.py**

```python
# talkativeai/ui/overlay.py
from collections import deque

from PySide6 import QtCore, QtGui, QtWidgets

_BARS = 12
_BAR_W = 4
_BAR_GAP = 3
_METER_H = 28
_PANEL_W = 360


class Overlay(QtWidgets.QWidget):
    def __init__(self):
        super().__init__(
            None,
            QtCore.Qt.FramelessWindowHint | QtCore.Qt.WindowStaysOnTopHint
            | QtCore.Qt.Tool)
        self.setAttribute(QtCore.Qt.WA_TranslucentBackground)
        self.setAttribute(QtCore.Qt.WA_ShowWithoutActivating)

        self.level_provider = None          # set by entry point: () -> float
        self._levels = deque([0.0] * _BARS, maxlen=_BARS)
        self._text = "● Listening…"

        self._label = QtWidgets.QLabel(self._text)
        self._label.setWordWrap(True)
        self._label.setStyleSheet("color: #ff5c5c; font-size: 14px;")

        # meter widget draws the bars
        self._meter = _Meter(self._levels)
        self._meter.setFixedHeight(_METER_H)

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(14, 8, 14, 8)
        layout.addWidget(self._meter)
        layout.addWidget(self._label)
        self.setFixedWidth(_PANEL_W)

        self._timer = QtCore.QTimer(self)
        self._timer.setInterval(40)         # ~25 fps
        self._timer.timeout.connect(self._tick)

    def paintEvent(self, event):
        p = QtGui.QPainter(self)
        p.setRenderHint(QtGui.QPainter.Antialiasing)
        p.setBrush(QtGui.QColor(20, 20, 20, 220))
        p.setPen(QtCore.Qt.NoPen)
        p.drawRoundedRect(self.rect(), 12, 12)
        super().paintEvent(event)

    @QtCore.Slot()
    def show_bottom_center(self):
        self.set_text("● Listening…")
        self._levels.extend([0.0] * _BARS)
        screen = QtWidgets.QApplication.primaryScreen()
        geo = screen.availableGeometry()
        self.adjustSize()
        x = geo.x() + (geo.width() - self.width()) // 2
        y = geo.y() + geo.height() - self.height() - 120
        self.move(x, y)
        self.show()
        self._timer.start()

    @QtCore.Slot(str)
    def set_text(self, text):
        self._text = text or "● Listening…"
        self._label.setText(self._text)
        self.adjustSize()

    @QtCore.Slot()
    def hide_overlay(self):
        self._timer.stop()
        self.hide()

    def _tick(self):
        level = 0.0
        if callable(self.level_provider):
            try:
                level = float(self.level_provider())
            except Exception:
                level = 0.0
        # scale RMS (typically 0..~0.3) to 0..1 with headroom, clamp
        norm = max(0.0, min(1.0, level * 4.0))
        self._levels.append(norm)
        self._meter.update()


class _Meter(QtWidgets.QWidget):
    def __init__(self, levels):
        super().__init__()
        self._levels = levels

    def paintEvent(self, event):
        p = QtGui.QPainter(self)
        p.setRenderHint(QtGui.QPainter.Antialiasing)
        p.setPen(QtCore.Qt.NoPen)
        p.setBrush(QtGui.QColor("#ff5c5c"))
        h = self.height()
        total = _BARS * _BAR_W + (_BARS - 1) * _BAR_GAP
        x = (self.width() - total) // 2
        for lvl in self._levels:
            bar_h = max(2, int(lvl * h))
            y = (h - bar_h) // 2
            p.drawRoundedRect(x, y, _BAR_W, bar_h, 2, 2)
            x += _BAR_W + _BAR_GAP
```

- [ ] **Step 2: Verify constructs offscreen**

Run:
```bash
set QT_QPA_PLATFORM=offscreen
.venv\Scripts\python3.exe -c "import sys; from PySide6 import QtWidgets; from talkativeai.ui.overlay import Overlay; app=QtWidgets.QApplication(sys.argv); o=Overlay(); o.level_provider=lambda: 0.2; o.show_bottom_center(); o._tick(); o.set_text('hello preview'); print('overlay ok', len(o._levels))"
```
Expected: prints `overlay ok 12`.

- [ ] **Step 3: Commit**

```bash
git add talkativeai/ui/overlay.py
git commit -m "feat: overlay live level bars + fixed bottom-center position"
```

---

## Task 3: Wire provider + new show method in entry point

**Files:**
- Modify: `talkativeai/__main__.py`

- [ ] **Step 1: Update overlay wiring**

In `talkativeai/__main__.py`, find:
```python
    bridge.show_overlay.connect(overlay.show_near_cursor)
    bridge.hide_overlay.connect(overlay.hide_overlay)
    bridge.preview.connect(overlay.set_text)
```
Replace with:
```python
    overlay.level_provider = recorder.current_level
    bridge.show_overlay.connect(overlay.show_bottom_center)
    bridge.hide_overlay.connect(overlay.hide_overlay)
    bridge.preview.connect(overlay.set_text)
```

- [ ] **Step 2: Launch and verify app stays up**

Run the app; expect it to start. Manual: hold hotkey → overlay appears bottom-center,
bars move while speaking, hides on release (smoke test).

- [ ] **Step 3: Full suite + commit**

Run: `.venv\Scripts\python3.exe -m pytest -q` (expect all pass)
```bash
git add talkativeai/__main__.py
git commit -m "feat: wire recorder level into overlay meter; show bottom-center"
```

---

## Self-Review Notes
- Spec coverage: level bars (T1 data, T2 render, T3 wiring), fixed bottom-center (T2
  show_bottom_center, T3 uses it). Covered.
- Types: `current_level()` (T1) feeds `overlay.level_provider` (T3); `rms_level` shared.
  `show_bottom_center` replaces `show_near_cursor` at the one call site (T3).
- No placeholders; all code concrete.
```