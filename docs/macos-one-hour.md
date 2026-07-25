# One hour on a Mac

Rekounts' macOS port is code-complete and has never run on a physical Mac.
[MACOS-TESTING.md](../MACOS-TESTING.md) is the full 63-box checklist and takes
about 75 minutes of actual testing. **This file is what to do if you have one
borrowed hour**, ordered so that the hour answers the questions most likely to
have a bad answer.

Everything a Windows box can settle has already been settled: the wording, the
CI leg that installs the real pyobjc frameworks and executes the mac code paths,
the `.icns`, the entitlements, the packaging procedure. What is left needs macOS
to *grant a permission* and then *actually deliver an event* — and no CI runner
can do either.

## The four questions, and why this order

Ordered by probability of failure × cost of finding out late. Not by section
number.

| # | Question | Why it is first / at risk |
| --- | --- | --- |
| **1** | Does the **global hotkey survive a long hold**? | The watchdog reads physical key state via `CGEventSourceKeyState`. If that lies about held keys under macOS's permission model, every push-to-talk hold self-releases ~0.3 s in and the app is unusable for its actual purpose. A gate is meant to prevent that by disabling the watchdog until the Input Monitoring preflight passes — **and CI has now measured that preflight returning `True` on a runner nobody granted anything on** (see below), so the gate is not the protection it reads as. |
| **2** | Does the **pill stay visible** when another app is frontmost? | That is its entire job — you are always dictating *into something else*. macOS hides tool windows on app deactivate. Three layers of countermeasure, none ever observed working. |
| **3** | Can the **Scratchpad take focus and receive dictation**? | New in v0.4.0, pure Qt, **zero platform branches**, written before macOS was in scope. Routing depends on `isActiveWindow()` for a frameless translucent window. Fails silently, not loudly. |
| **4** | With **Accessibility revoked**, is the startup toast the only warning? | `CGEventPost` does not fail when consent is missing — it is dropped. The app believes it pasted. If the toast does not appear, a user's first experience is an app that does nothing and says nothing. |

If you can only answer one, answer **1**. A dictation app whose push-to-talk
cannot be held has nothing else worth testing.

### What CI already measured, and why it makes Q1 worse

The `pytest-macos-runtime` leg runs the real frameworks on a GitHub
`macos-latest` (arm64) runner. Two results from its first run, 2026-07-25:

* **The whole runtime dependency set installs cleanly on Apple Silicon** in
  about 23 seconds — PySide6 6.7.2, ctranslate2 4.8.1, onnxruntime 1.27.0,
  av 12.3.0 and the four pyobjc frameworks at 11.1 on pyobjc-core 12.2.1. That
  was previously an open question with a plausible "no". It is settled.
* **`CGPreflightListenEventAccess()` returned `True`** with nobody having
  granted anything. `_key_state_poll` treats a passing preflight as licence to
  enable the watchdog, on the reasoning that a preflight only passes once the
  user has consented. At least one real environment breaks that reasoning, so
  the gate does not rule out the self-releasing-hold failure. **Hence Q1 first.**

Two smaller notes from the same install, for whoever picks up packaging:

* `requirements.txt` pins `faster-whisper==1.0.3` but leaves its native stack to
  resolve freely (`ctranslate2<5,>=4.0`, `onnxruntime<2,>=1.14`). CI got 4.8.1
  and 1.27.0; a Mac two weeks from now may not.
* The onnxruntime wheel CI resolved is tagged **`macosx_14_0_arm64`** — macOS 14
  or newer — while `Rekounts-macos.spec` declares
  `LSMinimumSystemVersion: 12.0`. pip will backtrack to an older onnxruntime on
  macOS 12–13, so those users get a version nothing has tested. If you are on
  macOS 12 or 13, say so in your report; that alone is a useful data point.

## Before the hour starts

Do this while doing something else — it is mostly downloads, and it is a waste
of borrowed Mac time.

```sh
git clone https://github.com/rekreatedigital/rekounts.git && cd rekounts
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt          # ~800 MB
python -m pytest -q                      # expect green; if not, stop and report
```

