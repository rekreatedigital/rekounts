> **Historical document** — an original design/plan kept for the record. It no longer matches the shipped app (see [docs/archive/README.md](../../README.md) for what changed). Do not use it as documentation.

# TalkativeAI Dictation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a local, always-on Windows voice-dictation app: press a hotkey, speak, and cleaned-up text is pasted into the focused app — all offline.

**Architecture:** An event-driven state machine (Idle→Recording→Processing→Idle) wires together isolated single-purpose components. Pure-logic units (Config, TextCleaner, StateMachine) are built first with TDD; hardware/UI units (audio, hotkeys, transcriber, inserter, tray, overlay, settings) are built behind small interfaces so the controller can be tested with mocks. faster-whisper runs on the CUDA GPU and loads once at startup.

**Tech Stack:** Python 3.11+, faster-whisper (CTranslate2/CUDA), sounddevice, pynput, pyperclip, pywin32, PySide6, pytest.

---

## File Structure

```
talkativeai/
  __init__.py
  __main__.py            # entry point: build Config, wire AppController, start Qt loop
  config.py              # Config: load/save/defaults/corruption recovery
  text_cleaner.py        # TextCleaner: rule-based cleanup
  state_machine.py       # DictationState enum + StateMachine with guarded transitions
  audio_recorder.py      # AudioRecorder: mic capture to in-memory buffer
  transcriber.py         # Transcriber: faster-whisper wrapper
  text_inserter.py       # TextInserter: clipboard-paste + restore, keystroke fallback
  hotkey_manager.py      # HotkeyManager: global PTT (hold) + toggle (tap) events
  controller.py          # AppController: orchestrates the pipeline
  ui/
    __init__.py
    overlay.py           # Overlay: recording indicator window
    tray.py              # TrayApp: system tray icon + menu
    settings_window.py   # SettingsWindow: edit config via Qt form
tests/
  test_config.py
  test_text_cleaner.py
  test_state_machine.py
  test_controller.py
pyproject.toml
requirements.txt
run.bat                  # launcher for daily use
docs/manual-smoke-test.md
```

Interfaces the controller depends on (so it can be mocked in tests):
- `AudioRecorder.start() -> None`, `AudioRecorder.stop() -> np.ndarray` (float32 mono @ 16kHz), `AudioRecorder.duration(buf) -> float`
- `Transcriber.transcribe(audio: np.ndarray) -> str`
- `TextCleaner.clean(text: str) -> str`
- `TextInserter.insert(text: str) -> None`

---

## Task 1: Project scaffold

**Files:**
- Create: `talkativeai/__init__.py`, `talkativeai/ui/__init__.py`, `tests/__init__.py`
- Create: `requirements.txt`, `pyproject.toml`, `.gitignore`

- [ ] **Step 1: Create package dirs and empty init files**

Create `talkativeai/__init__.py` with:
```python
__version__ = "0.1.0"
```
Create empty `talkativeai/ui/__init__.py` and `tests/__init__.py`.

- [ ] **Step 2: Create requirements.txt**

```
faster-whisper==1.0.3
sounddevice==0.4.7
numpy==1.26.4
pynput==1.7.7
pyperclip==1.9.0
pywin32==306
PySide6==6.7.2
pytest==8.2.2
```

- [ ] **Step 3: Create pyproject.toml**

```toml
[build-system]
requires = ["setuptools>=68"]
build-backend = "setuptools.build_meta"

[project]
name = "talkativeai"
version = "0.1.0"
requires-python = ">=3.11"

[tool.pytest.ini_options]
testpaths = ["tests"]
```

- [ ] **Step 4: Create .gitignore**

```
__pycache__/
*.pyc
.venv/
venv/
*.egg-info/
.pytest_cache/
```

- [ ] **Step 5: Create venv and install pytest only (fast, to verify scaffold)**

Run: `python -m venv .venv && .venv/Scripts/python -m pip install -q pytest && .venv/Scripts/python -m pytest -q`
Expected: `no tests ran` (exit code 5 is fine — scaffold works, no tests yet).

- [ ] **Step 6: Commit**

```bash
git add -A
git commit -m "chore: project scaffold and dependencies"
```

---

## Task 2: Config (load/save/defaults/corruption recovery)

**Files:**
- Create: `talkativeai/config.py`
- Test: `tests/test_config.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_config.py
import json
from talkativeai.config import Config, DEFAULTS

def test_defaults_when_file_missing(tmp_path):
    cfg = Config(path=tmp_path / "config.json")
    assert cfg.data == DEFAULTS
    assert cfg.get("model") == "small"

def test_save_then_load_roundtrip(tmp_path):
    p = tmp_path / "config.json"
    cfg = Config(path=p)
    cfg.set("model", "medium")
    cfg.save()
    reloaded = Config(path=p)
    assert reloaded.get("model") == "medium"

def test_corrupt_file_recovers_to_defaults(tmp_path):
    p = tmp_path / "config.json"
    p.write_text("{not valid json", encoding="utf-8")
    cfg = Config(path=p)
    assert cfg.get("model") == "small"
    # corrupt file was rewritten as valid defaults
    assert json.loads(p.read_text(encoding="utf-8"))["model"] == "small"

def test_unknown_key_backfilled_from_defaults(tmp_path):
    p = tmp_path / "config.json"
    p.write_text(json.dumps({"model": "medium"}), encoding="utf-8")
    cfg = Config(path=p)
    assert cfg.get("model") == "medium"      # preserved
    assert cfg.get("ptt_hotkey") == DEFAULTS["ptt_hotkey"]  # backfilled
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python -m pytest tests/test_config.py -v`
Expected: FAIL — `ModuleNotFoundError: talkativeai.config`.

