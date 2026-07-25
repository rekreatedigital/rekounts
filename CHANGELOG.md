# Changelog

All notable changes to Rekounts, newest first. Written for the people who
*use* the app, not just the people who write it.

The version string lives in one place — `rekounts/__init__.py` — and
everything else (`pyproject.toml`, the `.exe` file properties) reads it from
there.

## [0.4.1] — 2026-07-25

### Fixed: Settings now says only what is true for the person reading it

Settings had a **Processing** row offering "Auto — use the GPU when it actually
works", and telling you Auto "needs the CUDA libraries — see the README". If
you downloaded Rekounts, that was never true for you. The installed app is
built without any GPU support in it on purpose — smaller download, nothing to
go wrong — so Auto has always quietly meant CPU there, and the row was sending
people off to install graphics libraries the app could not have used. On a Mac
it was doubly untrue: the speech engine has no Mac GPU support at all.

The row is now shown only where the choice can actually change something:
running from source, on Windows or Linux. Everywhere else it is gone, rather
than sitting there labelled honestly and doing nothing. Nothing about your
settings file changes — a `device` you set by hand is still read and still
obeyed.

That same row was also cut off mid-sentence in the dropdown ("Auto — use the
GPU when it actually"). Every option in every dropdown is now checked against
the real width of the control, so a label can't quietly lose its ending again.

A few other lines were written for the person who built the app rather than
the person using it, and have gone or been rewritten:

- **Volume** (was "Cue volume") no longer says "Applies to the next cue — no
  restart." Nobody choosing between Soft and Loud was worried about a restart.
- **Catch the first word** is what the pre-roll buffer is called now. It is
  what the setting does; "pre-roll buffer" was the name in the source code.
- **Save dictation history** talks about your dictations, not about
  `history.db`.
- The **speech model** and **update check** rows dropped a clause each that
  described the machinery instead of the outcome.

The warnings that carry a real consequence are untouched — the pre-roll's
"never written to disk", "never your transcripts" on the log, "Rekounts sends
nothing itself", and both delete confirmations.

### Fixed: macOS told you to enable an app that isn't in the list

Running Rekounts from source on a Mac, a missing permission produced "Enable
Rekounts under System Settings > Privacy & Security > Input Monitoring". macOS
grants those permissions to the app that *launched* Rekounts — your terminal —
so "Rekounts" is not in that list and cannot be added, and the reasonable
conclusion is that the app is broken. It isn't.

From source, the message now tells you to enable your terminal and warns
outright that Rekounts will not appear in the list. The installed .app keeps
the old wording, which was right for it all along.

### Fixed: phantom YouTube outros no longer reach your transcript

Whisper was trained on a lot of YouTube captions, and when it hears silence or
room tone it sometimes writes the thing those videos all end with. One of these
landed in a real dictation:

> "Thank you so much for watching this video, I hope you enjoyed it, see you in
> the next one."

Nobody said it. The app already had a filter for this and it missed, for two
reasons. It compared the transcript against a fixed list of exact phrases, and
that sentence is three caption clauses glued together — no single list entry
matched it. And it only ever looked at the *whole* recording, so a phantom
stuck onto the end of a genuine dictation could not be caught at all, which is
exactly what happened.

Both are fixed. The filter now recognises the caption *family* rather than a
fixed list, and it reads the speech model's own confidence that a stretch of
audio contained no speech — a number the app had been throwing away. A phantom
tail is removed from the end of your dictation without touching the real words
in front of it.

The important half of this is what it does **not** do. Your words are never
removed on a hunch. Nothing is deleted unless **both** of these are true: the
model itself reports it heard no speech there, **and** the text is caption
boilerplate in every clause. So "thanks for watching, talk soon" arrives
intact, and if you dictate an actual YouTube outro on purpose, all of it
arrives — measured, the same sentence spoken for real scores about 150× more
speech-like than the hallucinated one. Turning **Ignore phantom phrases** off
in Settings still turns off all of it.

### Fixed: short dictations like "Thanks!" are no longer swallowed

This one was already shipped, and it was the same root cause. If your whole
dictation was a short pleasantry — "Thanks!", "Thank you.", "Ok thanks",
"Bye.", "Thank you very much." — the app deleted it and told you to check your
microphone. It was matching those words against a list without ever asking
whether you had actually said them.

Now it asks. Every one of those arrives, because the model reports it clearly
heard speech; the identical words over silence still get dropped. Same for
"Okay." on its own, "Thanks, bye.", "Thanks for listening.", "That's it for
today." and "Thank you for joining us." — all real dictation, all delivered.

### Fixed: scrolling the Settings page no longer changes your settings

The Settings page is taller than the window, so you have to scroll it to read
it. If the mouse pointer happened to be resting on a dropdown while you
scrolled — and it usually is, because the dropdowns sit in the middle of the
page — the wheel changed *that setting* instead of scrolling. The page didn't
move, so there was nothing to see; and because settings apply the moment they
change, the new value was already saved and running.

That could quietly switch your speech model, your microphone, your language,
how text is inserted, or your Processing device while you were simply reading.
One scroll over **Maximum recording length** could even end a dictation you
were in the middle of.

- **The wheel now scrolls the page, always.** It never changes a control's
  value, even one you have just clicked on. Click a dropdown, or use the arrow
  keys, to change a setting — the only ways that mean you meant it.
- **Changing the recording limit can no longer cut off a recording in
  progress.** If you set a limit shorter than what you have already recorded,
  you get 30 seconds and a heads-up to finish your sentence, instead of the
  recording stopping the instant you saved the setting.

If your settings look different from how you remember leaving them, this is
why. Worth a quick look down the page — **Processing** especially.

### Added: Send Feedback — with nothing on the other end

You can now tell the developer that something broke, from the tray menu
(**Send Feedback…**) or from Settings → **Data & Privacy**.

There is still no server, and there never will be. The window that opens shows
you a short diagnostics block — app version, Windows version, Python version,
whether this is the installed build, and four settings (model, processing,
insertion mode, language) — and then offers two ways to send it, because not
everyone has a GitHub account:

- a **prefilled GitHub issue**, which is public, searchable, and gets replies; or
- a **prefilled email**, which needs no account at all.

Either one opens in your own browser or mail client **already written and not
yet sent**. You read it, change it, delete anything you would rather keep, and
send it yourself. Rekounts transmits nothing: the window has **Copy** and
**Save**, and deliberately no Send button.

Never included: your transcripts, your Scratchpad, your Dictionary, your
history, your microphone's name, your Windows user name, your machine name, or
your home-folder path. There is an optional tickbox to attach the last few log
lines; those are capped, and paths in them are rewritten to `%USERPROFILE%\…`
before you see them.

- Settings → **Data & Privacy** also gained a **Diagnostic log → Open folder**
  shortcut, so "can you send me your log?" no longer means being talked through
  `%APPDATA%`.
- The privacy page, `SECURITY.md` and the note at the bottom of Settings still
  count **two** network moments — Send Feedback adds none. It joins Help and
  update notifications in the hand-off list: pages your browser or mail client
  opens, already written and not yet sent.

### Fixed: when something goes wrong, the log now says so

If the app misbehaved, `logs\rekounts.log` could be completely empty — which
made every problem report a guessing game.

- **Crashes are written down.** A failure inside the app's own event handling,
  or on one of its background threads, used to leave no trace at all: with no
  console window there was nowhere for the message to go. Both now land in
  `rekounts.log`, with the full detail. A crash deep enough to take the whole
  program down gets its own `logs\rekounts-crash.log`.
- **The log no longer silently throws lines away.** If your microphone's name,
  or your Windows username, contained a character outside your machine's
  default character set — anything non-Latin, and plenty of accented Latin —
  the affected line was not written at all, with no warning. Everything is
  written now.

### Fixed: a fragment of a dictation could reach the log

If one of your Dictionary corrections matched a word the speech model had
spelled with an unusual character, a few words of your transcript could be
written into `rekounts.log`. The log is documented as never holding your
transcripts, so this was a broken promise rather than a preference — it is
fixed at the cause, and those corrections now apply properly instead of being
skipped.

### Changed: the Scratchpad is now in the privacy documentation, and clearable

The Scratchpad saves your note automatically as you type, which
[docs/privacy.md](docs/privacy.md) had never mentioned — and the note is *not*
covered by **Save dictation history** or by deleting your history.

- The privacy page now describes the note, where it is kept, and exactly what
  the history switch does and does not cover.
- New: **Settings → Data & Privacy → Clear note**, which asks first and then
  empties the note and its file.
- The note still survives turning the Scratchpad feature off. Turning a feature
  off is not a request to delete what you wrote — clearing it is a separate,
  deliberate action.

### Fixed: three different answers to "how often does this app use the internet?"

The Settings page said twice, the privacy page said three times, and the
security policy said two. The answer is **twice** — the one-time speech-model
download and the update check. Opening a page in your web browser (**Help**, or
clicking an update notification) is your browser's request, not the app's, and
is now described separately instead of being counted as a third. All three
places are now generated from, or checked against, one list in the source.

### macOS: runnable from source, and honest about what is unverified

The README said there was no macOS version. There has been one since 0.3.x —
running from source — so it now says so, along with exactly how far it goes.
Still **no macOS download**: an unverified app that silently does nothing
because a permission was never granted is worse than no app.

- New **[Running on macOS](README.md#running-on-macos)** section: setup, the
  three permissions macOS requires and where each one lives, the known limits,
  and the unknowns spelled out as unknowns.
- The catch nobody expects, now prominent: running from source, macOS grants the
  permissions to your **terminal**, not to Rekounts. You will look for
  "Rekounts" in the Input Monitoring list and it will not be there.
- **The Hub no longer tells Mac users about Windows.** Six explanations named
  Windows out loud and were shown verbatim on macOS — the microphone default,
  the long-dictation paste (which sends Cmd+V on a Mac, not Ctrl+V), the
  pre-roll mic indicator, launch at login, the GPU row (there is no GPU path on
  a Mac at all), and the dictation pill, which announced `CTRL+WIN` for a chord
  the Mac keyboard calls Ctrl+Cmd.
- Nothing changes for Windows users: every Windows string is byte-for-byte what
  0.4.0 shipped, and there is a test that fails if that stops being true.

Under the hood, for anyone thinking about picking this up: CI now has a leg that
installs the real mac dependency set and executes the mac code paths instead of
faking them, `assets/icon.icns` and `packaging/entitlements.plist` are written,
and [docs/macos-one-hour.md](docs/macos-one-hour.md) is the ordered list of what
to check first on a borrowed Mac.

## [0.4.0] — 2026-07-25 (built, never published — superseded by 0.4.1 the same day)

### Fixed: long dictations no longer arrive scrambled

Dictating a long passage with **Insert as → keystrokes** could deliver the
first few words correctly and then degrade into garbage, or lose most of the
text outright. The longer the dictation, the worse it got.

The cause was that keystrokes were sent one character at a time, which turned
a 200-word transcript into a stream of thousands of separate injections
spread over *seconds*. Anything you did during those seconds — re-pressing the
dictation hotkey, or switching to another app — landed in the middle of the
message and destroyed the rest of it. Switching apps mid-delivery was the
worst case: most of the transcript vanished from where you wanted it and the
rest was typed into whatever you had just opened.

- **Long text is now handed over in a single operation**, so it either arrives
  complete and correct or does not arrive at all. It can no longer be
  half-delivered, interleaved with your typing, or split across two apps.
- **Short text is still typed as real keystrokes**, where the clipboard is
  better left alone.
- **The transcript goes wherever your cursor is when dictation ends.** Start
  talking in one app, wander through others while you speak, finish with a
  different text box focused — the whole transcript lands in that text box.
- **Nothing is ever lost, and your clipboard is never taken.** If there is no
  text field to deliver into, that is a perfectly normal outcome: the app says
  so and the transcript is waiting in History on the dashboard, ready to copy.
  Whatever *you* had copied stays where it was.
- **If a key is still held down**, typing now stops rather than pushing the
  rest of the message through a modified keyboard and mangling it. The notice
  tells you part of it already landed in the field, so you don't paste a
  duplicate on top of it.
- **The notices say what actually happened.** An admin window, a held key and
  an empty desktop used to produce the same "no text field was focused"
  message; each now gets its own.
- New setting, **Behavior → Paste long dictations** (on by default). It only
  applies in keystroke mode. Turn it off if your app ignores Ctrl+V and you
  would rather have a long dictation typed literally.
- Emoji and other non-BMP characters are no longer at risk of arriving
  half-formed.

One honest limitation: Windows gives no way to tell whether an app actually
accepted a paste. If yours silently ignores Ctrl+V, a long dictation in
keystroke mode will be reported as delivered when it was not — it is still in
History, and turning **Paste long dictations** off avoids the situation
entirely.

### Removed: Live typing

Live typing (typing words as you spoke, rather than once at the end) is gone.
It was experimental, off by default, and never reliable — Whisper re-reads the
whole recording each time and rewrites earlier words, so the text churned and
doubled as you talked. It is also the wrong shape for what Rekounts is for:
speaking a thought for five, fifteen, sixty minutes and getting clean text at
the end.

Removing it also removes the **Live typing** switch and the streaming model it
forced on everything (the reason the model selector greyed itself out). Your
chosen speech model now always applies. Nothing else changes for anyone who had
it off, which is everyone by default. It is preserved in the project history and
may return properly one day.

### Settings apply instantly, and anything that can't says so

Changing the language or microphone and dictating straight away could give you
a dictation that ran on the settings you had just replaced.

- **Language and beam size are now read at the moment you dictate**, not copied
  into the speech engine when you change them. Nothing can leave them stale —
  not the fraction of a second the Hub waits to batch up changes, and not a
  model reload running in the background.
- **A language change made while a model was loading used to be thrown away**
  when that model finished — permanently, with nothing to tell you and nothing
  to undo it. That's gone.
- **Changing your microphone no longer leaks the old one into your next
  dictation.** With "catch the first syllable" turned on, the mic is held open
  continuously, and the half-second of already-captured audio that opens your
  next dictation came from the microphone you had just switched away from.
- **Switching between settings no longer pushes the apply further away.** The
  Hub batches rapid changes into one apply; it was restarting that wait every
  time you touched something, so working down the page kept deferring it.

Two things genuinely can't be instant: loading a different speech model takes
a few seconds (measured at ~3s for Small and ~6s for Medium), and a microphone
change can't be applied to a recording already in progress. Dictation keeps
working through both — that part was already true and hasn't changed. What's
new is that **you can now see it**: the pill shows an amber dot and says what
is still catching up, and the Settings page says so too. Previously the only
sign was a tray notification, so with notifications turned off a model reload
was completely invisible — you'd dictate, get the old model's output, and have
nothing on screen to explain why.

### The start/stop cues are much quieter — and easy to switch off

The cues that shipped in 0.3.0 were too loud and too noticeable. They are now
a **toot**: shorter, lower, and about **half as loud**.

- **Lower, not just quieter.** The old cues sat at 660–880 Hz, right where the
  ear is most sensitive, so they cut through everything. The new ones sit at
  350–470 Hz and are softer on top of that. They do not go lower still on
  purpose: laptop speakers roll off below ~400 Hz, and a cue you cannot hear on
  a laptop is not an improvement.
- **Start and stop are each a single note now**, told apart by pitch — the stop
  tone is lower, which reads as "done" without a second note. The error cue
  keeps its two-note fall, because that one *should* be unmistakable.
- **New: Cue volume** — Soft / Normal / Loud, in Settings → Audio. Takes effect
  on the very next cue, no restart. Even **Loud** is quieter than the single
  fixed volume 0.3.0 shipped.
- **The off switch is easier to find.** *Sound effects* moved from
  Settings → System to **Settings → Audio**, next to the microphone and the new
  volume — which is where people were looking for it. Off means silent; the
  volume greys out so it can't look live when it isn't.
- Cues stay **on by default**: the start cue is the only confirmation that
  hold-to-talk actually engaged while your eyes are on the text field, and a
  missed start costs you a whole re-dictation. One switch turns it all off.
- On a machine that can't do in-memory playback, cues are now **silent** rather
  than falling back to `winsound.Beep` — a fixed, full-volume square wave with
  no volume control, which is the opposite of what this release is for.

### The Scratchpad

Dictating a quick note used to mean opening Notepad first to catch it. Now
**Open Scratchpad** in the tray menu gives you a floating sticky note that is
already listening.

- Dictation lands in the note **while the note is the focused window**, and goes
  to whatever app you are in otherwise — the same "text goes where the cursor
  is" rule, with the note as one more place the cursor can be. The text is
  written straight into the note rather than pasted, so your clipboard is never
  touched.
- Edit it like any note, and format it from the strip along the bottom: bold,
  italic, underline, strikethrough and bullets. Dictated text arrives as plain
  text in whatever formatting the cursor is already in.
- Your text, size and position all survive closing the note and restarting the
  app. Closing hides it; nothing is ever deleted.
- No title bar: drag it by any empty part of the note, resize it from any edge,
  and close/minimize fade in only when the pointer is over it.
- Switch the whole feature off in **Settings → System → Scratchpad**. The tray
  entry disappears and the note is kept.


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
