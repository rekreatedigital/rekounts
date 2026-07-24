# Changelog

All notable changes to Rekounts, newest first. Written for the people who
*use* the app, not just the people who write it.

The version string lives in one place — `rekounts/__init__.py` — and
everything else (`pyproject.toml`, the `.exe` file properties) reads it from
there.

## [0.3.0] — 2026-07-24

The first public release.

### macOS: the port is written, pending real-hardware verification

All platform seams now have macOS implementations — pasting via native
events, clipboard preservation, launch-at-login as a LaunchAgent, data in
`~/Library/Application Support/Rekounts`, permission checks with plain
guidance when macOS hasn't granted mic/input access yet — plus packaging
groundwork for a menu-bar `.app`. It is unit-tested and CI-green on macOS
runners, but nobody has run it on a physical Mac yet: that checklist lives
in `MACOS-TESTING.md`, and no macOS download ships until it passes.

### There is a real installer now

Download `Rekounts-Setup-<version>.exe` from the releases page and run it.

- **No administrator rights and no UAC prompt.** It installs for your account
  only, into `%LOCALAPPDATA%\Programs\Rekounts`, and shows up in
  **Settings → Apps** with a proper uninstaller.
- You get the **GPL-3.0 licence** to read, a choice of install folder, a Start
  Menu shortcut, and two optional boxes: a desktop shortcut, and starting
  Rekounts when you sign in. That last one is the *same* switch as
  Settings → System → Launch at login, not a second competing one — flip it in
  either place and both agree.
- **Upgrading** is just running the newer installer. It asks you to close
  Rekounts if it is running, keeps your existing install folder, and remembers
  whether you had launch-at-login on.
- **Uninstalling leaves your data alone.** Your settings, dictation history and
  downloaded speech model live in `%APPDATA%\Rekounts` and are *not* touched —
  the uninstaller offers a clearly-labelled checkbox if you do want them gone,
  and it starts unticked.

The **portable ZIP** is still there and still supported — unzip it anywhere and
run `Rekounts.exe`. Nothing about it changed; it is simply no longer the only
option.

### An actual icon

Rekounts has its official icon: the monochrome waveform mark from the website,
now on the `.exe` in Explorer, the taskbar, the Start Menu, the app's windows,
the installer, and the system tray. Previously the tray drew its own microphone
glyph in code and the `.exe` had no icon at all.

### Check for Updates now checks releases

- It compares the version you are running against the newest **release** on
  GitHub, instead of reporting the latest commit on `master` — a commit hash
  told you nothing about whether you were out of date. It now says plainly
  whether there is something newer, and **clicking the notification opens the
  release page**.
- New **Check for updates automatically** switch (Settings → System), **off by
  default**. With it on, Rekounts makes that one request about ten seconds after
  each launch and stays completely silent unless there is genuinely a newer
  release. It still downloads and installs nothing on its own.

The privacy page has been updated to match — see
[docs/privacy.md](docs/privacy.md) for exactly what that request contains.

### The app is now called Rekounts

**TalkativeAI was a placeholder. The app's real name is Rekounts.** The window,
the tray icon, the notifications and the `.exe` all say Rekounts now.

**You do not have to do anything.** The first time you start this version it
moves your existing data over for you:

- Your **settings**, **dictation history** and **custom dictionary** come across
  from `%APPDATA%\TalkativeAI` to `%APPDATA%\Rekounts`.
- Your **downloaded speech models** move too, so nothing is re-downloaded.
- **Launch at login** keeps working — the old Windows startup entry is replaced
  with the new one. (Without this you would quietly end up with the old app
  starting alongside the new one at every login.)

Two things worth knowing:

- **Quit the old app first if it is still running.** Both versions listen for the
  same dictation hotkey, so they would fight over it. If TalkativeAI is still in
  your system tray when you start Rekounts, Rekounts tells you and stops; quit
  the old one from its tray menu and start Rekounts again.
- **Your old folder is left alone.** `%APPDATA%\TalkativeAI` is copied, not
  emptied, so you can go back to the old version if you need to. Once you are
  happy with Rekounts you can delete that folder yourself — nothing uses it. (The
  `models` folder inside it is the one exception: it is *moved*, because copying
  several gigabytes of speech models could fill your disk.)

If a file cannot be moved on the first try — something had it open, for example —
the app starts anyway and finishes the job on the next launch. It never
overwrites data already in the new folder.

### Privacy & speech models
- **The app no longer contacts Hugging Face — at all.** Speech models are now
  downloaded from this project's own release host. Previously the first launch
  (and every model change) fetched the model from `huggingface.co`; that
  dependency is gone entirely, first run included.
- **Models live in the app's own folder**, `%APPDATA%\Rekounts\models\<name>\`,
  instead of the shared `%USERPROFILE%\.cache\huggingface` cache. Delete a folder
  to reclaim the space.