- [ ] **Step 3: Implement Config**

```python
# talkativeai/config.py
import json
import os
from pathlib import Path

DEFAULTS = {
    "ptt_hotkey": "ctrl+space",
    "toggle_hotkey": "ctrl+alt+space",
    "microphone": None,          # None = system default input device
    "model": "small",
    "device": "cuda",            # falls back to "cpu" at runtime if CUDA missing
    "language": "en",            # or "auto"
    "strip_fillers": True,
    "auto_capitalize": True,
    "fix_punctuation_spacing": True,
    "insertion_mode": "paste",   # or "keystroke"
    "launch_on_startup": False,
}

def default_config_path() -> Path:
    base = Path(os.environ.get("APPDATA", Path.home())) / "TalkativeAI"
    return base / "config.json"

class Config:
    def __init__(self, path: Path | None = None):
        self.path = Path(path) if path else default_config_path()
        self.data = self._load()

    def _load(self) -> dict:
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            if not isinstance(raw, dict):
                raise ValueError("config root is not an object")
            merged = {**DEFAULTS, **raw}
        except (FileNotFoundError, ValueError, json.JSONDecodeError, OSError):
            merged = dict(DEFAULTS)
            self.data = merged
            self.save()
            return merged
        # backfill any missing keys and persist if changed
        if merged != raw:
            self.data = merged
            self.save()
        return merged

    def get(self, key):
        return self.data.get(key, DEFAULTS.get(key))

    def set(self, key, value):
        self.data[key] = value

    def save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self.data, indent=2), encoding="utf-8")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/Scripts/python -m pytest tests/test_config.py -v`
Expected: PASS (4 passed).

- [ ] **Step 5: Commit**

```bash
git add talkativeai/config.py tests/test_config.py
git commit -m "feat: config with defaults and corruption recovery"
```

---

## Task 3: TextCleaner (rule-based cleanup)

**Files:**
- Create: `talkativeai/text_cleaner.py`
- Test: `tests/test_text_cleaner.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_text_cleaner.py
from talkativeai.text_cleaner import TextCleaner

def test_strips_filler_words():
    c = TextCleaner(strip_fillers=True, auto_capitalize=False, fix_punctuation_spacing=False)
    assert c.clean("um so uh this is a test") == "so this is a test"

def test_filler_stripping_is_case_insensitive_and_word_bounded():
    c = TextCleaner(strip_fillers=True, auto_capitalize=False, fix_punctuation_spacing=False)
    # "drum" must NOT lose "um"; standalone "Um" is removed
    assert c.clean("Um the drum is loud") == "the drum is loud"

def test_auto_capitalize_first_letter_and_after_period():
    c = TextCleaner(strip_fillers=False, auto_capitalize=True, fix_punctuation_spacing=False)
    assert c.clean("hello world. how are you") == "Hello world. How are you"

def test_fix_punctuation_spacing():
    c = TextCleaner(strip_fillers=False, auto_capitalize=False, fix_punctuation_spacing=True)
    assert c.clean("hello ,world .yes") == "hello, world. yes"

def test_all_toggles_off_only_trims():
    c = TextCleaner(strip_fillers=False, auto_capitalize=False, fix_punctuation_spacing=False)
    assert c.clean("  spaced out  ") == "spaced out"

def test_empty_input_returns_empty():
    c = TextCleaner(strip_fillers=True, auto_capitalize=True, fix_punctuation_spacing=True)
    assert c.clean("   ") == ""
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python -m pytest tests/test_text_cleaner.py -v`
Expected: FAIL — `ModuleNotFoundError: talkativeai.text_cleaner`.

- [ ] **Step 3: Implement TextCleaner**

```python
# talkativeai/text_cleaner.py
import re

FILLERS = {"um", "uh", "erm", "ah", "hmm"}

class TextCleaner:
    def __init__(self, strip_fillers=True, auto_capitalize=True, fix_punctuation_spacing=True):
        self.strip_fillers = strip_fillers
        self.auto_capitalize = auto_capitalize
        self.fix_punctuation_spacing = fix_punctuation_spacing

    def clean(self, text: str) -> str:
        text = (text or "").strip()
        if not text:
            return ""
        if self.strip_fillers:
            text = self._strip_fillers(text)
        if self.fix_punctuation_spacing:
            text = self._fix_spacing(text)
        if self.auto_capitalize:
            text = self._capitalize(text)
        return text.strip()

    def _strip_fillers(self, text: str) -> str:
        def repl(m):
            return "" if m.group(0).lower() in FILLERS else m.group(0)
        out = re.sub(r"\b[A-Za-z]+\b", repl, text)
        # collapse whitespace left behind
        return re.sub(r"\s{2,}", " ", out).strip()

    def _fix_spacing(self, text: str) -> str:
        # remove space before , . ! ? ; :
        text = re.sub(r"\s+([,.!?;:])", r"\1", text)
        # ensure one space after , . ! ? ; : when followed by a word char
        text = re.sub(r"([,.!?;:])(?=\S)", r"\1 ", text)
        return re.sub(r"\s{2,}", " ", text).strip()

    def _capitalize(self, text: str) -> str:
        # capitalize first letter and any letter following . ! ?
        def cap(m):
            return m.group(0).upper()
        text = re.sub(r"(^\s*[a-z])", cap, text)
        text = re.sub(r"([.!?]\s+)([a-z])", lambda m: m.group(1) + m.group(2).upper(), text)
        return text
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/Scripts/python -m pytest tests/test_text_cleaner.py -v`
Expected: PASS (6 passed).

