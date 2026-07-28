# macOS manual test plan

The macOS port is **code-complete**. Nothing in it has ever run on a physical
Mac: as of v0.4.0 this file has **0 boxes ticked**.

What CI does and does not prove, precisely, because the old wording here
overstated it:

* The `pytest-posix` / `macos-latest` leg installs `requirements-test.txt`,
  which contains **no pyobjc**. It exercises the mac port's *policy* against
  fakes and has never executed a real Quartz or AppKit call.
* The `pytest-macos-runtime` leg (added alongside this checklist) installs the
  full `requirements.txt` and does execute the real frameworks: the imports
  resolve, every CoreGraphics symbol the port names exists, the TCC probes
  answer, a real `NSPasteboard` round-trips through backup/restore, and real
  `CGEvent`s are built for Cmd+V and for unicode typing.
* **No CI leg can grant a TCC permission.** Everything downstream of consent —
  whether a posted event is actually delivered, whether the key-state poll tells
  the truth, whether an NSPanel stays on screen — needs this checklist.

So the honest split is: the *shape* of the mac code is tested, its *behaviour
under macOS's permission model* is unknown. This file is that unknown, written
down. For a human with one hour rather than three, do
[docs/macos-one-hour.md](docs/macos-one-hour.md) instead — it is the same
material ordered by likelihood of failure.

Requirements: a real Mac (Apple Silicon or Intel), macOS 12+.

Estimated time: ~75 minutes for everything below.

**Please record passes as well as failures.** "Confirmed working on hardware" is
currently a list of zero items, and a ticked box is as useful as a bug report.

## 0. Setup (from source)

```sh
git clone <repo> && cd rekounts
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python -m pytest -q          # expect: all green, 0 failures
python launch.py             # or: python -m rekounts
```

First launch downloads the Whisper model to
`~/Library/Application Support/Rekounts/models/` — ~486 MB for the default
`small`, or ~148 MB if you switch to `base` first. (Sizes are the manifest's own
in `rekounts/models.py`; this file used to say 75 MB, which was never right.)

Never done this before, or handing it to someone who hasn't?
[docs/macos-quickstart.md](docs/macos-quickstart.md) is the same setup written
out step by step.

> **Terminal note:** when running from source, macOS attributes permissions to
> the TERMINAL (Terminal.app/iTerm), not to "Rekounts". Grant the prompts to
> your terminal — you will look for "Rekounts" in the Input Monitoring and
> Accessibility lists and it will not be there. Note that this widens what
> *anything* you later run from that terminal may do, so prefer a terminal you
> do not use all day. After granting, **quit and reopen the terminal**: macOS
> only re-reads a grant at process start. The packaged .app gets its own
> identity and its own three grants.
>
> The app now says this itself: from source the permission toasts tell you to
> enable your terminal and warn that "Rekounts" will not be in the list, and
> only the packaged .app is told to look for Rekounts
> (`rekounts/permissions.py`). So a toast naming Rekounts during a from-source
> run is a bug, not the instruction to follow.

## 1. Permissions onboarding  ⬜

Fresh machine (or `tccutil reset All` equivalents on a test account):

- [ ] Launch. Expect tray toasts naming any missing permission with the exact
      System Settings pane (Input Monitoring / Accessibility) — NOT a silent
      dead app. (`rekounts/permissions.py`.) Running from source, each toast
      must name **your terminal**, not Rekounts, and end "start Rekounts
      again"; from the packaged .app it names Rekounts and ends "quit and
      reopen Rekounts".
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

      > **The gate is weaker than it reads.** Measured on the GitHub
      > `macos-latest` (arm64) runner, 2026-07-25:
      > `CGPreflightListenEventAccess()` returns **True** with nobody having
      > granted anything. So a passing preflight is *not* evidence that the poll
      > can be believed, and this check is not ruled out by the gate — it is the
      > reason this section is still first. (Recorded in
      > `tests/test_macos_native.py::test_the_hotkey_watchdog_gate_is_derived_from_the_real_preflight`.)
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
- [ ] Dictate ü/é/emoji → they arrive intact.
- [ ] Focus a different app during transcription → toast "No text field was
      focused", nothing pasted into the wrong app. KNOWN LIMIT: focus tracking
      is per-APP on macOS (frontmost pid), not per-window — switching windows
      within the same app won't abort.

