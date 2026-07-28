# Manual Smoke Test

Hardware and UI behavior can't be unit-tested, so run through this checklist
after changes that touch audio, hotkeys, insertion, the tray, the pill, the Hub,
or packaging.

**Prereq:** quit any running instance first — the app takes a named mutex and a
second launch just logs *"Another instance is already running"* and exits. Then
start it with `run.bat` (or `.venv\Scripts\python -m rekounts`).

Wait for the tray toast **"Rekounts is running. Hold or double-tap ctrl+win
to dictate."** (First launch is slower while the speech model loads.)

## The pill

- [ ] A small dark **pill** appears at the bottom-center of the monitor your
      mouse is on. Move the mouse to another monitor → the pill follows.
- [ ] Hover it → it widens and shows **"Hold ctrl+win to dictate"**.
- [ ] Click on it → the app you were typing in **keeps focus** (the pill must
      never steal it).
- [ ] Idle CPU for the process stays near zero (nothing animates while idle).

## Dictation — the three gestures (default hotkey: Ctrl+Win)

- [ ] **Hold**: open Notepad, hold **Ctrl+Win**, say "hello world", release.
      → While held the pill expands to **✕ │ live waveform │ ✓** and the
      waveform reacts to your voice. On release it shows a brief "thinking"
      animation, then **"Hello world"** is typed into Notepad.
- [ ] **Double-tap**: tap Ctrl+Win twice quickly → recording latches on and
      stays on with your hands off the keys. Speak a sentence, then **tap once**
      → it stops and the text is inserted.
- [ ] **Lone tap while idle**: tap Ctrl+Win once → **nothing is inserted** (no
      stray "you"/"thank you" from ambient noise) and you get a hint toast.
- [ ] **✕ button**: start recording, speak, click **✕** → nothing is inserted.
- [ ] **✓ button**: start recording, speak, click **✓** → text is inserted, same
      as releasing the key.
- [ ] Repeat the hold test in a browser address bar and in a VS Code editor.
      → text inserted in both.

## Edge cases

- [ ] Tap-and-immediately-release. → nothing inserted, no error.
- [ ] Speak only "um uh". → nothing or trimmed output; no crash.
- [ ] Speak into a muted/too-quiet mic. → tray notice
      *"No speech detected — check your microphone selection/volume."*
- [ ] Stay silent through a whole recording. → the hallucination filter drops
      Whisper's "Thank you." / "Thanks for watching." phantoms; nothing typed.
- [ ] Dictate a normal sentence, then stay silent for ~20 s before stopping.
      → your sentence arrives, with no phantom outro glued onto the end.
- [ ] Dictate an outro you *mean*: "thanks for watching, talk soon" — and a
      whole YouTube sign-off, "thank you so much for watching this video, I
      hope you enjoyed it, see you in the next one." → **both arrive in full**.
      Losing real words here is worse than letting a phantom through.
- [ ] Dictate short one-liners on their own: "Thanks!", "Thank you.", "Ok
      thanks", "Bye.", "Okay." → **every one arrives**. These have no ordinary
      words around them to protect them, so they are the cases most at risk
      from an over-eager filter (and before this change, several were deleted
      outright with a misleading "check your microphone" notice).
- [ ] Turn **Ignore phantom phrases** off, stay silent through a recording.
      → the phantom is inserted; off really means off.
- [ ] **Clipboard preservation** (paste mode): copy an image or a file in
      Explorer, dictate, then paste (Ctrl+V) elsewhere → your **original**
      clipboard content comes back, not just plain text.
- [ ] **Held-modifier guard**: dictate with the Ctrl+Win hold gesture into
      Notepad → the paste must not open Windows' clipboard-history popup
      (that would mean Ctrl+V fired while Win was still down).
- [ ] **Elevated target**: focus an app running as administrator and dictate
      → tray notice explaining it was blocked, and the text still appears in the
      Hub's Dictation page.
- [ ] Click into a different window mid-dictation → text is not dumped into the
      wrong app; the entry is still saved in the Hub.