- [ ] **Step 5: Commit**

```bash
git add talkativeai/text_cleaner.py tests/test_text_cleaner.py
git commit -m "feat: rule-based text cleaner"
```

---

## Task 4: StateMachine (guarded transitions)

**Files:**
- Create: `talkativeai/state_machine.py`
- Test: `tests/test_state_machine.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_state_machine.py
import pytest
from talkativeai.state_machine import StateMachine, DictationState

def test_starts_idle():
    sm = StateMachine()
    assert sm.state == DictationState.IDLE

def test_valid_cycle():
    sm = StateMachine()
    assert sm.to_recording() is True
    assert sm.state == DictationState.RECORDING
    assert sm.to_processing() is True
    assert sm.state == DictationState.PROCESSING
    assert sm.to_idle() is True
    assert sm.state == DictationState.IDLE

def test_cannot_record_while_recording():
    sm = StateMachine()
    sm.to_recording()
    assert sm.to_recording() is False   # rejected
    assert sm.state == DictationState.RECORDING

def test_cannot_process_from_idle():
    sm = StateMachine()
    assert sm.to_processing() is False
    assert sm.state == DictationState.IDLE

def test_can_return_to_idle_from_processing():
    sm = StateMachine()
    sm.to_recording(); sm.to_processing()
    assert sm.to_idle() is True
    assert sm.state == DictationState.IDLE
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python -m pytest tests/test_state_machine.py -v`
Expected: FAIL — `ModuleNotFoundError: talkativeai.state_machine`.

- [ ] **Step 3: Implement StateMachine**

```python
# talkativeai/state_machine.py
from enum import Enum

class DictationState(Enum):
    IDLE = "idle"
    RECORDING = "recording"
    PROCESSING = "processing"

# allowed transitions: from -> set of valid targets
_ALLOWED = {
    DictationState.IDLE: {DictationState.RECORDING},
    DictationState.RECORDING: {DictationState.PROCESSING, DictationState.IDLE},
    DictationState.PROCESSING: {DictationState.IDLE},
}

class StateMachine:
    def __init__(self):
        self.state = DictationState.IDLE

    def _transition(self, target: DictationState) -> bool:
        if target in _ALLOWED[self.state]:
            self.state = target
            return True
        return False

    def to_recording(self) -> bool:
        return self._transition(DictationState.RECORDING)

    def to_processing(self) -> bool:
        return self._transition(DictationState.PROCESSING)

    def to_idle(self) -> bool:
        return self._transition(DictationState.IDLE)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/Scripts/python -m pytest tests/test_state_machine.py -v`
Expected: PASS (5 passed).

- [ ] **Step 5: Commit**

```bash
git add talkativeai/state_machine.py tests/test_state_machine.py
git commit -m "feat: dictation state machine with guarded transitions"
```

---

## Task 5: AudioRecorder (mic capture)

**Files:**
- Create: `talkativeai/audio_recorder.py`

No unit test — this touches live hardware. It is verified in the manual smoke test (Task 12). Keep it thin so all logic worth testing lives elsewhere.

- [ ] **Step 1: Implement AudioRecorder**

```python
# talkativeai/audio_recorder.py
import numpy as np
import sounddevice as sd

SAMPLE_RATE = 16000  # faster-whisper expects 16 kHz mono

class AudioRecorder:
    def __init__(self, device=None, sample_rate=SAMPLE_RATE):
        self.device = device
        self.sample_rate = sample_rate
        self._frames = []
        self._stream = None

    def start(self) -> None:
        self._frames = []
        def callback(indata, frames, time, status):
            self._frames.append(indata.copy())
        self._stream = sd.InputStream(
            samplerate=self.sample_rate, channels=1, dtype="float32",
            device=self.device, callback=callback,
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

    def duration(self, audio: np.ndarray) -> float:
        return len(audio) / self.sample_rate
```

- [ ] **Step 2: Manual sanity check (record 1s, print duration)**

Run:
```bash
.venv/Scripts/python -c "import time; from talkativeai.audio_recorder import AudioRecorder; r=AudioRecorder(); r.start(); time.sleep(1); a=r.stop(); print('duration', round(r.duration(a),2))"
```
Expected: prints `duration 1.0` (±0.1). If it errors with no input device, that's expected on machines without a mic — note it and continue.

- [ ] **Step 3: Commit**

```bash
git add talkativeai/audio_recorder.py
git commit -m "feat: audio recorder (mic capture to buffer)"
```

---

## Task 6: Transcriber (faster-whisper wrapper)

**Files:**
- Create: `talkativeai/transcriber.py`

No unit test — depends on the model + GPU. Verified in the smoke test. Handles CUDA→CPU fallback.

- [ ] **Step 1: Implement Transcriber**

