> **Historical document** — an original design/plan kept for the record. It no longer matches the shipped app (see [docs/archive/README.md](../../README.md) for what changed). Do not use it as documentation.

# Live Chunk-Append Typing Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans.

**Goal:** Type words into the focused app as the user speaks (chunk-append, no deletes).

**Architecture:** Pure `new_suffix()` diff decides what's new to type. A streaming thread in the entry point transcribes audio-so-far every ~2s and types the new tail via keystrokes. On release, the controller (in live mode) types only the remaining tail. A `live_typing` config toggle (default on) selects live vs. type-on-release.

**Tech Stack:** existing. Tests: `.venv\Scripts\python3.exe -m pytest`.

---

## Task 1: text_stream.new_suffix (pure diff, TDD)

**Files:**
- Create: `talkativeai/text_stream.py`
- Test: `tests/test_text_stream.py`

- [ ] **Step 1: Failing tests**

```python
# tests/test_text_stream.py
from talkativeai.text_stream import new_suffix


def test_empty_typed_returns_whole_transcript():
    assert new_suffix("", "hello world") == "hello world"


def test_exact_match_returns_empty():
    assert new_suffix("hello world", "hello world") == ""


def test_appends_new_words_after_common_prefix():
    assert new_suffix("hello", "hello world") == "world"


def test_multi_word_prefix():
    assert new_suffix("the quick brown", "the quick brown fox jumps") == "fox jumps"


def test_whitespace_is_normalized_for_comparison():
    assert new_suffix("hello   world", "hello world again") == "again"


def test_divergence_returns_suffix_after_divergence_point():
    # typed "i scream", transcript now "i scream sunday" -> only "sunday"
    assert new_suffix("i scream", "i scream sunday") == "sunday"


def test_transcript_shorter_than_typed_returns_empty():
    assert new_suffix("hello world foo", "hello world") == ""


def test_no_common_prefix_returns_full_transcript():
    assert new_suffix("apple", "banana split") == "banana split"
```

- [ ] **Step 2: Run — expect fail**

Run: `.venv\Scripts\python3.exe -m pytest tests/test_text_stream.py -q`
Expected: FAIL — module missing.

- [ ] **Step 3: Implement text_stream.py**

```python
# talkativeai/text_stream.py

def _words(s: str):
    return s.split()


def new_suffix(already_typed: str, new_transcript: str) -> str:
    """Return the words in new_transcript that come after the longest common
    word-prefix shared with already_typed. Never returns text that would
    require rewriting already_typed (chunk-append is forward-only)."""
    typed = _words(already_typed)
    trans = _words(new_transcript)
    i = 0
    while i < len(typed) and i < len(trans) and typed[i] == trans[i]:
        i += 1
    remaining = trans[i:]
    return " ".join(remaining)
```

- [ ] **Step 4: Run — expect pass**

Run: `.venv\Scripts\python3.exe -m pytest tests/test_text_stream.py -q`
Expected: PASS (8 passed).

- [ ] **Step 5: Commit**

```bash
git add talkativeai/text_stream.py tests/test_text_stream.py
git commit -m "feat: pure new_suffix diff for chunk-append live typing"
```

---

## Task 2: live_typing config toggle + settings checkbox

**Files:**
- Modify: `talkativeai/config.py` (add default)
- Modify: `talkativeai/ui/settings_window.py` (add checkbox)

- [ ] **Step 1: Add default to config.py DEFAULTS**

In `talkativeai/config.py`, add after `"insertion_mode": "paste",`:
```python
    "live_typing": True,         # type words as you speak (chunk-append)
```

- [ ] **Step 2: Add checkbox to settings_window.py**

After the `self.fix_punct` checkbox block, add:
```python
        self.live_typing = QtWidgets.QCheckBox()
        self.live_typing.setChecked(config.get("live_typing"))
```
Add a form row after "Fix punctuation spacing":
```python
        form.addRow("Live typing (as you speak)", self.live_typing)
```
In `_save`, add:
```python
        self.config.set("live_typing", self.live_typing.isChecked())
```

- [ ] **Step 3: Verify settings constructs offscreen**