## Text insertion in Windows 11 Notepad

**This section cannot be replaced by the test suite.** The unit tests drive a
fake backend: they prove which code path was chosen, and nothing whatsoever
about whether real characters arrive intact in a real app. The bug this section
exists for was invisible to a green suite.

Use the **Windows 11 Notepad** — the rebuilt one with tabs and a formatting
toolbar (Settings → About shows an `11.x` version). An older build will pass
these whether or not the bug is present, because the defect is in the new one's
input pipeline.

- [ ] **1. Short dictation, default settings.** Dictate a sentence of well under
      100 characters into Notepad.
      → The **full sentence arrives, byte-exact**.
      The old failure: the first word landed correctly and every remaining
      character rendered as an identical dot.
- [ ] **2. The configuration that broke.** Quit the app. In
      `%APPDATA%\Rekounts\config.json` set `"insertion_mode": "keystroke"` and
      leave `"long_text_via_paste": true`. Relaunch. Dictate the same short
      sentence into Notepad.
      → Still **byte-exact** — this configuration pastes now, and that is the
      whole fix. Dots here mean the regression is back.
- [ ] **3. Literal typing still works where it has to.** Also set
      `"long_text_via_paste": false` and relaunch. Dictate a short sentence into
      an app that ignores Ctrl+V — **Windows Terminal** is the easy one.
      → The text is **typed** into the terminal. (Both keys are required; this
      is the documented escape hatch and it must not rot.)
- [ ] **4. What that costs.** With those two keys still set, dictate into
      Notepad.
      → Expect **dots or mangled text**. That is the trade the user opted into
      by hand, and seeing it here is what keeps the docs honest.
- [ ] **Put it back** — restore `"insertion_mode": "paste"` and
      `"long_text_via_paste": true` (or delete both keys) before moving on.

## Settings — instant apply, no restart

Tray → **Settings…** opens the Hub's **Settings page** (there is no separate
settings window). **There is no Save button** — every change persists and
applies on its own within a moment. Throughout this section the app must
**keep running** — no restart, no disappearing tray icon.

- [ ] **Microphone**: change it. → next dictation uses the new mic.
- [ ] **Test** button: reads "Heard you clearly" while you speak, "Silent"
      with the mic muted. **Refresh** re-scans devices after plugging one in.
- [ ] **Language** = Tagalog, speak Tagalog → Tagalog text appears.
- [ ] **Language, then dictate IMMEDIATELY** (within a second of the change)
      → the new language is used. It must not take a second dictation to
      "stick".
- [ ] **Model** = `medium` → toast "Loading model…", the app stays usable,
      then "Model ready (medium)". Dictation still works (slower, more
      accurate). Set it back to `base`.
- [ ] **Dictation hotkey**: click the box, press a new combo (e.g. Ctrl+Alt+D)
      → the new hotkey works immediately and the **old one no longer does**.
      The pill's hover hint updates. Press **Reset** to restore `Ctrl+Win`.
- [ ] Press a combo the app can't listen for → the field says so and the old
      hotkey is kept, nothing broken is saved.
- [ ] **Text cleanup** toggles: turn off "Remove filler words", dictate
      "um hello" → the "um" survives. Turn it back on.
- [ ] There is **no "Insert text by" row and no "Paste long dictations" row**
      in **Behavior** at all — they were removed, not disabled. Insertion is
      config-file-only now; the cases that exercise it are in the
      "Text insertion in Windows 11 Notepad" section above.
- [ ] **Processing**: in the INSTALLED app (and on any Mac) there is no
      Processing row in **General** at all, and nothing anywhere in Settings
      mentions CUDA — that build has no GPU stack in it, so the choice could
      only ever land on CPU. Running from source on Windows the row is there,
      and the **Auto** label reads in full inside the dropdown rather than
      being cut off mid-sentence.

## Settings — nothing deferred without saying so

The point of this section is that a change you cannot have yet is *visible*.
Run the whole thing with **Settings → System → Tray notifications OFF**, which
is the case that used to have no signal at all.