```python
# talkativeai/transcriber.py
import logging
import numpy as np

log = logging.getLogger(__name__)

class Transcriber:
    def __init__(self, model_name="small", device="cuda", language="en"):
        from faster_whisper import WhisperModel
        self.language = None if language == "auto" else language
        compute_type = "int8_float16" if device == "cuda" else "int8"
        try:
            self.model = WhisperModel(model_name, device=device, compute_type=compute_type)
            self.device = device
        except Exception as e:
            log.warning("CUDA init failed (%s); falling back to CPU", e)
            self.model = WhisperModel(model_name, device="cpu", compute_type="int8")
            self.device = "cpu"

    def transcribe(self, audio: np.ndarray) -> str:
        if audio is None or len(audio) == 0:
            return ""
        segments, _ = self.model.transcribe(
            audio, language=self.language, vad_filter=True, beam_size=1,
        )
        return " ".join(seg.text.strip() for seg in segments).strip()
```

- [ ] **Step 2: Manual sanity check (model loads)**

Run:
```bash
.venv/Scripts/python -c "from talkativeai.transcriber import Transcriber; t=Transcriber(); print('device', t.device)"
```
Expected: downloads the `small` model on first run, then prints `device cuda` (or `device cpu` if CUDA libs unavailable — either is acceptable).

- [ ] **Step 3: Commit**

```bash
git add talkativeai/transcriber.py
git commit -m "feat: faster-whisper transcriber with CPU fallback"
```

---

## Task 7: TextInserter (clipboard paste + restore, keystroke fallback)

**Files:**
- Create: `talkativeai/text_inserter.py`

No unit test — drives real clipboard/keystrokes. Verified in smoke test.

- [ ] **Step 1: Implement TextInserter**

```python
# talkativeai/text_inserter.py
import logging
import time
import pyperclip
from pynput.keyboard import Controller, Key

log = logging.getLogger(__name__)

class TextInserter:
    def __init__(self, mode="paste", restore_delay=0.15):
        self.mode = mode
        self.restore_delay = restore_delay
        self._kb = Controller()

    def insert(self, text: str) -> None:
        if not text:
            return
        if self.mode == "keystroke":
            self._type(text)
            return
        try:
            self._paste(text)
        except Exception as e:
            log.warning("paste failed (%s); using keystroke fallback", e)
            self._type(text)

    def _paste(self, text: str) -> None:
        try:
            original = pyperclip.paste()
        except Exception:
            original = ""
        pyperclip.copy(text)
        with self._kb.pressed(Key.ctrl):
            self._kb.press("v")
            self._kb.release("v")
        time.sleep(self.restore_delay)
        try:
            pyperclip.copy(original)
        except Exception:
            pass

    def _type(self, text: str) -> None:
        self._kb.type(text)
```

- [ ] **Step 2: Manual sanity check (paste into focused window)**

Run (then quickly focus Notepad within 3s):
```bash
.venv/Scripts/python -c "import time; from talkativeai.text_inserter import TextInserter; time.sleep(3); TextInserter().insert('hello from talkativeai')"
```
Expected: `hello from talkativeai` appears in the focused text field; prior clipboard is restored.

- [ ] **Step 3: Commit**

```bash
git add talkativeai/text_inserter.py
git commit -m "feat: text inserter with clipboard restore and keystroke fallback"
```

---

## Task 8: HotkeyManager (global PTT + toggle)

**Files:**
- Create: `talkativeai/hotkey_manager.py`

No unit test — global keyboard hooks. Verified in smoke test.

- [ ] **Step 1: Implement HotkeyManager**

```python
# talkativeai/hotkey_manager.py
import logging
from pynput import keyboard

log = logging.getLogger(__name__)

def _parse(hotkey: str) -> str:
    # convert "ctrl+alt+space" -> pynput HotKey format "<ctrl>+<alt>+<space>"
    parts = []
    for p in hotkey.lower().split("+"):
        p = p.strip()
        if p in {"ctrl", "alt", "shift", "cmd"}:
            parts.append(f"<{p}>")
        elif len(p) == 1:
            parts.append(p)
        else:
            parts.append(f"<{p}>")
    return "+".join(parts)

class HotkeyManager:
    """Emits callbacks:
       on_ptt_press / on_ptt_release  (hold-to-talk)
       on_toggle                      (tap-to-toggle)
    """
    def __init__(self, ptt_hotkey, toggle_hotkey,
                 on_ptt_press, on_ptt_release, on_toggle):
        self._ptt = keyboard.HotKey(keyboard.HotKey.parse(_parse(ptt_hotkey)),
                                    self._ptt_activate)
        self._toggle = keyboard.HotKey(keyboard.HotKey.parse(_parse(toggle_hotkey)),
                                       on_toggle)
        self._on_ptt_press = on_ptt_press
        self._on_ptt_release = on_ptt_release
        self._ptt_active = False
        self._listener = None

    def _ptt_activate(self):
        if not self._ptt_active:
            self._ptt_active = True
            self._on_ptt_press()

    def _for_canonical(self, f):
        return lambda k: f(self._listener.canonical(k))

    def _on_press(self, key):
        self._ptt.press(self._listener.canonical(key))
        self._toggle.press(self._listener.canonical(key))

    def _on_release(self, key):
        # releasing any part of the PTT combo ends the hold
        if self._ptt_active:
            self._ptt_active = False
            self._on_ptt_release()
        self._ptt.release(self._listener.canonical(key))
        self._toggle.release(self._listener.canonical(key))

    def start(self):
        self._listener = keyboard.Listener(
            on_press=self._on_press, on_release=self._on_release)
        self._listener.start()

    def stop(self):
        if self._listener:
            self._listener.stop()
            self._listener = None
```