### 3b. Keystroke mode, which is config-file-only now  ⬜

**This section changed.** It used to be about a >100-character escalation, and
about two Settings rows. Both rows are gone, and `_KEYSTROKE_SAFE_CHARS` is 0,
so keystroke mode delivers *everything* through the clipboard unless
`long_text_via_paste` is also turned off. See rekounts/text_inserter.py for the
Windows-side measurement that forced this.

There is no UI for any of it. Quit the app, edit
`~/Library/Application Support/Rekounts/config.json`, relaunch.

macOS is the harder case for the literal-typing branch: Windows can post a whole
chunk of characters in one atomic `SendInput`, while Quartz posts events one at a
time (`_MacBackend.type_unicode`), so typing has strictly more exposure here.

**Set `"insertion_mode": "keystroke"` for all of these.**

- [ ] `"long_text_via_paste": true` (the default), dictate ~200 words into
      TextEdit → the whole thing arrives at once, like a paste, not typed letter
      by letter. Log should show `keystroke mode: delivering N chars via the
      clipboard`.
- [ ] **Same settings, a SHORT dictation (a dozen words).** → It must ALSO
      arrive at once. This is the Windows bug ported to the Mac checklist: short
      text used to be typed here, and that is what corrupted it on Windows 11.
      Letter-by-letter appearance means the regression is back.
- [ ] Same, with an image on the clipboard first → after the dictation, ⌘V still
      pastes your image. (The delivery borrows the clipboard; this is the
      give-it-back path, on a real NSPasteboard.)
- [ ] Copy some text DURING the transcription pause → your copy survives
      (restore skipped via `changeCount`).
- [ ] Now also set `"long_text_via_paste": false` and relaunch. Dictate ~200
      words → it is literally typed. Record honestly: did every character
      arrive? How long did it take? This is the configuration that exists for
      apps which ignore ⌘V, and it is the least-protected path in the app.
- [ ] With the escalation still off, dictate a long passage containing emoji and
      accents (`é ü 😀`). `_MAC_UNICODE_CHUNK` is 20 **UTF-16 units**, and an
      emoji counts as two — a chunking bug shows up as a mangled or missing
      character near a boundary, not as an error.
