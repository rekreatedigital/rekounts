# macOS manual test plan

The macOS port is **code-complete and unit-tested with fakes** (the
`macos-latest` CI leg runs every mac code path), but several behaviors can
only be proven on real hardware: TCC permission flows, CGEvent posting, and
the overlay pill's NSPanel behavior. This checklist is for a human with a real
Mac (Apple Silicon or Intel, macOS 12+).

Estimated time: ~45 minutes.

## 0. Setup (from source)

```sh
git clone <repo> && cd rekounts
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python -m pytest -q          # expect: all green, 0 failures
python launch.py             # or: python -m rekounts
```

First launch downloads the Whisper model (~75 MB for `base`) to
`~/Library/Application Support/Rekounts/models/`.

> **Terminal note:** when running from source, macOS attributes permissions to
> the TERMINAL (Terminal.app/iTerm), not to "Rekounts". Grant the prompts to
> your terminal. The packaged .app gets its own identity.

## 1. Permissions onboarding  ⬜

Fresh machine (or `tccutil reset All` equivalents on a test account):

- [ ] Launch. Expect tray toasts naming any missing permission with the exact
      System Settings pane (Input Monitoring / Accessibility) — NOT a silent
      dead app. (`rekounts/permissions.py`; toast text ends "quit and reopen".)
- [ ] Grant **Input Monitoring**, relaunch: hotkey toast gone.
- [ ] Grant **Accessibility**, relaunch: paste toast gone.
- [ ] First dictation triggers the **Microphone** system prompt (that prompt
      is the intended onboarding; we do not pre-toast an undetermined mic).
- [ ] Deny the mic, relaunch: a mic toast now appears (denied ≠ undetermined).

## 2. Hotkey gestures  ⬜

Default hotkey is `ctrl+win` = **Ctrl+Cmd** on the Mac keyboard.

- [ ] Hold Ctrl+Cmd, speak, release → text pastes into the focused app.
- [ ] Hold for >30 s → no premature stop at ~0.3 s. **If a recording
      self-stops almost immediately**, the watchdog's key-state poll is lying:
      capture `~/Library/Application Support/Rekounts/logs/rekounts.log` and
      look for "healing a stuck combo" lines (this is the
      `CGEventSourceKeyState`-under-TCC question; see `_key_state_poll` in
      rekounts/hotkey_manager.py — the gate should prevent this by disabling
      the watchdog when preflight fails, so seeing it means the gate passed
      but polling still lies; report it).
- [ ] Double-tap Ctrl+Cmd → hands-free latch; single tap stops it.
- [ ] Lone tap while idle → hint toast, nothing pasted.
- [ ] Change the hotkey to `F8` in Settings and repeat hold/tap. Also try a
      letter hotkey (e.g. `cmd+9`) — letters/digits exercise the
      `_DARWIN_CHAR_VK` keycode table (ANSI/US layouts only; a non-US layout
      may not match — note what keyboard layout you tested).

## 3. Text insertion  ⬜

- [ ] Paste lands in: TextEdit, Safari address bar, VS Code, Slack.
- [ ] Clipboard restore: copy an image (screenshot), dictate, paste ⌘V again
      manually → the image is still on the clipboard.
- [ ] Copy something DURING the transcription pause → after insert, your new
      copy is still there (restore skipped via changeCount).
- [ ] While holding the Ctrl+Cmd hotkey through the paste: no stray
      Ctrl+Cmd+V side effects (modifier wait).
- [ ] Dictate ü/é/emoji → they arrive intact (keystroke mode).
- [ ] Focus a different app during transcription → toast "No text field in
      focus", nothing pasted into the wrong app. KNOWN LIMIT: focus tracking
      is per-APP on macOS (frontmost pid), not per-window — switching windows
      within the same app won't abort.

## 4. Overlay pill (the riskiest port item)  ⬜

The pill must stay visible while OTHER apps are active — that is its whole
job. Qt.Tool windows hide on app deactivate on macOS; we counter with
WA_MacAlwaysShowToolWindow + native NSPanel tweaks
(`rekounts/ui/overlay.py::_apply_mac_panel_behavior`, default ON).

- [ ] Idle pill visible at bottom-center while ANY other app is frontmost.
- [ ] Still visible while dictating into TextEdit (recording oblong, waveform).
- [ ] Follows the mouse across monitors / Spaces (CanJoinAllSpaces).
- [ ] Visible over a FULL-SCREEN app (FullScreenAuxiliary).
- [ ] Clicking ✕/✓ on the pill does NOT steal focus from the target app
      (non-activating panel) — the insertion must still land in the target.
- [ ] Kill switch: `REKOUNTS_MAC_OVERLAY_NATIVE=0 python launch.py` → app
      still runs; note whether the pill now hides when deactivated (expected:
      it may — that is what the native tweaks fix; Qt's
      WA_MacAlwaysShowToolWindow alone may or may not suffice — please record
      which).

## 5. Swaps  ⬜

- [ ] Sounds: start/stop cues audible (afplay), soft not harsh; toggle off in
      Settings silences them immediately.
- [ ] Launch at login ON → `~/Library/LaunchAgents/com.rekreatedigital.rekounts.plist`
      exists (RunAtLoad, correct interpreter + launch.py paths); log out/in →
      app is running. Toggle OFF → file gone.
- [ ] Single instance: launch twice → second exits quietly (flock on
      `~/Library/Application Support/Rekounts/.rekounts.lock`).
- [ ] Data location: everything under `~/Library/Application Support/Rekounts/`.
      Pre-seed `~/Rekounts/` (old fallback) with a config.json → first launch
      migrates it across (marker `.migrated-from-talkativeai` appears).

## 6. Packaging groundwork  ⬜

```sh
pip install pyinstaller
python -m PyInstaller --clean Rekounts-macos.spec
open dist/Rekounts.app
```

- [ ] Builds; app launches; NO Dock icon (LSUIElement); tray icon present.
- [ ] Mic prompt shows the NSMicrophoneUsageDescription text.
- [ ] Signing/notarization NOT expected to work (unsigned) — that procedure
      is docs/macos-packaging.md and needs the owner's Apple account.

## Reporting

For anything that fails: macOS version, chip (Intel/AS), keyboard layout, the
step, and `~/Library/Application Support/Rekounts/logs/rekounts.log`. The two
open questions that genuinely need hardware answers are **§2 long-hold**
(CGEventSourceKeyState under TCC) and **§4** (pill visibility + kill-switch
comparison).
