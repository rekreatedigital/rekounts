> **Historical document** — an original design/plan kept for the record. It no longer matches the shipped app (see [docs/archive/README.md](../../README.md) for what changed). Do not use it as documentation.

# TalkativeAI — Local Voice Dictation for Windows

**Date:** 2026-07-14
**Status:** Approved design, ready for implementation planning

## Goal

A Wispr Flow–style voice dictation app for Windows, built as a personal daily driver.
Press a hotkey, speak, and have cleaned-up speech typed into whatever application is
focused. Everything runs locally — audio never leaves the machine.

**Primary objective:** reliable, low-latency, always-on background dictation that "just
works" when the hotkey is pressed. Polish is secondary to reliability.

## Target Machine

- GPU: NVIDIA GeForce GTX 1650 SUPER (4 GB VRAM), CUDA-capable
- CPU: Intel i3-10105F (4 cores / 8 threads)
- RAM: 64 GB
- OS: Windows 10 Pro (19045)

The 4 GB VRAM is the key constraint. Default Whisper model is `small` (int8), with
`medium` as an option. `large-v3` is out of scope for this hardware.

## Key Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Speech-to-text | Local `faster-whisper` on CUDA GPU | Private, no per-use cost, offline; runs well on the GTX 1650 SUPER |
| AI cleanup | Rule-based only (no LLM) for v1 | Fully local, zero added latency; LLM cleanup deferred |
| Trigger | Push-to-talk (hold) **and** toggle (tap-tap), both configurable | Covers quick phrases and long-form dictation |
| Text insertion | Hybrid: clipboard-paste with save/restore, keystroke fallback | Fast and reliable across all apps |
| UI | System tray + recording-indicator overlay + settings window | Daily driver lives in background; settings window avoids config-file editing |
| Language / framework | Python 3.11+ | Every chosen capability maps to a well-supported Python library; faster-whisper is Python-native with CUDA |
| UI framework | PySide6 (Qt) for tray, overlay, and settings | One consistent UI framework instead of mixing pystray + Tkinter |

## Architecture

```
Hotkey pressed → Capture mic audio → faster-whisper (GPU) transcribes
   → Rule-based cleanup → Paste into focused app (clipboard + restore)
```

### Components (each isolated, single-purpose)

| Component | Responsibility | Key library |
|-----------|---------------|-------------|
| HotkeyManager | Listen for global hotkeys; emit start/stop events for PTT (hold) and toggle (tap) | `pynput` |
| AudioRecorder | Capture mic audio to an in-memory buffer while recording | `sounddevice` |
| Transcriber | Run faster-whisper on audio, return raw text | `faster-whisper` |
| TextCleaner | Rule-based cleanup (strip fillers, capitalize, punctuation spacing) | pure Python |
| TextInserter | Insert text via clipboard-paste with save/restore, keystroke fallback | `pyperclip` + `pywin32`/`keyboard` |
| Overlay | Small recording indicator near cursor/screen edge | PySide6 |
| TrayApp | System tray icon + menu; owns the settings window | PySide6 |
| SettingsWindow | Pick hotkeys, mic, Whisper model, cleanup toggles | PySide6 |
| Config | Load/save settings to a JSON file | pure Python |
| AppController | Wires it all together; orchestrates the pipeline | pure Python |

## Data Flow & State Machine

States: **Idle → Recording → Processing → Idle**

### Push-to-talk flow (hold key)
1. User holds PTT hotkey → HotkeyManager emits `start_recording`
2. AppController: Idle→Recording, AudioRecorder starts buffering, Overlay shown
3. User releases key → HotkeyManager emits `stop_recording`
4. AppController: Recording→Processing, recorder stops, audio buffer → Transcriber
5. Transcriber returns raw text → TextCleaner cleans → TextInserter pastes into focused app
6. Overlay hides, state returns to Idle

### Toggle flow (tap key)
Identical, except tap-to-start and a second tap-to-stop instead of hold/release.

### Guards & edge cases
- Empty/too-short audio (< ~0.3s) → skip transcription, silently return to Idle
- Overlapping triggers while Recording/Processing → ignored (state machine only accepts valid transitions)
- Transcription produces empty text → nothing pasted, return to Idle
- Model still loading at startup → hotkeys queue or show a "warming up" overlay until ready

### Model lifecycle
faster-whisper model loads **once at startup** and stays resident in GPU memory. Each
dictation pays only transcription cost, not load cost. This is what makes it feel instant.

## Text Insertion (hybrid strategy)

1. Save current clipboard contents
2. Set clipboard to the cleaned text
3. Send `Ctrl+V` to the focused window
4. Wait a short beat (~150 ms, so the paste completes before restore), then restore the original clipboard
5. Fallback: if paste fails (or config forces it), type via simulated keystrokes

## Error Handling

| Failure | Handling |
|---------|----------|
| No microphone / disconnected | Tray notification "No microphone found"; stay Idle |
| CUDA/GPU unavailable at startup | Auto-fall back to CPU (int8); log warning, notify once. App still works |
| Model download missing (first run) | Download chosen model with progress indicator in overlay |
| Transcription throws | Catch, notify "Transcription failed", return to Idle — never crash |
| Clipboard locked by another app | Retry briefly; else keystroke fallback |
| Settings file corrupt/missing | Fall back to defaults, rewrite clean config |

**Guiding principle:** the tray app must **never crash**. Every pipeline error is caught,
surfaced as a brief notification, and the app returns cleanly to Idle.

**Logging:** rotating log file at `%APPDATA%/TalkativeAI/logs/`.

## Configuration

JSON file at `%APPDATA%/TalkativeAI/config.json`, editable via the Settings window:
- PTT hotkey and toggle hotkey (both rebindable). Defaults: PTT = hold `Ctrl+Space`,
  toggle = `Ctrl+Alt+Space` (both chosen to avoid clashing with common app shortcuts;
  user can rebind on first run if either conflicts)
- Microphone device selection
- Whisper model (`small` default, `medium` option) + device (`cuda`/`cpu`)
- Language (`auto` or fixed, e.g. English — faster/more accurate when fixed)
- Cleanup toggles (strip fillers, auto-capitalize, punctuation spacing)
- Insertion mode (paste / keystroke)
- Launch-on-startup toggle

## Testing Strategy

- **Unit tests (pure logic):** TextCleaner (filler removal, capitalization), Config
  (load/save/defaults/corruption recovery), state-machine transitions and guards. Primary
  TDD surface.
- **Integration tests with mocks:** pipeline wiring with fake recorder/transcriber to
  verify Idle→Recording→Processing→Idle and edge cases (empty audio, overlapping triggers).
- **Manual smoke test checklist:** real end-to-end in Notepad, a browser, and an IDE.
  Hotkeys, audio, and paste can't be meaningfully unit-tested.

## Distribution / Running

- **Day-to-day:** run from a Python virtual environment via a `.bat`/`.vbs` launcher, or
  "run on startup." Simplest, most robust for a personal daily driver.
- **Optional later:** package to a single `.exe` with PyInstaller once stable. Nice-to-have,
  not core.

**Prerequisites:** Python 3.11+, CUDA-capable PyTorch/ctranslate2 for faster-whisper (works
with the GTX 1650 SUPER), and the libraries above. First launch downloads the Whisper model
(a few hundred MB) once, then fully offline.

## Out of Scope (YAGNI for v1)

- LLM-based cleanup (tone/grammar/format adaptation)
- Transcription history UI
- Multi-language switching UI
- Cloud sync
- Single-`.exe` packaging (deferred nice-to-have)