- [ ] Is there a macOS equivalent of the Windows 11 Notepad failure? With typing
      forced on, dictate a short sentence into a **SwiftUI or Catalyst** app
      (Freeform, Shortcuts, System Settings' search field) as well as into
      TextEdit. Windows' rebuilt-in-a-new-UI-toolkit app was the one that broke;
      nobody has checked whether macOS has the same class of victim. **Unknown,
      not "fine" — record what you actually see.**
- [ ] While a clipboard delivery happens, keep holding the hotkey chord → no
      stray Ctrl+Cmd+V side effect in the target app.
- [ ] **Put it back** — restore `"insertion_mode": "paste"` and
      `"long_text_via_paste": true`, or delete both keys.

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

## 5. Delivery notices — one per cause  ⬜

Also new in v0.4.0. When a dictation does not reach the cursor, the notice now
names the actual cause instead of always saying "no text field was focused". The
wording table is `_UNDELIVERED_MESSAGES` in rekounts/text_inserter.py, shared
with the controller so the two cannot drift. Every one of these outcomes reaches
the user through a tray toast, and the transcript is always in History.

The mac-specific point: two of the five outcomes behave differently here, and
one of them is a genuine UX hole that this session should confirm exists.

- [ ] **NO_TARGET via focus change.** Start a dictation in TextEdit, switch to
      another app while it transcribes → toast "No text field was focused — the
      transcript is in History, ready to copy." Then check the Hub's Dictation
      page has it.
- [ ] **NO_TARGET with nothing focused.** Click the Desktop (Finder frontmost, no
      text field) and dictate. EXPECTED, and worth confirming rather than
      assuming: you get **no** notice, because `_MacBackend.is_no_target` can
      only detect "no frontmost application at all", which barely happens
      interactively. The paste is attempted and goes nowhere quietly. Record what
      actually happened — if this is as described, it is a known gap, not a
      surprise, and the fix would be an AX-based check that costs a permission.
- [ ] **BLOCKED is unreachable on macOS.** There is no UIPI equivalent, so
      `is_blocked` always returns False and the "Can't type into an admin window"
      wording must never appear. If you ever see it on a Mac, that is a bug.
- [ ] **INTERRUPTED.** Needs BOTH `"insertion_mode": "keystroke"` and
      `"long_text_via_paste": false` in config.json (§3b) — with either one
      missing, the text is pasted and this case cannot be reached at all.
      Long-ish text: press and hold ⌘ or Option part-way through the typing →
      delivery stops and the toast
      says "Typing stopped part-way — a key was still held down. Part of it is
      already in the field; the whole transcript is in History." Check that the
      partial text really is in the field (the wording promises it, and a user
      who is told nothing landed would paste a duplicate on top).
- [ ] **The silent-denial case — the important one.** Revoke **Accessibility**
      from your terminal (System Settings, untick it), relaunch, and dictate into
      TextEdit. `CGEventPost` does not fail when consent is missing, it is
      dropped by the window server, so the app believes it pasted: expect **no
      text, no failure notice**, and the dictation recorded in History as
      delivered. The startup permission toast (§1) is the only thing standing
      between a user and a mysteriously dead app. Confirm that toast does appear
      in this state — that is the whole mitigation.
- [ ] Toasts respect **Settings → System → Tray notifications**: switch it off
      and repeat one of the above → no toast, and the transcript is still in
      History.

## 6. The Scratchpad  ⬜

**The item most likely to be broken, and the one nobody has thought about.** The
Scratchpad is new in v0.4.0, is pure Qt with **zero platform branches**, and was
written before macOS was in scope.

Why it is at risk specifically here: dictation is routed into the note only when
`Scratchpad.wants_dictation()` is true, and that requires
`enabled and shown and self._active`, where `_active` mirrors
`isActiveWindow()`. The pad is a `Qt.Window | Qt.FramelessWindowHint` with
`WA_TranslucentBackground`. On macOS a borderless `NSWindow` does not become the
key window by default (Qt overrides this, but it has never been checked here),
and an app running under the **accessory / LSUIElement** activation policy —
which `Rekounts-macos.spec` sets, `"LSUIElement": True` — has extra restrictions
on activating itself.

If `_active` never becomes true, the failure is not a crash. Dictation silently
goes to the *ordinary* insertion path while the pad is on screen and apparently
focused, so the text lands somewhere else or nowhere. That is what to watch for.

Note the from-source asymmetry: **a `python -m rekounts` run has no bundle and
therefore no `LSUIElement`**, so it runs as a normal app with a Dock icon and the
activation rules are the *easy* ones. A pass here does NOT predict a pass in the
packaged app — so re-run the starred items after §8 if you build one.

Enable it first: **Settings → System → Scratchpad** on, then menu bar →
**Open Scratchpad**.

- [ ] The note appears at all: a dark rounded sheet with a drop shadow, no title
      bar, a formatting strip along the bottom. `WA_TranslucentBackground` plus a
      hand-painted shadow is exactly the combination that can come out as an
      opaque black rectangle on macOS — say which you got.
- [ ] ★ Click into the note and type on the keyboard → characters appear. (If
      not, the window is not becoming key and everything below fails with it.)
- [ ] ★ **The routing rule.** With the note focused, dictate → the text lands in
      the NOTE, and your clipboard is untouched. This is the single most
      important check in this section.
- [ ] ★ Click into TextEdit, leaving the note visible, and dictate → the text
      goes to TextEdit, not the note.
- [ ] Dictate into the note twice in a row → both dictations land, appended, in
      whatever formatting the caret was already in.
- [ ] Formatting works from the strip: bold, italic, underline, strikethrough,
      bullets — and dictated text arrives as plain text taking the caret's
      current formatting.
- [ ] Drag the note by any empty part of it; resize it from each edge and corner.
      There is no native frame doing this, so it is all app code.
- [ ] Close and minimize fade in when the pointer is over the note and fade out
      when it leaves (macOS enter/leave events on a frameless translucent
      window).
- [ ] Minimize → the note goes away and comes back sensibly. On macOS a
      borderless window has no miniaturize button of its own; record what
      actually happens.
- [ ] Close the note → it hides, and reopening from the menu bar brings back the
      same text. Closing must never delete anything.
- [ ] Quit Rekounts entirely and relaunch → text, size and position are all
      restored, from
      `~/Library/Application Support/Rekounts/scratchpad.json`.
- [ ] Move the note to a second display or another Space, quit, relaunch → it
      comes back somewhere visible (not off-screen).
- [ ] With the note focused and a dictation running, the pill is still visible
      and shows the recording state (§4 and this section interacting).
- [ ] Turn **Settings → System → Scratchpad** off → an open note hides and the
      menu-bar entry disappears; turn it back on → the entry returns and the note
      still has your text.
- [ ] Privacy check: the note's text is written verbatim to `scratchpad.json` in
      plain text. Confirm the file contains what you dictated — users should know
      this, and it is what docs/privacy.md has to describe.

## 7. Swaps  ⬜

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

## 8. Packaging groundwork  ⬜

Do this LAST. It is the only section that can be skipped without leaving a
question unanswered, because the from-source app is what the README tells people
to run.

```sh
pip install pyinstaller
python -m PyInstaller --clean Rekounts-macos.spec
open dist/Rekounts.app
```

- [ ] Builds at all. PyInstaller has never been run against this spec; if it
      fails, the error is more valuable than the rest of this section.
- [ ] App launches; **NO Dock icon** (LSUIElement); menu-bar icon present.
- [ ] The menu-bar icon is the Rekounts waveform mark, and the app's icon in
      Finder / the force-quit panel is too — `assets/icon.icns` is committed and
      wired into `BUNDLE(icon=...)`, but has never been rendered by macOS.
- [ ] Mic prompt shows the `NSMicrophoneUsageDescription` text (the sentence
      about audio never leaving the Mac), and the app is not killed on first mic
      open.
- [ ] The bundle asks for its OWN three permissions, listed as **Rekounts** and
      not as your terminal. This is the payoff of packaging.
- [ ] ★ **Re-run the starred Scratchpad checks in §6 here.** The bundle sets
      `LSUIElement`, which the from-source run does not, so the pad's ability to
      become the active window is a genuinely different question in the packaged
      app. If it works from source and not here, that is the finding.
- [ ] Re-run §4 (the pill) here too, for the same reason.
- [ ] Gatekeeper: expect "cannot be opened because the developer cannot be
      verified" on first launch, needing right-click → Open. That is correct for
      an unsigned build, not a bug.
- [ ] Signing/notarization NOT expected to work (unsigned). That procedure is
      docs/macos-packaging.md, needs the owner's Apple Developer account
      ($99/yr), and is deliberately out of scope here. `packaging/entitlements.plist`
      is written but has never been through `codesign`.

## Reporting

For anything that fails: macOS version, chip (Intel/Apple Silicon), keyboard
layout, whether you ran from source or from the `.app`, the step, and
`~/Library/Application Support/Rekounts/logs/rekounts.log`.

The questions that genuinely need hardware, most-likely-to-fail first:

1. **§6 ★** — can the Scratchpad become the active window, and does dictation
   route into it? Zero platform branches, written without macOS in mind.
2. **§2 long-hold** — does `CGEventSourceKeyState` tell the truth under TCC, or
   does a push-to-talk hold self-release?
3. **§4** — does the pill stay visible while another app is frontmost, and does
   the `REKOUNTS_MAC_OVERLAY_NATIVE=0` kill switch change the answer?
4. **§5 silent-denial** — with Accessibility revoked, is the startup toast really
   the only thing telling the user why nothing happens?
5. **§3b** — does literal keystroke typing of a long passage survive on macOS,
   where events are posted one at a time? And the new one: does macOS have its
   own version of the Windows 11 Notepad failure — a SwiftUI/Catalyst app that
   renders synthesized characters as placeholder glyphs? On Windows that was
   the whole reason keystroke mode left the UI. Nobody has looked on a Mac.

An hour is enough for 1–4 in that order: see
[docs/macos-one-hour.md](docs/macos-one-hour.md).
