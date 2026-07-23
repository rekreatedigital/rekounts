> **Historical document** — an original design/plan kept for the record. It no longer matches the shipped app (see [docs/archive/README.md](../../README.md) for what changed). Do not use it as documentation.

# Shareable Milestone Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make TalkativeAI shareable via GitHub: mic-by-name portability, auto-restart on Save, a Test-mic button, a live overlay preview, and an Auto/English/Tagalog language picker, plus `setup.bat` and a friend-facing README.

**Architecture:** Keep new logic in small pure functions (device resolution, level classification, language mapping) that are unit-tested without hardware, then wire them into the existing recorder, settings window, controller, overlay, and entry point. faster-whisper already supports Tagalog; the language picker only exposes it.

**Tech Stack:** Python 3.11+, faster-whisper, sounddevice, PySide6, pytest (existing stack).

## Environment note

This machine's venv interpreter is `.venv\Scripts\python3.exe` (not `python.exe`).
Run tests with: `.venv\Scripts\python3.exe -m pytest`.

## File Structure

```
talkativeai/
  device_utils.py     # NEW: pure mic name<->device resolution + level classification
  languages.py        # NEW: pure language label<->code mapping
  audio_recorder.py   # MODIFY: resolve device by name, expose resolved name/notice
  controller.py       # MODIFY: expose partial-audio access for live preview
  __main__.py         # MODIFY: wire language, live-preview thread, restart-on-save
  ui/
    settings_window.py  # MODIFY: mic-by-name, Test button, language dropdown, restart
    overlay.py          # MODIFY: settable preview text
tests/
  test_device_utils.py  # NEW
  test_languages.py     # NEW
setup.bat             # NEW
README.md             # MODIFY: friend quickstart + troubleshooting
```

---

## Task 1: languages.py (pure label<->code mapping)

**Files:**
- Create: `talkativeai/languages.py`
- Test: `tests/test_languages.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_languages.py
from talkativeai.languages import LANGUAGES, label_for_code, code_for_label, labels


def test_labels_list_order():
    assert labels() == ["Auto-detect", "English", "Tagalog"]


def test_code_for_label():
    assert code_for_label("Auto-detect") == "auto"
    assert code_for_label("English") == "en"
    assert code_for_label("Tagalog") == "tl"


def test_label_for_code():
    assert label_for_code("auto") == "Auto-detect"
    assert label_for_code("en") == "English"
    assert label_for_code("tl") == "Tagalog"


def test_unknown_code_falls_back_to_first_label():
    assert label_for_code("zz") == "Auto-detect"


def test_languages_mapping_shape():
    assert LANGUAGES == [("Auto-detect", "auto"), ("English", "en"), ("Tagalog", "tl")]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv\Scripts\python3.exe -m pytest tests/test_languages.py -v`
Expected: FAIL — `ModuleNotFoundError: talkativeai.languages`.

- [ ] **Step 3: Implement languages.py**

```python
# talkativeai/languages.py

# Order matters: first entry is the default fallback.
LANGUAGES = [
    ("Auto-detect", "auto"),
    ("English", "en"),
    ("Tagalog", "tl"),
]


def labels() -> list[str]:
    return [label for label, _ in LANGUAGES]


def code_for_label(label: str) -> str:
    for l, code in LANGUAGES:
        if l == label:
            return code
    return LANGUAGES[0][1]


def label_for_code(code: str) -> str:
    for label, c in LANGUAGES:
        if c == code:
            return label
    return LANGUAGES[0][0]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv\Scripts\python3.exe -m pytest tests/test_languages.py -v`
Expected: PASS (5 passed).

- [ ] **Step 5: Commit**

```bash
git add talkativeai/languages.py tests/test_languages.py
git commit -m "feat: language label/code mapping (Auto/English/Tagalog)"
```

---

## Task 2: device_utils.py (pure device resolution + level classification)

**Files:**
- Create: `talkativeai/device_utils.py`
- Test: `tests/test_device_utils.py`

Note: functions take an injected `devices` list (list of dicts like sounddevice's
`query_devices()` output) so they are testable without audio hardware.