- **Already downloaded a model with another tool?** If a matching copy is in your
  Hugging Face cache, it is copied across on first run and **nothing is
  downloaded**. Your cache is left untouched.
- **Every downloaded file is SHA256-verified** against a hash recorded in the
  app's source before it is used, so a corrupted or tampered file is rejected
  rather than run. Interrupted downloads **resume** instead of starting over, and
  a model is only marked installed once all of its files pass.
- Downloads report progress — in the log while the app is starting, and as a
  notification when you switch models from Settings.
- Model sizes are now stated up front: `base` ~148 MB, `small` ~486 MB,
  `medium` ~1.5 GB.
- Attribution and license notices for the redistributed models are in
  [docs/model-license.md](docs/model-license.md); `scripts/publish_models.py` is
  the maintainer tool that fetches, verifies and publishes them.

## [0.2.0] — 2026-07-23 (internal milestone, never published)

The "daily driver" release: one hotkey that behaves the way your hands expect,
settings that apply the moment you save them, and a local Hub that remembers
everything you have dictated.

### Dictation & hotkeys
- **One hotkey, three gestures.** The old two-hotkey setup (hold `F8`, toggle
  `Ctrl+Alt+Space`) is replaced by a single **`Ctrl+Win`** hotkey:
  **hold** to talk, **double-tap** to go hands-free, **tap again** to stop.
  A lone tap while idle does nothing except remind you how it works.
- Existing configs are migrated automatically: if you customized the old
  push-to-talk key it is kept, otherwise you move to the new `Ctrl+Win` default.
- The hotkey capture box in Settings now records the combo you actually press
  and rejects combos it cannot listen for, instead of saving something broken.
- Releasing an unrelated key can no longer cut a push-to-talk hold short.
- **The hotkey no longer goes dead mid-session.** Opening the microphone used to
  happen on the same thread Windows uses to deliver key presses; if it ran slow,
  Windows would quietly drop our keyboard hook and the hotkey stopped working
  until you restarted the app. All of that work now runs off that thread, so the
  hook stays responsive.
- **Self-healing hotkey.** If the keyboard hook is ever lost anyway, it is now
  detected and rebuilt automatically within a second or two — no restart — and a
  dropped key-up that used to leave the hotkey "stuck" now recovers on its own.
- Stopping a recording with the overlay ✓ (or the auto-stop safety cap) no longer
  swallows your next hotkey press — the next press starts a fresh recording.
- Changing any setting while you are recording no longer strands that recording:
  the hotkey keeps working, and it still stops the clip you are in the middle of.

### Settings
- **Settings apply the instant you change them — no Save button, no restart.**
  Nothing is lost, no window flicker, no race with the single-instance lock.
  Hotkey, language, cleanup toggles, insertion mode and microphone take effect
  at once; switching the speech model reloads it in the background and tells you
  when it is ready.
- Every option that used to be config-file-only now has a control in Settings:
  pre-roll, maximum recording length, the phantom-phrase filter, launch at
  login, sound effects, the pill, tray notifications and dictation history.
  Only a few tuning knobs (`beam_size`, `stream_model`, `preroll_seconds`)
  remain `config.json`-only — `device` grew a **Processing** row in Settings
  (CPU / Auto-GPU).
- Microphone and Language can also be switched straight from the tray menu.
- The Model list now offers `base`, `small` and `medium`. Previously a `base`
  user was silently rewritten to `small` on save.
- **Every switch now does exactly what it says.** The pre-roll buffer applies
  the moment you toggle it (no more waiting for a restart). The speech-model
  selector is greyed out with a note while Live typing is on, because live
  typing uses the faster streaming model and the choice would be ignored. The
  "Tray notifications" switch now silences *every* toast — including the mic,
  language and update-check messages that used to slip past it.
- **Launch at login** is honest about Windows' Task Manager. If you disable
  Rekounts in the Startup tab, the switch now shows OFF (Windows really is
  skipping it) instead of a misleading ON, and turning it back on clears that
  disable so it actually starts again.

### The Hub (dashboard) — new
- **Open Dashboard** in the tray menu opens a local, monochrome Hub with:
  **Dictation** (searchable history of everything you have dictated, grouped by
  day, copy or delete individual entries, or clear everything),
  **Insights** (words today / this week / all time, average words-per-minute,
  current and longest daily streak, and a 21-day bar chart),
  **Dictionary** (teach it names and jargon — words bias the recognizer, and
  "sounds like" mishearings are auto-corrected), **Settings** (a full page in
  the Hub — see below), and
  **Account** (a display name and avatar, stored locally and shown in the
  sidebar; there is no sign-in).
- The Hub now updates live: a dictation that finishes while you are looking at
  the Dictation or Insights page shows up at once, instead of only after you
  switch pages.
- History is kept in a SQLite file next to your config
  (`%APPDATA%\Rekounts\history.db`). Turn **Save dictation history** off in
  Settings → Data & Privacy and nothing is ever written — it applies to the
  very next dictation, no restart.