Run:
```bash
set QT_QPA_PLATFORM=offscreen
.venv\Scripts\python3.exe -c "import sys; from PySide6 import QtWidgets; from talkativeai.config import Config; from talkativeai.ui.settings_window import SettingsWindow; app=QtWidgets.QApplication(sys.argv); w=SettingsWindow(Config(path='__s.json')); print('live_typing', w.live_typing.isChecked())"
```
Expected: prints `live_typing True`. Delete `__s.json`.

- [ ] **Step 4: Full suite + commit**

Run: `.venv\Scripts\python3.exe -m pytest -q` (expect pass)
```bash
git add talkativeai/config.py talkativeai/ui/settings_window.py
git commit -m "feat: live_typing config toggle + settings checkbox"
```

---

## Task 3: Controller live-typing mode (release types tail only)

**Files:**
- Modify: `talkativeai/controller.py`
- Test: `tests/test_controller.py`

The controller gets a `live_typing` flag and a shared `typed_so_far` string that the
streaming loop updates. In live mode, `_process` types only `new_suffix(typed_so_far,
final_raw)` and skips whole-sentence cleanup. In non-live mode, behavior is unchanged.

- [ ] **Step 1: Add failing tests to tests/test_controller.py**

```python
def test_live_mode_types_only_untyped_tail():
    from talkativeai.controller import AppController
    from talkativeai.text_cleaner import TextCleaner
    import numpy as np
    rec = FakeRecorder(np.ones(16000, dtype="float32"))
    trans = FakeTranscriber("hello world how are you")
    inserted = []
    ctrl = AppController(
        recorder=rec, transcriber=trans, cleaner=TextCleaner(),
        inserter=type("I", (), {"insert": lambda self, t: inserted.append(t)})(),
        min_seconds=0.3, live_typing=True,
    )
    ctrl.typed_so_far = "hello world"   # streaming already typed this
    ctrl.start_recording()
    ctrl.stop_recording()
    assert inserted == ["how are you"]   # only the tail


def test_non_live_mode_unchanged_types_cleaned_full():
    from talkativeai.controller import AppController
    from talkativeai.text_cleaner import TextCleaner
    import numpy as np
    rec = FakeRecorder(np.ones(16000, dtype="float32"))
    trans = FakeTranscriber("um hello world")
    inserted = []
    ctrl = AppController(
        recorder=rec, transcriber=trans, cleaner=TextCleaner(),
        inserter=type("I", (), {"insert": lambda self, t: inserted.append(t)})(),
        min_seconds=0.3, live_typing=False,
    )
    ctrl.start_recording()
    ctrl.stop_recording()
    assert inserted == ["Hello world"]   # cleaned full text
```

- [ ] **Step 2: Run — expect fail**

Run: `.venv\Scripts\python3.exe -m pytest tests/test_controller.py -q`
Expected: FAIL — `live_typing` kwarg unknown / behavior mismatch.

- [ ] **Step 3: Update controller.py**

Add `live_typing=False` param and `typed_so_far` state in `__init__`:
```python
    def __init__(self, recorder, transcriber, cleaner, inserter,
                 on_overlay_show=None, on_overlay_hide=None,
                 on_error=None, on_notice=None, min_seconds=0.3, run_async=None,
                 live_typing=False):
```
After `self.sm = StateMachine()` add:
```python
        self.live_typing = live_typing
        self.typed_so_far = ""   # shared with the streaming loop in live mode
```

Reset `typed_so_far` at the start of `start_recording` (after the `to_recording` guard):
```python
        self.typed_so_far = ""
```

Replace the body of `_process` transcription section:
```python
            raw = self.transcriber.transcribe(audio)
            if self.live_typing:
                from talkativeai.text_stream import new_suffix
                tail = new_suffix(self.typed_so_far, raw)
                if tail:
                    prefix = " " if self.typed_so_far and not tail.startswith(" ") else ""
                    self.inserter.insert(prefix + tail)
                    self.typed_so_far = (self.typed_so_far + prefix + tail).strip()
                elif not self.typed_so_far:
                    self.on_notice("No speech detected — check your microphone selection/volume.")
            else:
                cleaned = self.cleaner.clean(raw)
                if cleaned:
                    self.inserter.insert(cleaned)
                else:
                    self.on_notice("No speech detected — check your microphone selection/volume.")
```

- [ ] **Step 4: Run — expect pass**