- [ ] **Step 1: Write failing tests**

```python
# tests/test_device_utils.py
from talkativeai.device_utils import resolve_input_device, classify_level

DEVICES = [
    {"name": "System Thing", "max_input_channels": 0},
    {"name": "Microphone (ME6S)", "max_input_channels": 2},
    {"name": "EMEET SmartCam", "max_input_channels": 1},
    {"name": "EMEET SmartCam", "max_input_channels": 1},  # duplicate name, 2 host APIs
]


def test_none_returns_none_for_system_default():
    assert resolve_input_device(None, DEVICES) is None


def test_exact_name_resolves_to_index():
    assert resolve_input_device("Microphone (ME6S)", DEVICES) == 1


def test_duplicate_name_returns_first_input_capable_index():
    assert resolve_input_device("EMEET SmartCam", DEVICES) == 2


def test_missing_name_returns_none_default():
    assert resolve_input_device("Nonexistent Mic", DEVICES) is None


def test_name_matching_output_only_device_is_skipped():
    # "System Thing" has 0 input channels -> not selectable -> default
    assert resolve_input_device("System Thing", DEVICES) is None


def test_classify_level_loud_quiet_silent():
    assert classify_level(0.5) == "loud"
    assert classify_level(0.03) == "quiet"
    assert classify_level(0.0005) == "silent"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv\Scripts\python3.exe -m pytest tests/test_device_utils.py -v`
Expected: FAIL — `ModuleNotFoundError: talkativeai.device_utils`.

- [ ] **Step 3: Implement device_utils.py**

```python
# talkativeai/device_utils.py

# RMS thresholds for the Test-mic button.
_SILENT_BELOW = 0.005
_QUIET_BELOW = 0.15


def resolve_input_device(name, devices):
    """Return the index of the first input-capable device whose name matches
    exactly, or None (meaning: use the system default) when name is None or
    no input-capable match exists.

    `devices` is a list of dicts shaped like sounddevice.query_devices().
    """
    if name is None:
        return None
    for i, d in enumerate(devices):
        if d.get("name") == name and d.get("max_input_channels", 0) > 0:
            return i
    return None


def classify_level(rms: float) -> str:
    """Bucket a post-gain RMS level for user-facing feedback."""
    if rms < _SILENT_BELOW:
        return "silent"
    if rms < _QUIET_BELOW:
        return "quiet"
    return "loud"
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv\Scripts\python3.exe -m pytest tests/test_device_utils.py -v`
Expected: PASS (6 passed).

- [ ] **Step 5: Commit**

```bash
git add talkativeai/device_utils.py tests/test_device_utils.py
git commit -m "feat: pure device resolution + mic level classification"
```

---

## Task 3: AudioRecorder resolves device by name

**Files:**
- Modify: `talkativeai/audio_recorder.py`

The recorder currently passes `self.device` (an index or None) straight to sounddevice.
Change it to accept a device **name** (or None), resolve it via `resolve_input_device`,
and expose whether the saved mic was found (so the caller can notify on fallback).

- [ ] **Step 1: Update AudioRecorder**

Replace the file with:
```python
# talkativeai/audio_recorder.py
import numpy as np
import sounddevice as sd

from talkativeai.device_utils import resolve_input_device

SAMPLE_RATE = 16000  # faster-whisper expects 16 kHz mono


class AudioRecorder:
    def __init__(self, device=None, sample_rate=SAMPLE_RATE):
        # `device` is a device NAME (str) or None (system default).
        self.device_name = device
        self.sample_rate = sample_rate
        self._frames = []
        self._stream = None
        # resolve name -> index once; None means system default
        self._device_index = resolve_input_device(device, sd.query_devices())
        # True if a name was requested but not found (caller may notify)
        self.fell_back_to_default = device is not None and self._device_index is None

    def start(self) -> None:
        self._frames = []

        def callback(indata, frames, time, status):
            self._frames.append(indata.copy())

        self._stream = sd.InputStream(
            samplerate=self.sample_rate, channels=1, dtype="float32",
            device=self._device_index, callback=callback,
        )
        self._stream.start()

    def stop(self) -> np.ndarray:
        if self._stream is None:
            return np.zeros(0, dtype="float32")
        self._stream.stop()
        self._stream.close()
        self._stream = None
        if not self._frames:
            return np.zeros(0, dtype="float32")
        return np.concatenate(self._frames, axis=0).flatten()

    def snapshot(self) -> np.ndarray:
        """Audio captured so far WITHOUT stopping the stream (for live preview)."""
        if not self._frames:
            return np.zeros(0, dtype="float32")
        return np.concatenate(list(self._frames), axis=0).flatten()

    def duration(self, audio: np.ndarray) -> float:
        return len(audio) / self.sample_rate
```