### The pill (on-screen indicator) — redesigned
- The old colorful overlay is replaced by a small monochrome capsule at the
  bottom of whichever monitor your mouse is on. Idle it is barely there; hover
  it and it tells you the hotkey; while recording it expands into
  **✕ cancel │ live waveform │ ✓ finish**; after release it shows a brief
  "thinking" animation.
- **Fades when idle.** When you are not using it the pill drops to a low opacity
  so it is a faint hint, not a fixture; hovering it (or starting to record)
  brings it fully back so the text stays readable.
- **Sits on the taskbar.** It now rests just above the taskbar instead of
  floating ~100 px above it — lower and out of the way, and correct whether your
  taskbar auto-hides or is docked to a side.
- It never steals focus, and it only animates while recording or processing, so
  it costs nothing when idle.
- Turn **Show dictation pill** off in Settings → System to hide it entirely —
  it disappears (and comes back) immediately.

### Audio cues
- The start / stop / error cues are now soft, low-volume **sine** tones rendered
  in memory, instead of the fixed-volume square-wave beeps Windows' `Beep` makes
  (which have no volume control and always sound harsh). Still stdlib-only —
  nothing bundled, nothing downloaded.
- The **start cue is a single minimal note** — present but easy to stop noticing,
  "nothing fancy". Stop and error stay two-note shapes so the three remain easy
  to tell apart by ear.
- Turn them off with the Hub's **Sound effects** switch (or `"sound_effects":
  false`). Where no audio backend is available they silently do nothing.

### Accuracy & reliability
- **Pre-roll** (optional, off by default) keeps a short rolling buffer so your
  first syllable is not clipped. Off by default because it holds the microphone
  open, which keeps the Windows "mic in use" indicator lit.
- **Hallucination filter** drops Whisper's classic silence artefacts
  ("Thank you.", "Thanks for watching.") — but only when that is the *entire*
  result, so a real sentence starting with those words is untouched.
- **Safety cap**: a hands-free recording you forget to stop ends automatically
  (default 10 minutes, configurable in Settings) instead of freezing on a huge
  transcription — and now warns you about 30 seconds before it fires. Changing
  the limit mid-recording reschedules the running timer, so the countdown and
  the "reached the … limit" message always agree.
- Beam size raised to 5 — noticeably more accurate for a small CPU cost.
- Repeated-word collapsing ("the the" → "the") added to the cleanup options.
- The model is warmed up in the background at launch, so your first dictation is
  as fast as the rest.

### Text insertion
- Clipboard preservation now uses the native Windows clipboard and keeps
  **every** format you had copied — images, files, HTML — not just plain text.
- Your clipboard is only restored if it still holds our text, so anything you
  copied in the meantime is never clobbered.
- Before pasting, the app waits for you to actually let go of the hotkey, so a
  held `Ctrl+Win` can no longer turn `Ctrl+V` into `Ctrl+Win+V`.
- If the focused window is running as administrator, or focus moved away
  mid-dictation, you now get an honest notice instead of text silently vanishing.

### Packaging, docs & housekeeping
- **Standalone `.exe`** (`build.bat`) verified end-to-end on a real machine:
  it launches, shows the tray icon and pill, opens the Hub, and completes a full
  record → transcribe cycle with no Python installed. The `.exe` now carries
  proper version/company details in its file properties.
- **Launch at login** is a switch in Settings → System. It writes a per-user
  registry entry, repairs the path if the app folder moves, and respects a
  disable made in Task Manager's Startup tab instead of silently overriding it.
- **Check for Updates** and **Help** in the tray menu.
- Licensed **GPL-3.0**.
- New [privacy page](docs/privacy.md) spelling out exactly what is stored, where,
  and the three click-or-first-run moments the app can touch the network.
- CI installs a minimal test dependency set instead of the full ~805 MB runtime
  stack, and now runs a lint pass. Same test suite, roughly a quarter of the
  install time.
- The unit suite now also runs on Linux and macOS in CI. The app itself is
  still Windows-only — the tests fake the Windows pieces — but keeping them
  green off-Windows protects the seam a future macOS port will use, and
  `pip install -r requirements.txt` no longer fails on other platforms
  (`pywin32` is marked Windows-only).
- Public-repo furniture: README screenshots of the pill, issue and pull-request
  templates, a security policy, and a code of conduct. The early design
  documents moved to `docs/archive/` with an honest "historical" warning.

## [0.1.0]

The first working version: hold `F8` to dictate, tap `Ctrl+Alt+Space` to toggle,
local faster-whisper transcription, rule-based cleanup (fillers, capitalization,
punctuation spacing), paste-or-keystroke insertion, a tray icon, a settings
window with a microphone test, an on-screen level meter, and Auto/English/Tagalog
language selection.