- [ ] **Step 2: Manual sanity check (prints on hotkey)**

Run (press Ctrl+Space, then Ctrl+Alt+Space, then Ctrl+C to quit):
```bash
.venv/Scripts/python -c "import time; from talkativeai.hotkey_manager import HotkeyManager; h=HotkeyManager('ctrl+space','ctrl+alt+space', lambda: print('PTT down'), lambda: print('PTT up'), lambda: print('TOGGLE')); h.start(); time.sleep(15)"
```
Expected: "PTT down"/"PTT up" while holding/releasing Ctrl+Space; "TOGGLE" on Ctrl+Alt+Space.

- [ ] **Step 3: Commit**

```bash
git add talkativeai/hotkey_manager.py
git commit -m "feat: global hotkey manager (PTT hold + toggle)"
```

---

## Task 9: AppController (pipeline orchestration, tested with mocks)

**Files:**
- Create: `talkativeai/controller.py`
- Test: `tests/test_controller.py`

The controller depends only on the small interfaces (recorder/transcriber/cleaner/inserter/overlay callbacks), so it is fully unit-testable with fakes.

- [ ] **Step 1: Write failing tests**

```python
# tests/test_controller.py
import numpy as np
from talkativeai.controller import AppController
from talkativeai.state_machine import DictationState

class FakeRecorder:
    def __init__(self, audio): self._audio = audio; self.started = False
    def start(self): self.started = True
    def stop(self): self.started = False; return self._audio
    def duration(self, a): return len(a) / 16000

class FakeTranscriber:
    def __init__(self, text): self._text = text; self.calls = 0
    def transcribe(self, audio): self.calls += 1; return self._text

class Recorder1s(FakeRecorder):
    def __init__(self, text_audio=16000): super().__init__(np.ones(text_audio, dtype="float32"))

def make(audio_len=16000, raw_text="um hello"):
    rec = FakeRecorder(np.ones(audio_len, dtype="float32"))
    trans = FakeTranscriber(raw_text)
    inserted = []
    from talkativeai.text_cleaner import TextCleaner
    ctrl = AppController(
        recorder=rec, transcriber=trans, cleaner=TextCleaner(),
        inserter=type("I", (), {"insert": lambda self, t: inserted.append(t)})(),
        on_overlay_show=lambda: None, on_overlay_hide=lambda: None,
        min_seconds=0.3,
    )
    return ctrl, rec, trans, inserted

def test_full_cycle_inserts_cleaned_text():
    ctrl, rec, trans, inserted = make(audio_len=16000, raw_text="um hello world")
    ctrl.start_recording()
    assert ctrl.sm.state == DictationState.RECORDING
    assert rec.started is True
    ctrl.stop_recording()   # runs processing synchronously in test
    assert trans.calls == 1
    assert inserted == ["Hello world"]
    assert ctrl.sm.state == DictationState.IDLE

def test_too_short_audio_skips_transcription():
    ctrl, rec, trans, inserted = make(audio_len=1600, raw_text="hello")  # 0.1s
    ctrl.start_recording()
    ctrl.stop_recording()
    assert trans.calls == 0
    assert inserted == []
    assert ctrl.sm.state == DictationState.IDLE

def test_empty_transcript_inserts_nothing():
    ctrl, rec, trans, inserted = make(audio_len=16000, raw_text="   ")
    ctrl.start_recording()
    ctrl.stop_recording()
    assert inserted == []
    assert ctrl.sm.state == DictationState.IDLE

def test_overlapping_start_ignored():
    ctrl, rec, trans, inserted = make()
    ctrl.start_recording()
    ctrl.start_recording()   # second one ignored
    assert ctrl.sm.state == DictationState.RECORDING

def test_transcription_error_returns_to_idle():
    ctrl, rec, _, inserted = make()
    def boom(a): raise RuntimeError("gpu exploded")
    ctrl.transcriber = type("T", (), {"transcribe": staticmethod(boom)})()
    ctrl.start_recording()
    ctrl.stop_recording()
    assert ctrl.sm.state == DictationState.IDLE
    assert inserted == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python -m pytest tests/test_controller.py -v`
Expected: FAIL — `ModuleNotFoundError: talkativeai.controller`.

- [ ] **Step 3: Implement AppController**