- [ ] **Step 2: Verify import + resolution works (no mic needed)**

Run:
```bash
.venv\Scripts\python3.exe -c "from talkativeai.audio_recorder import AudioRecorder; r=AudioRecorder(device='definitely-not-a-mic'); print('fell_back', r.fell_back_to_default, 'idx', r._device_index)"
```
Expected: prints `fell_back True idx None`.

- [ ] **Step 3: Run full suite (nothing regressed)**

Run: `.venv\Scripts\python3.exe -m pytest -q`
Expected: PASS (all existing tests + tasks 1-2).

- [ ] **Step 4: Commit**

```bash
git add talkativeai/audio_recorder.py
git commit -m "feat: resolve microphone by name with default fallback; add snapshot()"
```

---

## Task 4: Controller exposes recorder for live preview + fallback notice

**Files:**
- Modify: `talkativeai/controller.py`

The controller already holds `self.recorder`. Add a helper the preview thread can call
to get the in-progress audio, and notify if the recorder fell back to default on start.

- [ ] **Step 1: Add fallback notice in start_recording**

In `talkativeai/controller.py`, find `start_recording` (currently):
```python
    def start_recording(self):
        if not self.sm.to_recording():
            return
        try:
            self.recorder.start()
            self.on_overlay_show()
        except Exception as e:
            self.on_error(f"Microphone error: {e}")
            self.sm.to_idle()
```
Replace with:
```python
    def start_recording(self):
        if not self.sm.to_recording():
            return
        try:
            if getattr(self.recorder, "fell_back_to_default", False):
                self.on_notice("Saved microphone not found — using system default.")
            self.recorder.start()
            self.on_overlay_show()
        except Exception as e:
            self.on_error(f"Microphone error: {e}")
            self.sm.to_idle()
```

- [ ] **Step 2: Add is_recording helper for the preview thread**

At the end of the `AppController` class (after `_process`), add:
```python
    def is_recording(self) -> bool:
        return self.sm.state.name == "RECORDING"

    def preview_snapshot(self):
        """Audio captured so far, or None if not recording / unsupported."""
        if not self.is_recording():
            return None
        snap = getattr(self.recorder, "snapshot", None)
        return snap() if callable(snap) else None
```

- [ ] **Step 3: Run full suite**