Run: `.venv\Scripts\python3.exe -m pytest -q`
Expected: PASS (all, including 2 new).

- [ ] **Step 5: Commit**

```bash
git add talkativeai/controller.py tests/test_controller.py
git commit -m "feat: controller live-typing mode types only untyped tail on release"
```

---

## Task 4: Streaming loop in entry point

**Files:**
- Modify: `talkativeai/__main__.py`

- [ ] **Step 1: Build controller with live_typing from config**

In `talkativeai/__main__.py`, update the `AppController(...)` construction to pass:
```python
        live_typing=cfg.get("live_typing"),
```

- [ ] **Step 2: Add the streaming loop (only active in live mode)**

After `hotkeys.start()`, add:
```python
    def stream_loop():
        import time
        from talkativeai.audio_utils import normalize_gain
        from talkativeai.text_stream import new_suffix
        if not cfg.get("live_typing"):
            return
        while True:
            time.sleep(2.0)
            try:
                if not controller.is_recording():
                    continue
                snap = controller.preview_snapshot()
                if snap is None or len(snap) < int(0.6 * 16000):
                    continue
                seg, _ = transcriber.model.transcribe(
                    normalize_gain(snap),
                    language=transcriber.language, vad_filter=False, beam_size=1)
                raw = " ".join(s.text.strip() for s in seg).strip()
                tail = new_suffix(controller.typed_so_far, raw)
                if tail:
                    prefix = " " if controller.typed_so_far and not tail.startswith(" ") else ""
                    inserter.insert(prefix + tail)
                    controller.typed_so_far = (controller.typed_so_far + prefix + tail).strip()
            except Exception:
                pass  # streaming is best-effort; final release pass still runs

    threading.Thread(target=stream_loop, daemon=True).start()
```

Note: streaming and the release tail both use `controller.typed_so_far`, so the release
pass in `_process` types only whatever the streaming loop hadn't yet typed.

- [ ] **Step 3: Ensure streaming uses keystroke insertion**

The streaming loop calls `inserter.insert(...)`. For live typing, keystroke mode avoids
clobbering the clipboard each chunk. In `__main__.py`, where `inserter` is built, force
keystroke mode when live typing is on:
```python
    inserter = TextInserter(
        mode="keystroke" if cfg.get("live_typing") else cfg.get("insertion_mode"))
```
(Replace the existing `inserter = TextInserter(mode=cfg.get("insertion_mode"))` line.)

- [ ] **Step 4: Launch and verify app stays up**

Run the app; hold hotkey, speak a long sentence → words appear in ~2s groups; release →
tail completes. (Manual smoke.)

- [ ] **Step 5: Full suite + commit**

Run: `.venv\Scripts\python3.exe -m pytest -q` (expect pass)
```bash
git add talkativeai/__main__.py
git commit -m "feat: streaming loop types words as you speak in live mode"
```

---

## Task 5: Smoke test doc

**Files:**
- Modify: `docs/manual-smoke-test.md`

- [ ] **Step 1: Append**

```markdown
## Live typing
- [ ] Live typing ON (default): hold hotkey, speak a long sentence → words appear in
      ~2s groups while speaking; on release the last words complete; nothing is deleted.
- [ ] Settings → uncheck "Live typing", Save (restart) → words appear only on release
      (cleaned), as before.
```

- [ ] **Step 2: Commit**

```bash
git add docs/manual-smoke-test.md
git commit -m "docs: smoke test for live typing"
```

---

## Self-Review Notes
- Spec coverage: diff (T1), toggle+UI (T2), release-tail live mode (T3), streaming loop +
  keystroke insertion (T4), smoke (T5). Covered.
- Types: `new_suffix(already_typed, new_transcript)` used identically in T3 controller and
  T4 stream loop; `controller.typed_so_far` shared between them; `live_typing` flows
  config → controller (T3) and stream loop (T4).
- Shared-state note: streaming loop and `_process` both append to `typed_so_far`; the
  release pass reads the streaming loop's latest value, so it only types the remaining
  tail. Both run for the same recording; `_process` runs after `stop_recording` flips
  state out of RECORDING, so the stream loop's `is_recording()` guard stops it feeding
  concurrently.
- No placeholders; all code concrete.
```