```python
# talkativeai/controller.py
import logging
from talkativeai.state_machine import StateMachine

log = logging.getLogger(__name__)

class AppController:
    def __init__(self, recorder, transcriber, cleaner, inserter,
                 on_overlay_show=None, on_overlay_hide=None,
                 on_error=None, min_seconds=0.3, run_async=None):
        self.recorder = recorder
        self.transcriber = transcriber
        self.cleaner = cleaner
        self.inserter = inserter
        self.on_overlay_show = on_overlay_show or (lambda: None)
        self.on_overlay_hide = on_overlay_hide or (lambda: None)
        self.on_error = on_error or (lambda msg: log.error(msg))
        self.min_seconds = min_seconds
        # run_async(fn): schedule heavy work off the caller thread.
        # In tests it's None -> runs synchronously.
        self.run_async = run_async
        self.sm = StateMachine()

    # --- hotkey entry points ---
    def start_recording(self):
        if not self.sm.to_recording():
            return
        try:
            self.recorder.start()
            self.on_overlay_show()
        except Exception as e:
            self.on_error(f"Microphone error: {e}")
            self.sm.to_idle()

    def stop_recording(self):
        if self.sm.state.name != "RECORDING":
            return
        if not self.sm.to_processing():
            return
        self.on_overlay_hide()
        if self.run_async:
            self.run_async(self._process)
        else:
            self._process()

    def toggle(self):
        if self.sm.state.name == "IDLE":
            self.start_recording()
        elif self.sm.state.name == "RECORDING":
            self.stop_recording()
        # PROCESSING: ignore

    # --- heavy pipeline (runs off UI thread in production) ---
    def _process(self):
        try:
            audio = self.recorder.stop()
            if self.recorder.duration(audio) < self.min_seconds:
                return
            raw = self.transcriber.transcribe(audio)
            cleaned = self.cleaner.clean(raw)
            if cleaned:
                self.inserter.insert(cleaned)
        except Exception as e:
            self.on_error(f"Transcription failed: {e}")
        finally:
            self.sm.to_idle()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/Scripts/python -m pytest tests/test_controller.py -v`
Expected: PASS (5 passed).

- [ ] **Step 5: Run the whole suite**

Run: `.venv/Scripts/python -m pytest -v`
Expected: PASS (all tests from tasks 2,3,4,9).

- [ ] **Step 6: Commit**

```bash
git add talkativeai/controller.py tests/test_controller.py
git commit -m "feat: app controller orchestrating the dictation pipeline"
```

---

## Task 10: UI — Overlay, Tray, Settings window

**Files:**
- Create: `talkativeai/ui/overlay.py`, `talkativeai/ui/tray.py`, `talkativeai/ui/settings_window.py`

UI is verified visually in the smoke test. Keep each file focused.

- [ ] **Step 1: Implement Overlay**

```python
# talkativeai/ui/overlay.py
from PySide6 import QtCore, QtWidgets, QtGui

class Overlay(QtWidgets.QWidget):
    def __init__(self):
        super().__init__(None,
            QtCore.Qt.FramelessWindowHint | QtCore.Qt.WindowStaysOnTopHint |
            QtCore.Qt.Tool)
        self.setAttribute(QtCore.Qt.WA_TranslucentBackground)
        self.setAttribute(QtCore.Qt.WA_ShowWithoutActivating)
        self._label = QtWidgets.QLabel("● Listening…", self)
        self._label.setStyleSheet(
            "background: rgba(20,20,20,220); color: #ff5c5c;"
            "padding: 8px 14px; border-radius: 10px; font-size: 14px;")
        self._label.adjustSize()
        self.resize(self._label.size())

    @QtCore.Slot()
    def show_near_cursor(self):
        pos = QtGui.QCursor.pos()
        self.move(pos.x() + 16, pos.y() + 16)
        self.show()

    @QtCore.Slot()
    def hide_overlay(self):
        self.hide()
```

- [ ] **Step 2: Implement SettingsWindow**

```python
# talkativeai/ui/settings_window.py
from PySide6 import QtWidgets
import sounddevice as sd

class SettingsWindow(QtWidgets.QWidget):
    def __init__(self, config, on_saved=None):
        super().__init__()
        self.config = config
        self.on_saved = on_saved or (lambda: None)
        self.setWindowTitle("TalkativeAI Settings")
        form = QtWidgets.QFormLayout(self)

        self.ptt = QtWidgets.QLineEdit(config.get("ptt_hotkey"))
        self.toggle = QtWidgets.QLineEdit(config.get("toggle_hotkey"))

        self.model = QtWidgets.QComboBox()
        self.model.addItems(["small", "medium"])
        self.model.setCurrentText(config.get("model"))

        self.mic = QtWidgets.QComboBox()
        self.mic.addItem("System default", None)
        for i, d in enumerate(sd.query_devices()):
            if d["max_input_channels"] > 0:
                self.mic.addItem(d["name"], i)

        self.language = QtWidgets.QComboBox()
        self.language.addItems(["en", "auto"])
        self.language.setCurrentText(config.get("language"))

        self.strip_fillers = QtWidgets.QCheckBox(); self.strip_fillers.setChecked(config.get("strip_fillers"))
        self.auto_cap = QtWidgets.QCheckBox(); self.auto_cap.setChecked(config.get("auto_capitalize"))
        self.fix_punct = QtWidgets.QCheckBox(); self.fix_punct.setChecked(config.get("fix_punctuation_spacing"))

        self.insertion = QtWidgets.QComboBox()
        self.insertion.addItems(["paste", "keystroke"])
        self.insertion.setCurrentText(config.get("insertion_mode"))

        form.addRow("Push-to-talk hotkey", self.ptt)
        form.addRow("Toggle hotkey", self.toggle)
        form.addRow("Microphone", self.mic)
        form.addRow("Model", self.model)
        form.addRow("Language", self.language)
        form.addRow("Strip fillers", self.strip_fillers)
        form.addRow("Auto-capitalize", self.auto_cap)
        form.addRow("Fix punctuation spacing", self.fix_punct)
        form.addRow("Insertion mode", self.insertion)

        save = QtWidgets.QPushButton("Save")
        save.clicked.connect(self._save)
        form.addRow(save)

        note = QtWidgets.QLabel("Restart the app for hotkey/model changes to apply.")
        note.setStyleSheet("color: gray; font-size: 11px;")
        form.addRow(note)

    def _save(self):
        self.config.set("ptt_hotkey", self.ptt.text().strip())
        self.config.set("toggle_hotkey", self.toggle.text().strip())
        self.config.set("microphone", self.mic.currentData())
        self.config.set("model", self.model.currentText())
        self.config.set("language", self.language.currentText())
        self.config.set("strip_fillers", self.strip_fillers.isChecked())
        self.config.set("auto_capitalize", self.auto_cap.isChecked())
        self.config.set("fix_punctuation_spacing", self.fix_punct.isChecked())
        self.config.set("insertion_mode", self.insertion.currentText())
        self.config.save()
        self.on_saved()
        self.close()
```

