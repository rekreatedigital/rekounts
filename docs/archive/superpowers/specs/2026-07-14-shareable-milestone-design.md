> **Historical document** — an original design/plan kept for the record. It no longer matches the shipped app (see [docs/archive/README.md](../../README.md) for what changed). Do not use it as documentation.

# TalkativeAI — "Shareable" Milestone Design

**Date:** 2026-07-14
**Status:** Approved design, ready for implementation planning
**Prereq:** builds on the v1 dictation app (see 2026-07-14-talkativeai-dictation-design.md)

## Goal

Make TalkativeAI safe to share with friends via a GitHub repo: a friend can clone,
run, pick their own microphone and hotkey through the UI (no JSON editing), confirm
their mic works, and see live feedback while speaking.

## Scope

Five changes:

1. **Mic stored by name, not index** — portable across machines and reboots.
2. **Auto-restart on Save** — mic/hotkey/model changes always take effect.
3. **Test-microphone button** in Settings — records ~2s, classifies the level.
4. **Live preview in the overlay** — running transcript while speaking; final clean
   text still typed on release (display-only preview, unchanged final accuracy).
5. **Language picker (Auto / English / Tagalog)** — expose Whisper's multilingual
   support in Settings so the user picks their spoken language.

Plus friend-facing packaging: a `setup.bat` and a rewritten quickstart README.

### Out of scope
- True streaming transcription into the target app (separate future milestone).
- LLM cleanup / grammar rewriting (decided unnecessary — Whisper output is coherent).
- Proper-noun replacement dictionary (paused; separate next feature).
- Installer / single .exe (chose GitHub-repo distribution instead).

## Portability Blockers Found (analysis)

| # | Blocker | Impact on a friend |
|---|---------|--------------------|
| 1 | Mic saved by device **index** (`microphone: 3`) | Index is meaningless/wrong on another PC and can shuffle across reboots |
| 2 | Mic/hotkey changes need a **manual restart** to apply | Friend changes mic, sees no effect, gives up |
| 3 | Hotkey is a raw text field with a strict format | Typo → silently broken |
| 4 | No pre-flight mic feedback | "Nothing types" with no idea why |

## Design

### 1. Mic by name

- Config `microphone` becomes a **device name string** (or `null` = system default).
- `AudioRecorder` resolves the saved name → matching input-capable device at startup.
  - Not found (different hardware) → fall back to system default, fire a notice
    "Saved microphone not found, using default." Never crash.
  - Name matches multiple host-API entries → pick the first input-capable match
    deterministically (avoids the earlier "Multiple input devices found" error).
- Settings mic dropdown stores the **name** as the item value instead of the index.
- `null` remains the friend-safe default (system default input device).

### 2. Auto-restart on Save

- On Save: write config, show "Restarting to apply settings…" tray notice, spawn a
  fresh process (`sys.executable -m talkativeai`), then quit the current one.
- The ~5s model reload happens once; new settings are then live.
- If spawning the new process fails → notify "Restart failed, please relaunch
  manually" and keep the current process alive (never leave the user with nothing).

### 3. Test-microphone button

- A **"Test"** button beside the mic dropdown in Settings.
- Records ~2s from the **currently selected** dropdown mic (not the saved one), applies
  the pipeline's auto-gain, measures level, shows an inline result:
  - "✓ Heard you clearly" — good signal
  - "⚠ Very quiet — boosted, may still work" — low but usable (e.g. ME6S)
  - "✗ Silent — wrong mic or muted" — near-zero (e.g. a virtual device)
- Runs on a worker thread; button shows "Listening…" during the 2s.
- Disabled while a dictation is active (and dictation ignored while testing).

### 4. Live overlay preview

- While recording, a background thread every ~1.5s transcribes the audio captured
  **so far** and updates the overlay text with the latest guess.
- Overlay wraps/grows to show the most recent words.
- **Display-only:** preview text is discarded on release. The final text delivered to
  the target app is still the single clean transcription of the full clip — accuracy
  unchanged.
- Preview uses the fast path (`beam_size=1`, no VAD) and is capped to one in-flight
  preview at a time; if CPU can't keep up it simply updates less often. Never blocks or
  delays the final result.
- Honest caveat: Whisper isn't a streaming model and this runs on CPU, so the preview
  updates in ~1–2s bursts, not word-by-word. Good enough for "I can see it working."

### 5. Language picker (Auto / English / Tagalog)

- Whisper is already multilingual; this only exposes it. Config `language` already
  exists and flows into `Transcriber` (`None` = auto-detect, else a language code).
- Settings `language` dropdown offers three labeled options mapped to codes:
  - "Auto-detect" → `"auto"` (Transcriber passes `language=None`; Whisper detects per
    utterance, handling mixed Taglish reasonably)
  - "English" → `"en"`
  - "Tagalog" → `"tl"`
- The dropdown shows human labels but stores the code; on open it selects the item
  matching the saved code (defaults to the first option if the saved code is unknown).
- Applied on the next start — covered by the auto-restart-on-Save flow (change #2).
- **Honest caveat (documented in README + a Settings note):** on the `small` model,
  Whisper's Tagalog is noticeably weaker than English and mixed Taglish is hit-or-miss.
  It works, but expect more errors; the `medium` model improves accuracy at the cost of
  slower CPU transcription.

## Error Handling (all new paths fail safe)

- Saved mic name absent → system default + notice. No crash.
- Test-mic during active dictation → button disabled; dictation during test → ignored.
- Auto-restart spawn fails → notice, old process stays alive.
- Live-preview transcription errors → caught and ignored (best-effort).

## Testing

- **Unit (TDD):**
  - Mic name→device resolution: found / not-found→default / ambiguous→first match.
  - Test-button level classification: loud / quiet / silent thresholds.
  - Language label↔code mapping: "Auto-detect"↔`auto`, "English"↔`en`, "Tagalog"↔`tl`;
    unknown saved code → first option.
- **Regression:** existing 26 tests stay green.
- **Manual smoke additions:** pick mic by name persists across restart; Test button on
  good/quiet/muted mic; overlay shows live words; change hotkey → Save → auto-restart →
  new hotkey works; pick Tagalog, speak Tagalog → Tagalog text out.

## Friend-facing packaging

- **`setup.bat`:** create venv, install `requirements.txt` — so a friend runs one file.
  (Documents the machine-specific `python3.exe` / venv caveat; falls back to `python`.)
- **README rewrite** — top-of-file "For my friends" quickstart:
  1. Install Python 3.11+.
  2. Clone repo, run `setup.bat`.
  3. Run `run.bat`.
  4. First launch downloads the model once (~500MB).
  5. Tray → Settings → pick mic (use **Test**), set hotkey, Save (auto-restarts).
  6. Hold hotkey, talk, release.
  - Plus **Troubleshooting**: nothing types → Test mic; hotkey conflict → change it.