Run: `.venv\Scripts\python3.exe -m pytest -q`
Expected: PASS (existing controller tests still green; fallback notice only fires when
`fell_back_to_default` is truthy, which the fakes don't set).

- [ ] **Step 4: Commit**

```bash
git add talkativeai/controller.py
git commit -m "feat: controller notifies on mic fallback; exposes preview snapshot"
```

---

## Task 5: Overlay shows live preview text

**Files:**
- Modify: `talkativeai/ui/overlay.py`

Add a slot to set the overlay's text, and reset to "● Listening…" when shown.

- [ ] **Step 1: Update Overlay**

Replace `talkativeai/ui/overlay.py` with:
```python
# talkativeai/ui/overlay.py
from PySide6 import QtCore, QtGui, QtWidgets


class Overlay(QtWidgets.QWidget):
    def __init__(self):
        super().__init__(
            None,
            QtCore.Qt.FramelessWindowHint | QtCore.Qt.WindowStaysOnTopHint
            | QtCore.Qt.Tool)
        self.setAttribute(QtCore.Qt.WA_TranslucentBackground)
        self.setAttribute(QtCore.Qt.WA_ShowWithoutActivating)
        self._label = QtWidgets.QLabel("● Listening…", self)
        self._label.setWordWrap(True)
        self._label.setMaximumWidth(360)
        self._label.setStyleSheet(
            "background: rgba(20,20,20,220); color: #ff5c5c;"
            "padding: 8px 14px; border-radius: 10px; font-size: 14px;")
        self._label.adjustSize()
        self.resize(self._label.size())

    @QtCore.Slot()
    def show_near_cursor(self):
        self.set_text("● Listening…")
        pos = QtGui.QCursor.pos()
        self.move(pos.x() + 16, pos.y() + 16)
        self.show()

    @QtCore.Slot(str)
    def set_text(self, text):
        self._label.setText(text or "● Listening…")
        self._label.adjustSize()
        self.resize(self._label.size())

    @QtCore.Slot()
    def hide_overlay(self):
        self.hide()
```

- [ ] **Step 2: Verify constructs offscreen**

Run:
```bash
set QT_QPA_PLATFORM=offscreen
.venv\Scripts\python3.exe -c "import sys; from PySide6 import QtWidgets; from talkativeai.ui.overlay import Overlay; app=QtWidgets.QApplication(sys.argv); o=Overlay(); o.set_text('hello world preview'); print('overlay ok')"
```
Expected: prints `overlay ok`.

- [ ] **Step 3: Commit**

```bash
git add talkativeai/ui/overlay.py
git commit -m "feat: overlay supports live preview text"
```

---

## Task 6: Settings window — mic by name, Test button, language dropdown, restart on save

**Files:**
- Modify: `talkativeai/ui/settings_window.py`

- [ ] **Step 1: Rewrite settings_window.py**

Replace the file with:
```python
# talkativeai/ui/settings_window.py
import threading

import numpy as np
import sounddevice as sd
from PySide6 import QtCore, QtWidgets

from talkativeai.audio_utils import normalize_gain
from talkativeai.device_utils import classify_level, resolve_input_device
from talkativeai.languages import code_for_label, label_for_code, labels

_LEVEL_MESSAGES = {
    "loud": "✓ Heard you clearly",
    "quiet": "⚠ Very quiet — boosted, may still work",
    "silent": "✗ Silent — wrong mic or muted",
}


class SettingsWindow(QtWidgets.QWidget):
    _test_result = QtCore.Signal(str)

    def __init__(self, config, on_saved=None, on_restart=None):
        super().__init__()
        self.config = config
        self.on_saved = on_saved or (lambda: None)
        self.on_restart = on_restart or (lambda: None)
        self.setWindowTitle("TalkativeAI Settings")
        form = QtWidgets.QFormLayout(self)

        self.ptt = QtWidgets.QLineEdit(config.get("ptt_hotkey"))
        self.toggle = QtWidgets.QLineEdit(config.get("toggle_hotkey"))

        self.model = QtWidgets.QComboBox()
        self.model.addItems(["small", "medium"])
        self.model.setCurrentText(config.get("model"))

        # Microphone dropdown stores the device NAME (or None for system default).
        self.mic = QtWidgets.QComboBox()
        self.mic.addItem("System default", None)
        for d in sd.query_devices():
            if d["max_input_channels"] > 0:
                self.mic.addItem(d["name"], d["name"])
        saved_mic = config.get("microphone")
        idx = self.mic.findData(saved_mic)
        if idx >= 0:
            self.mic.setCurrentIndex(idx)

        self.test_btn = QtWidgets.QPushButton("Test")
        self.test_btn.clicked.connect(self._test_mic)
        self.test_result = QtWidgets.QLabel("")
        self.test_result.setStyleSheet("font-size: 11px;")
        mic_row = QtWidgets.QHBoxLayout()
        mic_row.addWidget(self.mic, 1)
        mic_row.addWidget(self.test_btn)
        self._test_result.connect(self._show_test_result)

        # Language dropdown shows labels, stores codes.
        self.language = QtWidgets.QComboBox()
        self.language.addItems(labels())
        self.language.setCurrentText(label_for_code(config.get("language")))

        self.strip_fillers = QtWidgets.QCheckBox()
        self.strip_fillers.setChecked(config.get("strip_fillers"))
        self.auto_cap = QtWidgets.QCheckBox()
        self.auto_cap.setChecked(config.get("auto_capitalize"))
        self.fix_punct = QtWidgets.QCheckBox()
        self.fix_punct.setChecked(config.get("fix_punctuation_spacing"))

        self.insertion = QtWidgets.QComboBox()
        self.insertion.addItems(["paste", "keystroke"])
        self.insertion.setCurrentText(config.get("insertion_mode"))

        form.addRow("Push-to-talk hotkey", self.ptt)
        form.addRow("Toggle hotkey", self.toggle)
        form.addRow("Microphone", mic_row)
        form.addRow("", self.test_result)
        form.addRow("Model", self.model)
        form.addRow("Language", self.language)
        form.addRow("Strip fillers", self.strip_fillers)
        form.addRow("Auto-capitalize", self.auto_cap)
        form.addRow("Fix punctuation spacing", self.fix_punct)
        form.addRow("Insertion mode", self.insertion)

        lang_note = QtWidgets.QLabel(
            "Tagalog works but is less accurate than English on the 'small' model; "
            "try 'medium' for better results.")
        lang_note.setWordWrap(True)
        lang_note.setStyleSheet("color: gray; font-size: 11px;")
        form.addRow(lang_note)

        save = QtWidgets.QPushButton("Save (restarts app)")
        save.clicked.connect(self._save)
        form.addRow(save)

    # --- mic test (records ~2s from the currently selected dropdown mic) ---
    def _test_mic(self):
        self.test_btn.setEnabled(False)
        self.test_result.setText("Listening…")
        name = self.mic.currentData()
        threading.Thread(target=self._run_test, args=(name,), daemon=True).start()

    def _run_test(self, name):
        try:
            index = resolve_input_device(name, sd.query_devices())
            rec = sd.rec(int(2 * 16000), samplerate=16000, channels=1,
                         dtype="float32", device=index)
            sd.wait()
            audio = normalize_gain(rec.flatten())
            rms = float(np.sqrt(np.mean(audio ** 2))) if len(audio) else 0.0
            self._test_result.emit(_LEVEL_MESSAGES[classify_level(rms)])
        except Exception as e:
            self._test_result.emit(f"✗ Mic error: {e}")

    @QtCore.Slot(str)
    def _show_test_result(self, msg):
        self.test_result.setText(msg)
        self.test_btn.setEnabled(True)

    def _save(self):
        self.config.set("ptt_hotkey", self.ptt.text().strip())
        self.config.set("toggle_hotkey", self.toggle.text().strip())
        self.config.set("microphone", self.mic.currentData())
        self.config.set("model", self.model.currentText())
        self.config.set("language", code_for_label(self.language.currentText()))
        self.config.set("strip_fillers", self.strip_fillers.isChecked())
        self.config.set("auto_capitalize", self.auto_cap.isChecked())
        self.config.set("fix_punctuation_spacing", self.fix_punct.isChecked())
        self.config.set("insertion_mode", self.insertion.currentText())
        self.config.save()
        self.on_saved()
        self.close()
        self.on_restart()
```

- [ ] **Step 2: Verify constructs offscreen (with a temp config)**

Run:
```bash
set QT_QPA_PLATFORM=offscreen
.venv\Scripts\python3.exe -c "import sys; from PySide6 import QtWidgets; from talkativeai.config import Config; from talkativeai.ui.settings_window import SettingsWindow; app=QtWidgets.QApplication(sys.argv); w=SettingsWindow(Config(path='__s.json')); print('lang', w.language.currentText(), 'mic items', w.mic.count())"
```
Expected: prints e.g. `lang English mic items <N>`. Then delete `__s.json`.

- [ ] **Step 3: Commit**

```bash
git add talkativeai/ui/settings_window.py
git commit -m "feat: settings mic-by-name, Test button, language picker, restart-on-save"
```

---

## Task 7: Entry point — restart-on-save + live preview thread

**Files:**
- Modify: `talkativeai/__main__.py`

- [ ] **Step 1: Add a restart helper and preview loop, wire into main()**

In `talkativeai/__main__.py`, after the existing imports at top, add:
```python
import os
```

Find the block that builds `settings` and `tray` (currently):
```python
    settings = SettingsWindow(cfg)
    tray = TrayApp(app, on_open_settings=settings.show, on_quit=app.quit)
    bridge.notify.connect(tray.notify)
```
Replace with:
```python
    def restart_app():
        bridge.notify.emit("Restarting to apply settings…")
        try:
            import subprocess
            subprocess.Popen([sys.executable, "-m", "talkativeai"],
                             close_fds=True)
        except Exception as e:
            log.error("restart failed: %s", e)
            bridge.notify.emit("Restart failed — please relaunch manually.")
            return
        app.quit()

    settings = SettingsWindow(cfg, on_restart=restart_app)
    tray = TrayApp(app, on_open_settings=settings.show, on_quit=app.quit)
    bridge.notify.connect(tray.notify)

    # --- live overlay preview: periodically transcribe audio-so-far ---
    preview_signal = bridge  # reuse bridge for thread-safe UI updates

    def preview_loop():
        import time
        last = ""
        while True:
            time.sleep(1.5)
            try:
                snap = controller.preview_snapshot()
                if snap is None or len(snap) < int(0.4 * 16000):
                    continue
                from talkativeai.audio_utils import normalize_gain
                seg, _ = transcriber.model.transcribe(
                    normalize_gain(snap),
                    language=transcriber.language, vad_filter=False, beam_size=1)
                text = " ".join(s.text.strip() for s in seg).strip()
                if text and text != last:
                    last = text
                    bridge.preview.emit(text)
            except Exception:
                pass  # preview is best-effort

    threading.Thread(target=preview_loop, daemon=True).start()
```

- [ ] **Step 2: Add the preview signal to Bridge and connect it**

Find the `Bridge` class inside `main()`:
```python
    class Bridge(QtCore.QObject):
        show_overlay = QtCore.Signal()
        hide_overlay = QtCore.Signal()
        notify = QtCore.Signal(str)
```
Add a `preview` signal:
```python
    class Bridge(QtCore.QObject):
        show_overlay = QtCore.Signal()
        hide_overlay = QtCore.Signal()
        notify = QtCore.Signal(str)
        preview = QtCore.Signal(str)
```
Then, where overlay signals are connected (after `bridge.hide_overlay.connect(...)`),
add:
```python
    bridge.preview.connect(overlay.set_text)
```

- [ ] **Step 3: Launch and verify it starts and stays up**

Run (PowerShell): launch detached, wait, confirm running, then stop.
```bash
.venv\Scripts\python3.exe -m talkativeai
```
Expected: tray icon appears, app runs. Manually: hold hotkey and speak — the overlay
text should update with a running transcript; on release the final text is typed.
(This is a manual smoke step; see Task 9.)

- [ ] **Step 4: Run full suite (no regressions)**

Run: `.venv\Scripts\python3.exe -m pytest -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add talkativeai/__main__.py
git commit -m "feat: restart-on-save and live overlay preview thread"
```

---

## Task 8: setup.bat + friend-facing README

**Files:**
- Create: `setup.bat`
- Modify: `README.md`

- [ ] **Step 1: Create setup.bat**

```bat
@echo off
cd /d "%~dp0"
echo Creating virtual environment...
where python >nul 2>nul && (set PY=python) || (set PY=python3)
%PY% -m venv .venv
echo Installing dependencies (this downloads ~1GB, please wait)...
.venv\Scripts\python -m pip install --upgrade pip
.venv\Scripts\python -m pip install -r requirements.txt
echo.
echo Done! Run the app with:  run.bat
pause
```

- [ ] **Step 2: Prepend a "For my friends" quickstart to README.md**

Insert this section directly under the first paragraph of `README.md`:
```markdown
## Quickstart (for friends)

1. Install **Python 3.11+** from https://www.python.org/downloads/ (check
   "Add Python to PATH" during install).
2. Download this repo (green **Code** button → Download ZIP, or `git clone`).
3. Double-click **`setup.bat`** and wait (first time downloads ~1GB of libraries).
4. Double-click **`run.bat`**. The first launch downloads the speech model once
   (~500 MB), then it works offline.
5. Right-click the **red tray icon** → **Settings**:
   - Pick your **Microphone** and click **Test** (you want "✓ Heard you clearly").
   - Set your **Push-to-talk** and **Toggle** hotkeys if you like.
   - Choose your **Language** (Auto / English / Tagalog).
   - Click **Save** — the app restarts to apply your settings.
6. **Hold your push-to-talk hotkey, talk, release** → your words are typed into
   whatever app is focused.

### Troubleshooting
- **Nothing gets typed:** open Settings → **Test** your mic. If it says "Silent",
  pick a different microphone or unmute it in Windows.
- **Hotkey does nothing / conflicts with another app:** open Settings and change it,
  then Save.
- **Tagalog accuracy is rough:** switch **Model** to `medium` in Settings (slower but
  more accurate), and speak clearly.
```

- [ ] **Step 3: Verify setup.bat references are consistent**

Confirm `requirements.txt` and `run.bat` exist (they do). No command to run here beyond
a visual check.

- [ ] **Step 4: Commit**

```bash
git add setup.bat README.md
git commit -m "docs: setup.bat and friend-facing quickstart + troubleshooting"
```

---

## Task 9: Manual smoke test pass

**Files:**
- Modify: `docs/manual-smoke-test.md`

- [ ] **Step 1: Append shareable-milestone checks**

Add to `docs/manual-smoke-test.md`:
```markdown
## Shareable milestone
- [ ] Settings → Microphone → Test: good mic shows "✓", quiet mic "⚠", muted "✗".
- [ ] Change Microphone, Save → app auto-restarts → new mic is used.
- [ ] Change push-to-talk hotkey, Save → auto-restart → new hotkey works.
- [ ] While holding the hotkey and speaking, the overlay shows a running transcript.
- [ ] On release, the final cleaned text is typed (preview text is discarded).
- [ ] Set Language = Tagalog, speak Tagalog → Tagalog text appears.
- [ ] Set a nonexistent mic name in config.json, launch → "Saved microphone not found"
      notice, app uses default, no crash.
```

- [ ] **Step 2: Run the checklist manually.** Record any failures as fixes before done.

- [ ] **Step 3: Commit**

```bash
git add docs/manual-smoke-test.md
git commit -m "docs: smoke test for shareable milestone"
```

---

## Self-Review Notes

- **Spec coverage:** mic-by-name (T2, T3), auto-restart on Save (T6, T7), Test-mic button
  (T2 classify, T6 UI), live overlay preview (T4 snapshot, T5 overlay, T7 thread),
  language picker (T1, T6), setup.bat + README (T8), smoke tests (T9). All five changes
  covered.
- **Placeholder scan:** none — all code and commands are concrete.
- **Type consistency:** `resolve_input_device(name, devices)` and `classify_level(rms)`
  signatures match across T2 tests, T3 recorder, and T6 settings. `code_for_label` /
  `label_for_code` / `labels` match across T1 and T6. `snapshot()` on recorder (T3) is
  consumed by `preview_snapshot()` (T4) and the preview loop (T7). `Overlay.set_text`
  (T5) is connected to `bridge.preview` (T7).
- **Fallback behavior:** recorder sets `fell_back_to_default`; controller fires
  `on_notice` (T4). Config `microphone` is now a name string; existing default is `null`
  (system default) — friend-safe.
- **Known caveat carried through:** Tagalog accuracy note in both Settings (T6) and
  README (T8), consistent with the spec.
```