- [ ] **Step 3: Implement TrayApp**

```python
# talkativeai/ui/tray.py
from PySide6 import QtWidgets, QtGui

class TrayApp:
    def __init__(self, app, on_open_settings, on_quit):
        self.tray = QtWidgets.QSystemTrayIcon()
        # simple generated icon (red dot on transparent) so no asset file is needed
        pix = QtGui.QPixmap(32, 32); pix.fill(QtGui.QColor(0, 0, 0, 0))
        p = QtGui.QPainter(pix); p.setBrush(QtGui.QColor("#ff5c5c"))
        p.setPen(QtGui.Qt.NoPen); p.drawEllipse(6, 6, 20, 20); p.end()
        self.tray.setIcon(QtGui.QIcon(pix))
        self.tray.setToolTip("TalkativeAI")

        menu = QtWidgets.QMenu()
        menu.addAction("Settings…", on_open_settings)
        menu.addSeparator()
        menu.addAction("Quit", on_quit)
        self.tray.setContextMenu(menu)
        self.tray.show()

    def notify(self, message: str):
        self.tray.showMessage("TalkativeAI", message)
```

- [ ] **Step 4: Sanity check (tray + settings render)**

Run:
```bash
.venv/Scripts/python -c "import sys; from PySide6 import QtWidgets; from talkativeai.config import Config; from talkativeai.ui.tray import TrayApp; from talkativeai.ui.settings_window import SettingsWindow; app=QtWidgets.QApplication(sys.argv); w=SettingsWindow(Config()); w.show(); TrayApp(app, lambda: w.show(), app.quit); app.exec()"
```
Expected: a tray icon appears and the settings window renders with all fields. Close to exit.

- [ ] **Step 5: Commit**

```bash
git add talkativeai/ui/
git commit -m "feat: tray, overlay, and settings UI"
```

---

## Task 11: Entry point (wire everything + threading)

**Files:**
- Create: `talkativeai/__main__.py`
- Create: `run.bat`

- [ ] **Step 1: Implement __main__.py**

The transcription pipeline must run off the Qt UI thread; hotkey callbacks arrive on the pynput listener thread, so we marshal overlay show/hide onto the Qt thread via signals and run `_process` on a worker thread.

```python
# talkativeai/__main__.py
import logging, os, sys, threading
from logging.handlers import RotatingFileHandler
from pathlib import Path
from PySide6 import QtCore, QtWidgets

from talkativeai.config import Config, default_config_path
from talkativeai.text_cleaner import TextCleaner
from talkativeai.audio_recorder import AudioRecorder
from talkativeai.transcriber import Transcriber
from talkativeai.text_inserter import TextInserter
from talkativeai.hotkey_manager import HotkeyManager
from talkativeai.controller import AppController
from talkativeai.ui.overlay import Overlay
from talkativeai.ui.tray import TrayApp
from talkativeai.ui.settings_window import SettingsWindow

def setup_logging():
    log_dir = default_config_path().parent / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    handler = RotatingFileHandler(log_dir / "talkativeai.log", maxBytes=1_000_000, backupCount=3)
    logging.basicConfig(level=logging.INFO, handlers=[handler],
                        format="%(asctime)s %(levelname)s %(name)s %(message)s")

class Bridge(QtCore.QObject):
    show_overlay = QtCore.Signal()
    hide_overlay = QtCore.Signal()
    notify = QtCore.Signal(str)

def main():
    setup_logging()
    log = logging.getLogger("main")
    cfg = Config()

    app = QtWidgets.QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)  # keep running with only the tray

    overlay = Overlay()
    bridge = Bridge()
    bridge.show_overlay.connect(overlay.show_near_cursor)
    bridge.hide_overlay.connect(overlay.hide_overlay)

    transcriber = Transcriber(cfg.get("model"), cfg.get("device"), cfg.get("language"))
    cleaner = TextCleaner(cfg.get("strip_fillers"), cfg.get("auto_capitalize"),
                          cfg.get("fix_punctuation_spacing"))
    recorder = AudioRecorder(device=cfg.get("microphone"))
    inserter = TextInserter(mode=cfg.get("insertion_mode"))

    def run_async(fn):
        threading.Thread(target=fn, daemon=True).start()

    controller = AppController(
        recorder=recorder, transcriber=transcriber, cleaner=cleaner, inserter=inserter,
        on_overlay_show=bridge.show_overlay.emit,
        on_overlay_hide=bridge.hide_overlay.emit,
        on_error=lambda m: (log.error(m), bridge.notify.emit(m)),
        run_async=run_async,
    )

    hotkeys = HotkeyManager(
        cfg.get("ptt_hotkey"), cfg.get("toggle_hotkey"),
        on_ptt_press=controller.start_recording,
        on_ptt_release=controller.stop_recording,
        on_toggle=controller.toggle,
    )
    hotkeys.start()

    settings = SettingsWindow(cfg)
    tray = TrayApp(app, on_open_settings=settings.show, on_quit=app.quit)
    bridge.notify.connect(tray.notify)

    log.info("TalkativeAI started (device=%s)", transcriber.device)
    tray.notify("TalkativeAI is running. Hold %s to dictate." % cfg.get("ptt_hotkey"))
    code = app.exec()
    hotkeys.stop()
    sys.exit(code)

if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Create run.bat**

```bat
@echo off
cd /d "%~dp0"
start "" ".venv\Scripts\pythonw.exe" -m talkativeai
```

- [ ] **Step 3: Install full dependencies**

Run: `.venv/Scripts/python -m pip install -r requirements.txt`
Expected: all packages install. (faster-whisper pulls ctranslate2; first run downloads the model.)

- [ ] **Step 4: Launch and verify it starts**

Run: `.venv/Scripts/python -m talkativeai`
Expected: tray icon appears, notification "TalkativeAI is running…". Model loads once (watch the log). Leave running for the smoke test.

- [ ] **Step 5: Commit**

```bash
git add talkativeai/__main__.py run.bat
git commit -m "feat: application entry point wiring all components"
```

---

## Task 12: Manual smoke test + docs

**Files:**
- Create: `docs/manual-smoke-test.md`

- [ ] **Step 1: Write the smoke-test checklist**

```markdown
# Manual Smoke Test

