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

Everything lives in `%APPDATA%\Rekounts` (typically
`C:\Users\<you>\AppData\Roaming\Rekounts`).

| File | What is in it |
| --- | --- |
| `config.json` | Your settings: hotkey, microphone name, model, language, cleanup toggles, insertion mode, and the local display name / avatar path if you set them. Plain JSON — open it, read it, edit it. |
| `history.db` | A SQLite database of your dictations: the raw transcript, the cleaned text, a UTC timestamp, how long you spoke, the word count, and whether the text was successfully inserted. Also holds your Dictionary entries. |
| `logs\rekounts.log` | A rotating diagnostic log (max 1 MB, 3 backups). It records startup, model loading, errors, and audio *durations* — **not** your transcripts. |

| `models\<name>\` | The downloaded speech model (~148 MB for `base`, ~486 MB for `small`, ~1.5 GB for `medium`). Four plain files per model — delete a folder to reclaim the space; it is re-downloaded only if you select that model again. |

One thing lives outside that folder:

| Where | What |
| --- | --- |
| `HKCU\Software\Microsoft\Windows\CurrentVersion\Run\Rekounts` | A per-user registry entry, only if you turn on **Launch at login** (Settings → System). |

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

## When the app touches the network

Three times, all of them either one-off or triggered by you clicking something.
There are no background pings, no update daemon, and no account server.

1. **Downloading the speech model — once, on first use of a model.**
   The first launch (and the first time you pick a different model size) fetches
   the model from **this project's own release host**:

   ```
   https://github.com/ryankyleocampo-github/talkativeai-models/releases/download/...
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
2. **Check for Updates — only when you click it.** Tray menu →
   **Check for Updates** asks the public GitHub API for the newest commit on
   this project and shows it in a notification. Unauthenticated, no account, and
   it never runs on its own.
3. **Help — only when you click it.** Tray menu → **Help** opens this project's
   README in your normal web browser. That request is made by your browser, not
   by Rekounts.

Your voice, your transcripts, your history and your settings are never part of
any of these.

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