- [ ] **Model** = `medium` with notifications off → the pill grows a small
      **amber dot**, and hovering it reads *"Loading medium… dictation still
      uses <old model>."* The Settings page shows the same line under its
      title. Dictate during the load → it still works (on the old model), and
      the dot is still there on the recording pill.
- [ ] When the load finishes → the dot and both messages disappear on their
      own. Set the model back and confirm the same both ways.
- [ ] **Change the model twice quickly** (`medium`, then `base`) → the message
      names the model you picked *last*, and does not clear until that one is
      ready. It must never say "ready" for a model you already moved off.
- [ ] Turn **"Catch the first word" (pre-roll) ON**, change the
      **microphone**, then dictate immediately → the recording contains only
      audio from the NEW mic. (Easiest check: mute the new mic — you should get
      "no speech detected", not half a second of the old mic's room noise.)
- [ ] With pre-roll on, **change the microphone while a hands-free recording is
      running** → the recording in flight is not cut off, the pill shows the
      amber dot with *"New microphone starts with your next dictation."*, and
      that message clears the moment the recording ends.
- [ ] **Tray → Microphone submenu** with pre-roll on → same behaviour as
      changing it in the Hub (this path bypasses the Hub entirely).


## Settings — Audio cues

All of these live in **Settings → Audio**, under the microphone.

- [ ] **Sound effects** off → dictation start/stop cues go silent immediately
      (no restart); on → they come back.
- [ ] With sound effects **off**, the **Volume** dropdown is greyed out and says
      so, rather than looking live while changing nothing.
- [ ] With sound effects **on**, the **Volume** row has no explanation under it
      at all — the row is self-evident and used to carry a sentence about
      restarting that nobody was wondering about.
- [ ] **Volume** = Loud → dictate → the very next cue is louder. Set it to
      Soft → the next cue is quieter. No restart at any point.
- [ ] By ear: the start cue is a single short, low toot — noticeable if you
      listen for it, easy to ignore if you don't. The stop cue is the same but
      lower. Neither should make you flinch on headphones.
- [ ] The error cue (unplug the mic mid-dictation, or force a failure) is a
      two-note fall — clearly not the start or stop cue.

## Settings — System & Privacy switches

- [ ] **Show dictation pill** off → the pill disappears immediately; on → it
      comes back, in the right position.
- [ ] **Tray notifications** off → change a setting → no "Settings applied."
      toast; on → toasts return.
- [ ] **Launch at login** on → `HKCU\Software\Microsoft\Windows\
      CurrentVersion\Run` gains a `Rekounts` entry (check with `reg query`
      or Task Manager → Startup apps); off → the entry is gone.
- [ ] **Maximum recording length** = 1 min → a hands-free recording you leave
      running stops itself after a minute.
- [ ] **Save dictation history** off → dictate → **no new entries appear** in
      the Hub's Dictation page (the text is still inserted); on → entries
      return. No relaunch needed for either direction.

## Tray menu

- [ ] **Microphone** and **Language** submenus show the current selection
      checked, and switching applies without opening Settings.
- [ ] **Check for Updates** → a toast naming the latest GitHub *release*: either
      "You are on the latest release" or "Rekounts X.Y.Z is available". Offline,
      a clean "Could not reach GitHub" — it must not hang or crash.
- [ ] If it offered an update, **clicking the toast** opens that release's page
      in your browser. (To exercise this without waiting for a real release,
      temporarily lower `__version__` in a source run.)
- [ ] Settings → System → **Check for updates automatically** is **off** on a
      fresh install. Turn it on, restart the app, and confirm it stays silent
      when you are already up to date.
- [ ] **Help** → opens the project README in your browser.
- [ ] **Quit** → tray icon and pill disappear, process exits, the mic is
      released.

## Send Feedback (tray → Send Feedback…, and Settings → Data & Privacy)

- [ ] Both front doors open the **same** window, and it has **Copy**, **Save…**
      and **no Send button** anywhere.
- [ ] Read the diagnostics block line by line. It must NOT contain your Windows
      user name, your machine name, `C:\Users\<you>`, your microphone's name, or
      a single word of anything you have ever dictated.
- [ ] **Open a GitHub issue…** → your browser opens GitHub's *new issue* form,
      already filled in, and **nothing is posted**. Close the tab; no issue
      exists.
- [ ] **Email …** → your mail client opens a new message, already written, sitting
      unsent in the compose window. Close it without sending.
- [ ] Tick **Include the last 40 log lines** → the block grows, and the paths in
      those lines read `%USERPROFILE%\…`, never your real folder.
- [ ] **Copy** → paste into Notepad; you get exactly what was on screen.
      **Save…** → the file holds the same text.
- [ ] Settings → Data & Privacy → **Diagnostic log** → **Open folder** opens
      `%APPDATA%\Rekounts\logs` in Explorer.

## The Hub (tray → Open Dashboard)

- [ ] **Dictation**: your recent dictations appear newest-first, grouped by day.
      Dictate something new, reopen → it is there.
- [ ] Search box filters entries (case-insensitive, matches raw and cleaned).
- [ ] **Copy** on an entry puts its text on the clipboard; **Delete** removes
      just that entry; **Clear all** asks for confirmation, then empties it.
- [ ] **Insights**: words today / 7 days / all time, average WPM, current and
      longest streak, and a 21-day bar chart that changes after new dictations.
- [ ] **Dictionary**: add a word (with optional "sounds like"), it persists
      across restarts; delete removes it.
- [ ] Dictionary words actually bias transcription: add a name Whisper
      mishears (e.g. a product name or surname), dictate a sentence with it →
      it comes out spelled as you entered it noticeably more often. A
      "sounds like" spelling is auto-corrected after transcription.
- [ ] **Settings** in the sidebar shows the same Settings page the tray's
      **Settings…** opens.
- [ ] **Account**: set a display name, Save profile, restart → still there.

## Resilience

- [ ] Set a nonexistent mic name in `config.json`, launch → *"Saved microphone
      not found — using system default."* notice, app uses default, no crash.
- [ ] Disable the mic, try to dictate. → tray notice, no crash.
- [ ] Corrupt `config.json` (write `not json`), launch → the app rewrites it
      with defaults and starts normally.
- [ ] Launch a second copy while one is running → it exits quietly and the first
      one is unaffected.
- [ ] `%APPDATA%\Rekounts\logs\rekounts.log` ends with a
      `Rekounts started (device=..., hotkey=...)` line and no tracebacks.

## Upgrading from TalkativeAI (one-time, on the first run after the rename)

Do these on a machine — or a spare Windows user profile — that still has a real
`%APPDATA%\TalkativeAI` folder. **Back that folder up first.**

- [ ] **Fresh install, no old data.** Rename `%APPDATA%\TalkativeAI` out of the
      way, delete `%APPDATA%\Rekounts`, launch → app starts normally, no
      migration lines in the log, no `.migrated-from-talkativeai` marker.
- [ ] **The upgrade.** Restore the old folder, delete `%APPDATA%\Rekounts`,
      launch → `%APPDATA%\Rekounts` now holds your `config.json`, `history.db`,
      `logs\` and `models\`; the log has a `data-folder migration: ...
      complete=True` line; a `.migrated-from-talkativeai` marker exists.
- [ ] Your **settings survived** (hotkey, mic, model are the ones you had) and the
      Hub's **history and dictionary** show your real entries.
- [ ] **No re-download.** The model you already had is listed as installed and
      dictation works immediately. `%APPDATA%\TalkativeAI\models` is now gone
      (moved), while `config.json` and `history.db` are still there (copied).
- [ ] **Second launch does nothing.** Relaunch → no migration lines in the log.
- [ ] **Partial recovery.** Delete `.migrated-from-talkativeai` and
      `%APPDATA%\Rekounts\history.db`, launch → history.db comes back,
      `config.json` is reported skipped, and your settings are untouched.
- [ ] **Launch at login moved.** With the setting ON, check
      `HKCU\Software\Microsoft\Windows\CurrentVersion\Run` →  a `Rekounts` value
      pointing at the current build, and **no** `TalkativeAI` value.
- [ ] **Both apps at once.** Start the old TalkativeAI build, then start
      Rekounts → Rekounts shows the "TalkativeAI is still running" dialog and
      exits; the old app is unaffected. Quit the old one, start Rekounts → it
      starts normally.

## The standalone .exe

Run this after any change to `Rekounts.spec`, `requirements.txt`, or the
import order in `__main__.py` — the frozen build fails in ways the source build
never does.

```bat
build.bat
```

- [ ] The build completes without errors (a few `WARNING: Failed to collect
      submodules for 'onnxruntime.quantization'` and `sounddevice ... is not a
      package` lines are expected and harmless).
- [ ] **Quit the dev instance first** (single-instance mutex), then run
      `dist\Rekounts\Rekounts.exe`.
- [ ] The log reaches `Rekounts started (device=cpu, hotkey=ctrl+win)` with
      no traceback. (A startup crash usually means the Qt/CTranslate2 import
      order or the duplicated `msvcp140.dll` — see the spec's comments.)
- [ ] The tray icon appears (check the hidden-icons `^` flyout) and its menu has
      all nine items.
- [ ] The pill appears and follows the mouse between monitors.
- [ ] **Open Dashboard** opens the Hub and renders all five pages.
- [ ] A full dictation works: hold Ctrl+Win, speak, release → text inserted, and
      the entry shows up in the Hub. This is what proves the bundled PortAudio,
      CTranslate2, the silero VAD model and the Win32 clipboard path all made it
      into the bundle.
- [ ] Right-click `Rekounts.exe` → Properties → Details shows the version,
      company and copyright.
- [ ] `Rekounts.exe` shows the **waveform icon** in Explorer (not the generic
      one), and so does the tray icon and the Hub's title bar / taskbar button.
- [ ] Ideally, test on a **second PC with no Python installed** — unzip, run,
      click through the SmartScreen warning, and confirm the model downloads.

## The installer

`build.bat` also produces `dist\Rekounts-Setup-<version>.exe`. Most of this is
covered by an automated pass (see the PR for `feat/icon-installer-updates`), but
the wizard's own pages need eyes.

- [ ] Running Setup shows **no UAC prompt** at any point.
- [ ] The wizard shows the **GPL-3.0 licence**, then an **install folder** page
      defaulting to `%LOCALAPPDATA%\Programs\Rekounts`, then the two optional
      tasks (desktop shortcut, start at sign-in) — both **unticked**.
- [ ] The wizard's header shows the Rekounts mark, and `Setup.exe` itself shows
      the icon in Explorer.
- [ ] Finish with **Launch Rekounts** ticked → the app starts.
- [ ] The Start Menu entry works, and **Settings → Apps** lists *Rekounts* with
      the right version and publisher.
- [ ] If you ticked "start at sign-in", **Settings → System → Launch at login**
      inside the app reads **ON**. Turn it off there and the registry value goes
      away — one switch, two front doors.
- [ ] Re-run Setup **while Rekounts is running** → it asks you to close the app
      rather than failing or corrupting the install.
- [ ] Re-run Setup with it closed → installs over the top, and your dictation
      history and settings are still there afterwards.
- [ ] Uninstall from **Settings → Apps**. The dialog offering to delete your
      data appears with the box **unticked**; leave it unticked and confirm
      `%APPDATA%\Rekounts` still exists afterwards, program gone.

## CPU vs GPU notes

- Transcription runs on **CPU** by default (`"device": "cpu"`). A modern CPU
  handles the `base` model in about a second per sentence.
- GPU (CUDA) is **off by default**: loading a model without the matching cuDNN
  runtime crashes CTranslate2. To try it, install the cuDNN runtime for your
  CUDA version and set `"device": "cuda"` in `config.json`. Revert to `"cpu"`
  if it crashes on launch.
