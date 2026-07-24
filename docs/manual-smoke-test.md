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
- [ ] **Insert text by** = keystrokes, dictate → text is typed
      character-by-character and your clipboard is untouched.

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
- [ ] Turn **"Catch the first syllable" (pre-roll) ON**, change the
      **microphone**, then dictate immediately → the recording contains only
      audio from the NEW mic. (Easiest check: mute the new mic — you should get
      "no speech detected", not half a second of the old mic's room noise.)
- [ ] With pre-roll on, **change the microphone while a hands-free recording is
      running** → the recording in flight is not cut off, the pill shows the
      amber dot with *"New microphone starts with your next dictation."*, and
      that message clears the moment the recording ends.
- [ ] **Tray → Microphone submenu** with pre-roll on → same behaviour as
      changing it in the Hub (this path bypasses the Hub entirely).

## Settings — System & Privacy switches

- [ ] **Show dictation pill** off → the pill disappears immediately; on → it
      comes back, in the right position.
- [ ] **Sound effects** off → dictation start/stop cues go silent; on → back.
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

## Upgrading from TalkativeAI (one-time, v0.3.0 only)

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

## Live typing (experimental, OFF by default)

Types words as you speak instead of once on release. It is **off by default and
known to be unreliable** (Whisper rewrites earlier words as the buffer grows,
causing doubled/garbled text). Only test it if you deliberately enable it.

- [ ] Settings → turn on **Live typing** (applies immediately). Switch the
      hotkey to a non-modifier key like **F8** first — holding Ctrl/Win while
      it types would fire shortcuts. Hold, speak → words appear in groups while
      speaking; the tail completes on release.
- [ ] Turn **Live typing** off → words appear only on release (cleaned).
      The streaming loop must actually stop — no double-typing.

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
      all seven items.
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