([macos-quickstart.md](macos-quickstart.md) is the unhurried version of the same
setup, if the Mac's owner is doing this part rather than you.)

Then two setup choices that buy back minutes:

* **Use a terminal you do not otherwise use.** Running from source grants Input
  Monitoring and Accessibility to the *terminal*, and everything you later run
  from it inherits them. Terminal.app while you normally live in iTerm, say.
* **Set the model to `base` before the first launch** — edit
  `~/Library/Application Support/Rekounts/config.json` after the first run, or
  just accept one `small` download (~486 MB). `base` is ~148 MB, a third of the
  wait. (Both figures are the manifest's own in `rekounts/models.py`; this line
  used to say 75 MB for `base`, which was never right.) Accuracy is not what
  this hour is testing.

Grant the two permissions up front, because each one costs a relaunch:

1. Launch once: `python -m rekounts`. Expect toasts naming the missing consents.
2. System Settings → Privacy & Security → **Input Monitoring** → add/tick your
   terminal. Same again under **Accessibility**.
3. **Quit and reopen the terminal**, then relaunch Rekounts. macOS re-reads
   grants only at process start.
4. Dictate once into TextEdit to trigger the microphone prompt; allow it.

You now have a working app, or you have already found something worth reporting.

## The hour

Keep the log open in a second window the whole time — it is the primary evidence
for every one of these:

```sh
tail -f ~/Library/Application\ Support/Rekounts/logs/rekounts.log
```

### 0:00–0:12 — Q1, the long hold  (MACOS-TESTING.md §2)

1. Hold **Ctrl+Cmd**, speak a sentence, release. Text should arrive in TextEdit.
2. Hold **Ctrl+Cmd for a full 30 seconds**, talking. This is the test.
   * **Pass:** it records the whole time and inserts on release.
   * **Fail:** the recording stops on its own after roughly a third of a second.
     Grep the log for `healing a stuck combo`. Seeing that means the trust gate
     passed but `CGEventSourceKeyState` is still lying — report it with the log
     lines, it is the single most valuable finding available today. Note that CI
     has already shown the gate is willing to open without a real grant, so this
     is not a remote possibility.
3. **Double-tap** Ctrl+Cmd → hands-free latch; **single tap** stops it.
4. Change the hotkey to **F8** in Settings and repeat the 30-second hold. F8 is
   layout-independent, so if F8 holds and Ctrl+Cmd does not, the problem is the
   modifier keycodes, not the poll.
5. Note your **keyboard layout** — the letter/digit keycode table assumes
   ANSI/US.

### 0:12–0:22 — Q2, the pill  (§4)

The pill lives at bottom-centre of whichever display has the pointer.

1. Click into TextEdit so Rekounts is *not* frontmost. **Is the pill still
   visible?** That is the question.
2. Dictate and watch it: it should expand to ✕ │ waveform │ ✓ and stay on screen
   throughout, while TextEdit has focus.
3. Click **✓** on the pill → the recording finishes and the text still lands in
   **TextEdit**, i.e. clicking the pill did not steal focus.
4. Move the pointer to a second display (if there is one) → the pill follows.
5. Full-screen an app (e.g. Safari) → the pill is still visible over it.
6. Now the comparison that tells us what to ship:
   ```sh
   REKOUNTS_MAC_OVERLAY_NATIVE=0 python -m rekounts
   ```
   Repeat step 1. **Record whether the pill now hides on deactivate.** If it
   hides with the flag off and stays with it on, the native NSPanel tweaks are
   doing real work and should stay default-on. If it stays visible either way,
   Qt's `WA_MacAlwaysShowToolWindow` alone is sufficient and the pyobjc layer can
   be deleted — that is a code-simplification decision waiting on this one
   observation.

### 0:22–0:40 — Q3, the Scratchpad  (§6)

Enable it: **Settings → System → Scratchpad**, then menu bar → **Open
Scratchpad**.

1. **Does it render as a sticky note** — dark rounded sheet, soft shadow, no
   title bar, formatting strip at the bottom? Or as an opaque black rectangle?
   (`WA_TranslucentBackground` plus a hand-painted shadow is exactly the
   combination that can go wrong on macOS.) A screenshot here is worth more than
   a description.
2. **Click into the note and type.** If characters do not appear, the window is
   not becoming key and steps 3–4 will fail with it — say so and move on, that is
   the finding.
3. **The one that matters: dictate with the note focused.** The text must land in
   the NOTE, not in the app you were in before.
   * **Fail mode to watch for:** it is *not* a crash. If `isActiveWindow()` never
     becomes true, dictation quietly takes the ordinary insertion path — the text
     goes somewhere else, or nowhere, while the note sits there looking focused.
   * Check your clipboard afterwards: routing into the note must not touch it.
4. Click into TextEdit, leaving the note visible, and dictate → text goes to
   **TextEdit**. Both halves of the rule have to hold.
5. Drag the note by an empty part of it; resize it from an edge. No native frame
   is doing this.
6. Quit Rekounts, relaunch, reopen the note → same text, same size, same place.

### 0:40–0:50 — Q4, the silent denial  (§5)

1. System Settings → Privacy & Security → **Accessibility** → **untick** your
   terminal. Quit and reopen the terminal, relaunch Rekounts.
2. **Does a startup toast appear** naming Accessibility and telling you where to
   grant it? Screenshot it.
3. Dictate into TextEdit anyway. Expected: **nothing arrives, and no error**.
   Confirm the transcript is in the Hub's Dictation page. This is the app's
   worst-case UX and step 2's toast is its only mitigation — if that toast is
   missing, that is a shipping blocker, not a polish item.
4. Re-tick Accessibility, relaunch, confirm the toast is gone and pasting works
   again.

### 0:50–1:00 — the cheap wins

Small, fast, and each one turns an inference into a fact:

- [ ] Dictate into **Safari's address bar**, **VS Code** and **Slack** — one
      sentence each. Different text systems, all common targets.
- [ ] Copy an image (⇧⌘4 to the clipboard), dictate, then ⌘V manually → your
      image is still there. Proves the real NSPasteboard backup/restore.
- [ ] Settings → Behavior → **Insert text by: Type keystrokes**, dictate ~200
      words → it should arrive *all at once* (the >100-char clipboard escalation),
      not letter by letter.
- [ ] Dictate `é ü 😀` → they arrive intact.
- [ ] **Launch at login** on → check
      `~/Library/LaunchAgents/com.rekreatedigital.rekounts.plist` exists; off →
      it is gone.
- [ ] Start-and-stop cues are audible and soft (`afplay`), and switching sound
      effects off silences them immediately.

## What NOT to spend the hour on

* **Building the `.app`.** PyInstaller is a long build and the README points Mac
  users at running from source. It is §8 of the checklist, and it is also the one
  thing where a second hour is genuinely needed — the bundle sets `LSUIElement`,
  which changes the Scratchpad and pill questions all over again.
* **Signing or notarizing anything.** Needs the owner's Apple Developer account
  ($99/yr) — [macos-packaging.md](macos-packaging.md).
* **Accuracy, models, the GPU.** Transcription quality is platform-independent,
  and there is no GPU path on a Mac at all (the speech engine is CUDA-only).
* **Anything the CI leg already covers** — the pyobjc imports resolving, the
  CoreGraphics symbols existing, the permission probes answering. Those are
  green; do not re-derive them by hand.

## Reporting

For each of Q1–Q4, one line: **pass**, **fail**, or **did not get to it**. Then
for anything that failed:

* macOS version and chip (Intel / Apple Silicon)
* keyboard layout
* from source or from the `.app`
* the step number here or the box in MACOS-TESTING.md
* `~/Library/Application Support/Rekounts/logs/rekounts.log`
* screenshots for anything visual — the pill and the Scratchpad especially,
  since nobody on this project has seen either of them on a Mac

**Tick the boxes that passed, too.** As of v0.4.0, MACOS-TESTING.md has 63
unchecked boxes and zero checked ones. Half of the value of this hour is turning
some of those zeros into ones, so that the next person knows what not to re-test.
