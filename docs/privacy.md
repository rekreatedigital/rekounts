# Privacy

Rekounts is a local dictation app. Your voice is turned into text **on your
own machine**, by a speech model that runs on your own CPU. This page describes
exactly what is stored, where, and the only moments the app talks to the
internet.

Everything below was checked against the source, not aspirational.

## Your audio

**Your recordings are never written to disk.** Audio lives in memory as a NumPy
buffer while you hold the hotkey, is handed straight to the local speech model,
and is dropped when the recording ends. There is no `.wav` file, no temp file,
no upload, and no "improve the product" telemetry — the app contains no
analytics code of any kind.

If you enable **pre-roll** (`"preroll_enabled": true`), a short rolling buffer of
the last half-second is kept in RAM so your first syllable is not clipped. Same
rule: memory only, never disk. It is off by default precisely because it holds
the microphone stream open, which keeps the Windows "microphone in use"
indicator lit — that is a thing you should opt into knowingly.

## What is stored on your machine

Everything lives in `%APPDATA%\Rekounts` (on macOS:
`~/Library/Application Support/Rekounts`; typically
`C:\Users\<you>\AppData\Roaming\Rekounts`).

| File | What is in it |
| --- | --- |
| `config.json` | Your settings: hotkey, microphone name, model, language, cleanup toggles, insertion mode, and the local display name / avatar path if you set them. Plain JSON — open it, read it, edit it. |
| `history.db` | A SQLite database of your dictations: the raw transcript, the cleaned text, a UTC timestamp, how long you spoke, the word count, and whether the text was successfully inserted. Also holds your Dictionary entries. |
| `logs\rekounts.log` | A rotating diagnostic log (max 1 MB, 3 backups). It records startup, model loading, errors, and audio *durations* — **not** your transcripts. |
| `logs\rekounts-crash.log` | Empty unless the app has crashed hard enough to take the whole process down. It holds the native stack trace of that crash and nothing else — no text, no audio, no settings. Delete it whenever you like. |
| `scratchpad.json` | **Your Scratchpad note**, saved automatically. See [The Scratchpad](#the-scratchpad) below — this one holds text you wrote or dictated, and it is not covered by the dictation-history switch. |

| `models\<name>\` | The downloaded speech model (~148 MB for `base`, ~486 MB for `small`, ~1.5 GB for `medium`). Four plain files per model — delete a folder to reclaim the space; it is re-downloaded only if you select that model again. |

A few things live outside that folder, and all of them belong to the *program*
rather than to your data:

| Where | What |
| --- | --- |
| `HKCU\Software\Microsoft\Windows\CurrentVersion\Run\Rekounts` | A per-user registry entry, only if you turn on **Launch at login** (Settings → System, or the matching checkbox in the installer — they are the same switch). |
| `%LOCALAPPDATA%\Programs\Rekounts` | The program itself, if you used the installer. Nothing personal is kept here. (The portable ZIP puts the same files wherever you unzipped it.) |
| Start Menu, and the Desktop if you asked for it | Shortcuts the installer created. |
| `HKCU\Software\Microsoft\Windows\CurrentVersion\Uninstall\...` | The entry that makes Rekounts appear in **Settings → Apps**, so it can be uninstalled like anything else. |

The installer is per-user throughout: it never asks for administrator rights,
writes nothing outside your own account, and touches no system-wide location.

### Uninstalling

Uninstalling removes the program and the entries above — and stops there.
**`%APPDATA%\Rekounts` is left exactly where it is**, so your settings, your
dictation history and the speech model you downloaded survive an uninstall, a
reinstall, and an upgrade. The uninstaller offers a checkbox to delete that
folder too; it is unticked, and nothing deletes it unless you tick it yourself.
You can of course also just delete the folder by hand at any time.

### If you used the app when it was called TalkativeAI

Your data used to live in `%APPDATA%\TalkativeAI`. The first launch of Rekounts
copies it into `%APPDATA%\Rekounts` for you, and replaces the old
`...\Run\TalkativeAI` startup entry with the Rekounts one so the old version
does not keep starting at login.

**The old folder is left in place** — copied, not emptied — so you can go back to
the old version if you want to. Nothing reads it any more, so delete
`%APPDATA%\TalkativeAI` yourself whenever you are ready. The one exception is
`models\`, which is *moved* rather than copied, because duplicating several
gigabytes of speech models could fill your disk.

The speech model lives in the app's own folder, **not** in the shared
`%USERPROFILE%\.cache\huggingface` cache. If you already had a matching model in
that cache from another tool, Rekounts copies it across on first run instead
of downloading it again — and leaves your cache untouched.

Nothing is encrypted, because nothing leaves your machine — anyone who can read
your Windows user profile can read these files, exactly like your documents.

### Turning history off, or clearing it

- **Clear it:** Hub → **Dictation** → **Clear all** (also available in
  Settings → Data & Privacy), or delete entries one at a time. You can also
  just delete `history.db`.
- **Never record it:** turn **Save dictation history** off in Settings →
  Data & Privacy — it takes effect on your very next dictation, no restart.
  (`"history_enabled": false` in `config.json` is the same switch.) With it
  off, `History.add()` does nothing — no rows are written at all.

**This switch covers `history.db` and nothing else.** In particular it does not
cover the Scratchpad: if you have written or dictated into the note, that text is
in `scratchpad.json` and stays there whether history is on or off, and deleting
`history.db` does not touch it. Clearing the note is a separate, deliberate
action — see below.

## The Scratchpad

The Scratchpad is the floating sticky note you can open from the tray menu and
dictate into. **It saves what you write there automatically**, about
three-quarters of a second after you stop typing, and again when you close or
hide it. There is no Save button, and it is not asking you first. That is the
point of a sticky note — it is still there tomorrow — but it does mean the
Scratchpad is the one place in Rekounts where your text sits on disk without you
having decided to put it there.

It is saved to `%APPDATA%\Rekounts\scratchpad.json`, as the note's rich text
(bold, bullets and so on, which is why it is HTML rather than plain text) plus
the window's last position. It is a plain file — open it and read it. It never
leaves your machine; nothing above in [When the app touches the
network](#when-the-app-touches-the-network) reads or sends it.

**Clearing it:** Settings → Data & Privacy → **Clear note**, which asks first
and then empties both the open note and the file. You can also just delete
`scratchpad.json` while the app is closed.

**Turning the feature off does not delete your note.** Settings → System →
**Scratchpad** hides the pad and stops dictation being routed to it; the text
you had written is deliberately left alone, because turning a feature off is not
a request to throw away what you wrote. If you want the text gone, clear it.

We chose to keep it that way rather than tying the note to **Save dictation
history**. The history is a *record* Rekounts keeps of what you dictated; the
note is a *document you are writing*, on screen in front of you. Wiring the two
together would mean that switching on a privacy setting silently deleted an open
note, which is data loss rather than privacy. So the note gets its own explicit
control instead — you can see it, and you can get rid of it, without either
happening by surprise.

## When the app touches the network

<!-- network-moments: 2 (source of truth: rekounts/network_facts.py — keep this
     marker, tests/test_network_claims.py checks the number against the code) -->

Rekounts reaches the network twice. One is a one-off download; the other is
triggered by you clicking something, unless you switch on the opt-in check that
is off until you do. There are no background pings, no update daemon, and no
account server.

(This page used to say three times, counting **Help** as the third. It is not:
Help hands a URL to your web browser, and the request is your browser's. The
same goes for clicking an update notification. Both are described below, under
their own heading, because "your browser fetched a page you asked for" and
"Rekounts made a request" are different promises and should not share a number.)

1. **Downloading the speech model — once, on first use of a model.**
   The first launch (and the first time you pick a different model size) fetches
   the model from **this project's own release host**:

   ```
   https://github.com/rekreatedigital/rekounts-models/releases/download/...
   ```

   That is the only host involved. The app **never contacts `huggingface.co`** —
   not on first run, not ever. (Earlier development builds downloaded from
   Hugging Face; that dependency is gone entirely.) If a matching model already exists in
   your `%USERPROFILE%\.cache\huggingface` cache from another tool, it is copied
   from there and **nothing is downloaded at all**.

   Every file is checked against a SHA256 hash recorded in the app's source
   (`rekounts/models.py`) before it is used, so a corrupted or tampered
   download is rejected rather than run.

   After that one download, loads are **fully offline**: the model is opened
   straight from a folder on your disk with **zero network requests** — online or
   not. This is structural, not a setting: the app hands the speech engine a
   local directory path, so there is no code path left that could fetch anything.
2. **Check for Updates.** Tray menu → **Check for Updates** asks the public
   GitHub API for this project's newest **release**:

   ```
   https://api.github.com/repos/rekreatedigital/rekounts/releases/latest
   ```

   It compares that release's version number with the one you are running and
   shows the answer in a notification. Unauthenticated, no account, no query
   string, and nothing about you is sent — the request carries no identifier
   beyond a `User-Agent` of `Rekounts/<version>`, which GitHub requires. It
   **downloads nothing and installs nothing**; if there is an update, clicking
   the notification opens the release page in your browser and you take it from
   there.

   **By default this only happens when you click it.** There is one opt-in:
   **Settings → System → Check for updates automatically**, which is **off**
   until you turn it on. With it on, Rekounts makes that same single request
   about ten seconds after each launch and says nothing at all unless there is
   genuinely a newer release — no "you're up to date" toast, and nothing if you
   are offline. Turning it back off stops it at the next launch. It is also
   `"auto_check_updates": false` in `config.json` if you would rather set it
   there.
Your voice, your transcripts, your history and your settings are never part of
either of these.

### Pages Rekounts opens in your browser — or your mail client

Three places hand a web address to your normal browser — or a ready-to-read
message to your mail client — and stop there. Rekounts makes no request of its
own, sends nothing, and never sees the answer — which is why they are not in
the count above:

- **Help.** Tray menu → **Help** opens this project's README.
- **An update notification.** Clicking one opens the release page.
- **Send Feedback…** (tray menu, and Settings → Data & Privacy) shows you a
  short diagnostics block first — app version, Windows version, Python version,
  whether you run the installed build, and four settings: model, processing,
  insertion mode and language. That is the whole list, shown in a window with
  **Copy** and **Save** and deliberately **no Send button**. From there it can
  open a **prefilled GitHub issue form** in your browser or a **prefilled
  email** in your mail client — both arrive unsent; you read, edit, delete,
  and nothing goes anywhere until *you* press submit or send.

  Never included: your transcripts, your Scratchpad, your Dictionary, your
  history, your microphone's name (which often contains a person's name), your
  Windows user name, your machine name, and your home-folder path. If you tick
  the optional box to attach the last few log lines, those are capped and the
  paths in them are rewritten (`C:\Users\you\…` becomes `%USERPROFILE%\…`)
  before you ever see them, let alone send them.

## Your clipboard

In the default **paste** insertion mode the app briefly puts your dictated text
on the clipboard, presses `Ctrl+V`, and then puts your original clipboard
contents back — including images, files and rich text, not just plain text. If
you copied something new in that fraction of a second, the app notices and
leaves your new clipboard alone rather than overwriting it. Choose the
**keystroke** insertion mode in Settings if you would rather the clipboard were
never touched.

## The Account page

The Hub's **Account** page stores a display name and an avatar path in
`config.json` and nothing more. There is no sign-in, no account, no server, and
no sync.