Prereq: app running via `.venv/Scripts/python -m talkativeai`.

## Push-to-talk
- [ ] Open Notepad. Hold Ctrl+Space, say "hello world", release.
      → Overlay shows while held; "Hello world" typed into Notepad.
- [ ] Repeat in a browser address bar / text field. → text inserted.
- [ ] Repeat in an IDE (VS Code) editor. → text inserted.

## Toggle
- [ ] Tap Ctrl+Alt+Space, speak a sentence, tap again.
      → text inserted; overlay hidden after.

## Edge cases
- [ ] Tap-and-immediately-release PTT (no speech). → nothing inserted, no error.
- [ ] Speak only "um uh". → nothing or trimmed output; no crash.
- [ ] Clipboard: copy some text, dictate, then paste (Ctrl+V) elsewhere.
      → your original clipboard text is preserved.

## Settings
- [ ] Tray → Settings. Change model to medium, save. Restart app.
      → app still works (may be slower/more accurate).
- [ ] Change microphone in settings, save, restart. → uses selected mic.

## Resilience
- [ ] Unplug/disable mic, try PTT. → tray notification, no crash.
- [ ] Check %APPDATA%/TalkativeAI/logs/talkativeai.log has startup + errors.
```

- [ ] **Step 2: Run through the checklist manually**

Perform each item. Record any failures as new issues to fix before considering v1 done.

- [ ] **Step 3: Update README with run instructions**

Add to `README.md`:
```markdown
## Setup
1. `python -m venv .venv`
2. `.venv\Scripts\python -m pip install -r requirements.txt`
3. `.venv\Scripts\python -m talkativeai`  (or double-click run.bat)

First launch downloads the Whisper model once (~500 MB), then runs offline.

## Usage
- Hold **Ctrl+Space** to dictate (release to insert).
- Tap **Ctrl+Alt+Space** to toggle recording on/off.
- Right-click the tray icon for Settings.

## Run on startup (optional)
Put a shortcut to `run.bat` in `shell:startup`.
```

- [ ] **Step 4: Commit**

```bash
git add docs/manual-smoke-test.md README.md
git commit -m "docs: smoke test checklist and run instructions"
```

---

## Self-Review Notes

- **Spec coverage:** local faster-whisper (T6), rule-based cleanup (T3), PTT+toggle (T8), hybrid paste+restore+fallback (T7), tray+overlay+settings (T10), JSON config w/ recovery (T2), state machine + guards + edge cases (T4, T9), CUDA→CPU fallback (T6), never-crash error handling (T9, T11), logging (T11), distribution via venv+run.bat (T11, T12). All covered.
- **Model lifecycle:** loaded once in `__main__` (T11), passed to controller — matches spec.
- **Threading:** pipeline runs on a worker thread; overlay/notify marshalled to Qt via signals (T11) — the one real integration subtlety, made explicit.
- **Types consistent:** `AppController` interface (recorder/transcriber/cleaner/inserter, `run_async`, `min_seconds`) matches between T9 tests, T9 impl, and T11 wiring. `Config.get/set/save`, `TextCleaner.clean`, `StateMachine.to_*` names consistent across tasks.
- **Deferred (spec "out of scope"):** LLM cleanup, history UI, launch-on-startup auto-registration (config flag exists; wiring deferred), PyInstaller exe. Noted, not built.