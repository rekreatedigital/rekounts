# Architecture

Rekounts is a local, offline Windows dictation app. You hold a hotkey, speak,
and cleaned-up text is typed into whatever app has focus. No audio or text ever
leaves your machine — see [docs/privacy.md](docs/privacy.md) for the full
accounting, including the few network touchpoints that do exist.

- **Language / runtime:** Python 3.11+ (developed on 3.12)
- **Speech:** [faster-whisper](https://github.com/SYSTRAN/faster-whisper) (CTranslate2), CPU by default
- **UI:** PySide6 (Qt) — tray icon, a monochrome dictation pill, a settings window, and the Hub
- **Storage:** stdlib `sqlite3` (`history.db`) + a JSON config file
- **Input/output:** `sounddevice` (mic capture), `pynput` (global hotkey), native Win32 via `ctypes` + `pywin32` (clipboard/paste/keystrokes)

## Entry point and a critical import-order rule

`python -m rekounts` runs [`rekounts/__main__.py`](rekounts/__main__.py);
the frozen `Rekounts.exe` runs the same file.

> **Do not import PySide6 (or any `rekounts/ui/*` module) at module top.**
> Qt bundles an OpenMP runtime that conflicts with CTranslate2's; if Qt loads
> **before** the Whisper model, the process hard-crashes with a native access
> violation. `__main__.py` therefore loads the model first, then imports Qt
> inside `_run()`. Any packaging/build change must preserve this order.
>
> The same class of collision bites the PyInstaller build from a different
> angle: PyInstaller collects two *different* versions of `msvcp140.dll` (one
> top-level, one private to `PySide6\`), and loading both kills the process.
> `Rekounts.spec` de-duplicates them. See the comments in that file.

Startup sequence in `_run()`:

1. `setup_logging()` → rotating log file (see paths below).
2. `_acquire_single_instance()` → a named Windows mutex. A second launch detects
   it, logs "Another instance is already running", and exits — so you never get
   duplicate tray icons or two hotkey listeners fighting.
3. Build the model + pipeline objects (`Transcriber`, `TextCleaner`,
   `AudioRecorder`, `TextInserter`). The model is warmed on a background thread
   so the first real dictation is not slower than the rest.
4. **Now** import Qt and build the `Overlay`, `History`, `TrayApp`, `Dashboard`
   (the Hub — settings are a page inside it, not a separate window).
5. Wire hotkeys → `AppController`; start the live-typing loop; run the Qt event
   loop.

### Threading model

Recording, transcription and the hotkey listener all run off the GUI thread. A
small `Bridge(QObject)` in `__main__.py` carries three signals — `state`,
`result`, `notify` — so worker threads never touch Qt widgets directly.
`History` is the other shared object; it guards a single SQLite connection with
one re-entrant lock.

**The keyboard-hook thread is sacred.** pynput delivers every key event on the
thread that services the Windows low-level keyboard hook, and Windows *silently
removes* a hook whose callback runs long (`LowLevelHooksTimeout`, ~200-300 ms) —
after which the hotkey is dead for the rest of the session with no error. So the
hook callbacks (`HotkeyManager._on_press/_on_release`) do the bare minimum —
canonicalize the key, stamp the arrival time, and hand off to a
`_ThreadedDispatcher` — and everything expensive (combo matching, the gesture
machine, and above all `AudioRecorder.start()` opening the mic stream) runs on a
dedicated worker thread. Event timestamps are captured on the hook thread and
threaded through, so tap-vs-hold timing stays correct even if the worker lags.
A `HotkeyWatchdog` polls OS ground truth (`GetAsyncKeyState` on the combo's own
keys) and rebuilds the listener if the hook is lost anyway, or heals the combo
tracker after a lost key-up — so a dead hook self-recovers instead of needing an
app restart.

### Live-apply settings (no restart)

`apply_settings()` in `__main__.py` runs whenever a setting changes in the Hub.
It rebuilds the hotkey listener **only when the hotkey value actually changed**
(rebuilding it on every Save would hand a fresh idle gesture to a recording
already in flight, which could then never be stopped by the hotkey), rebuilds
`TextCleaner`/`TextInserter`, updates the controller's flags, and sets
`language`/`beam_size` straight on the transcriber
(both are read per `transcribe()` call, so they are live). Only a change of
model **name or device** triggers a reload, which happens on a background thread
with a "Loading model… / Model ready" notice. The recorder needs nothing: it
re-resolves its device through a `device_provider` callback on each `start()`.

This replaced the old restart-on-save, which raced the single-instance mutex.

## Module map (`rekounts/`)

| Module | Responsibility |
| --- | --- |
| `__init__.py` | `__version__` — the single source of truth for the version string (`pyproject.toml` and `Rekounts.spec` both read it) |
| `__main__.py` | Entry point, logging, single-instance mutex, wiring, live-apply, live-typing loop, Qt event loop |
| `config.py` | `Config` + `DEFAULTS`; loads/saves `config.json`, backfills missing keys, recovers from corruption, migrates the legacy `ptt_hotkey` into the unified `hotkey` |
| `controller.py` | `AppController` — orchestrates record → transcribe → clean → insert; drives the state machine; emits `on_state` / `on_result` |
| `state_machine.py` | `StateMachine` over `IDLE → RECORDING → PROCESSING → IDLE` (rejects illegal transitions) |
| `audio_recorder.py` | `AudioRecorder` — 16 kHz mono capture via `sounddevice`; optional pre-roll ring buffer; live level + snapshot |
| `audio_utils.py` | `rms_level`, `normalize_gain` — pure-numpy audio helpers (gain-boost quiet mics) |
| `device_utils.py` | `list_microphones()` — the canonical mic list (one entry per endpoint, full names, DirectSound-only); resolve a saved mic **name** → device index; RMS thresholds for the mic Test button |
| `transcriber.py` | `Transcriber` — wraps faster-whisper; CPU/CUDA selection, offline-first model loads, dictionary hotwords, warm-up, a model lock so streaming can't race the final pass, and the silence-hallucination phrase set |
| `text_cleaner.py` | `TextCleaner` — strip fillers, capitalize, fix punctuation spacing, collapse stutters |
| `text_inserter.py` | `TextInserter` — paste (default) or keystroke insertion behind a Win32 backend; native clipboard save/restore across all formats, modifier-release wait, elevation (UIPI) and focus-change guards; returns an `InsertResult` outcome |
| `text_stream.py` | `LiveTyper` + `new_suffix` — forward-only word streaming for experimental live typing |
| `hotkey_manager.py` | `HotkeyManager` — one global hotkey, three gestures (`TapHoldGesture` + `_Combo`); the hotkey-string parser/validator; a `_ThreadedDispatcher` that keeps the OS hook thread free, and a `HotkeyWatchdog` that rebuilds a silently-dead hook / heals a stuck combo |
| `history.py` | `History` — SQLite store for dictation entries and dictionary words; stats, streaks and daily word counts |
| `languages.py` | Supported languages (Auto / English / Tagalog) and label↔code mapping |
| `startup.py` | Enable/disable/query **launch on login** (Windows `HKCU\...\Run` registry key, macOS `~/Library/LaunchAgents` plist); also purges the pre-rename `TalkativeAI` entry |
| `paths.py` | Every per-user filesystem location in one place (`%APPDATA%\Rekounts` and its children), plus the pre-rename folder name |
| `migrate.py` | One-time move of user state from `%APPDATA%\TalkativeAI` to `%APPDATA%\Rekounts`. Runs before logging and `Config()`, since both would otherwise create/read the new folder first. Marker-file completion, per-item atomic staging, copy-except-models, never overwrites, never deletes the old folder |
| `ui/tray.py` | `TrayApp` — tray icon, menu (Dashboard, Settings, Microphone, Language, Check for Updates, Help, Quit), toasts, the GitHub release check |
| `ui/branding.py` | Loads `assets/icon.ico` for the tray and every window, and sets the Windows AppUserModelID |
| `ui/overlay.py` | `Overlay` — the frameless monochrome pill: idle / hover / recording (✕, waveform, ✓) / processing. Follows the monitor the mouse is on; never takes focus |
| `sounds.py` | `Sounds` — non-blocking start/stop/error audio cues (stdlib `winsound`); silent when disabled |
| `ui/dashboard.py` | `Dashboard` — the Hub, the app's one window: Dictation / Insights / Dictionary / Settings / Account |
| `ui/settings_page.py` | `SettingsPage` — every setting, applied the instant you change it (no Save button, no restart) |
| `ui/theme.py` | The single monochrome palette + stylesheet every Hub page shares |

## The hotkey engine

One physical hotkey (`Ctrl+Win` by default) drives every gesture, classified in
`TapHoldGesture` with an injectable clock and scheduler so the timing is
unit-testable with a fake clock:

| Gesture | Result |
| --- | --- |
| Hold (> ~0.35 s) then release | Push-to-talk: record while held, insert on release |
| Two taps within ~0.30 s | Hands-free: latch recording on |
| Tap while hands-free | Stop and insert |
| One tap while idle | **Cancel**, not stop — that clip is only tap-duration plus the double-tap window, so transcribing it would paste ambient noise. A hint toast is shown instead |

`_Combo` only reacts to keys that are part of the configured hotkey, so
releasing an unrelated key can never end a hold. pynput calls the Windows key
`Key.cmd` on every platform, so `win` / `windows` / `super` / `meta` all resolve
to `<cmd>`.

**Staying in sync with the controller.** A recording can also end by a route the
gesture didn't drive — the overlay ✓/✕ buttons or the auto-stop timer. When that
happens `AppController.on_recording_ended` fires `TapHoldGesture.external_stop()`,
which drops any latch so the next press starts a fresh recording instead of being
swallowed "stopping" a recording that is already gone. And if a press's start is
*refused* while the controller is already `RECORDING` (a gesture that was rebuilt
in front of a live recording), the gesture routes it to stop instead — a toggle
fallback via the injected `is_recording` provider. These two mechanisms keep the
one-key gesture and the controller's state machine from drifting apart.

## Data flow (one dictation)

```
hotkey (pynput)  →  TapHoldGesture  →  HotkeyManager
  → AppController.start_recording()  [IDLE → RECORDING]
      → AudioRecorder.start()        (mic → 16 kHz mono frames, RAM only)
      → on_state("recording") → Bridge → Overlay expands to the pill
  ── user speaks ──
release / tap
  → AppController.stop_recording()   [RECORDING → PROCESSING]
      → run_async(_process):
          AudioRecorder.stop()       → numpy buffer
          normalize_gain()           → boost quiet mics
          Transcriber.transcribe()   → raw text (faster-whisper, local)
          hallucination filter       → drop "Thank you."-style phantoms
          TextCleaner.clean()        → cleaned text
          TextInserter.insert()      → paste/keystroke → InsertResult
      → on_result(raw, cleaned, duration_s, inserted)
          → History.add()            → history.db  (records it even when the
                                        insertion was blocked — the Hub is the
                                        safety net)
  → [PROCESSING → IDLE]
```

Live typing (off by default, experimental) adds a background loop in
`__main__.py` that periodically transcribes the in-progress buffer and streams
new words via `LiveTyper`; the release pass then appends only the remaining
tail. The loop re-checks `controller.live_typing` every iteration so the setting
can be flipped at runtime.

## Where things live on disk

| What | Path |
| --- | --- |
| Config | `%APPDATA%\Rekounts\config.json` |
| History + dictionary | `%APPDATA%\Rekounts\history.db` (SQLite; timestamps stored UTC, grouped by local date for stats) |
| Logs | `%APPDATA%\Rekounts\logs\rekounts.log` (rotating, ≤1 MB × 3) |
| Speech models | `%APPDATA%\Rekounts\models\<name>\` (fetched from the project's own release host on first use, SHA256-verified, then fully offline — see `rekounts/models.py`) |
| Launch-on-login entry | `HKCU\Software\Microsoft\Windows\CurrentVersion\Run\Rekounts` (when enabled) |

Audio is never written to disk.

## Packaging

`Rekounts.spec` builds a onedir PyInstaller bundle (`build.bat` →
`dist\Rekounts\Rekounts.exe`, ~350 MB). Notable decisions, all commented
in the spec: CUDA/GPU stacks excluded (CPU-only build), native/data-heavy
packages collected wholesale via `collect_all`, the MSVC runtime de-duplicated,
and the `.exe` stamped with a version resource read from
`rekounts/__init__.py`. The speech model is deliberately **not** bundled — it
downloads once, exactly as it does from source. The `.exe` is unsigned, so
SmartScreen warns on first run.

## Testing

Pure-logic modules are unit-tested with `pytest` (`tests/`, 400+ tests). The
suite needs neither the speech model nor pywin32 — see `requirements-test.txt`,
which is what CI installs. Hardware- and UI-dependent behavior (mic capture,
real hotkeys, insertion into other apps, tray/overlay/Hub rendering, and the
frozen `.exe`) is covered by
[docs/manual-smoke-test.md](docs/manual-smoke-test.md).
