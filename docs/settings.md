# Every setting, and where your data lives

The full tour. Most people never need this page — the Settings screen explains
each row as you read it.

## Settings

Settings are a page inside the Hub (tray → **Settings…** jumps straight there).
**Every change applies the moment you make it** — there is no Save button and
no restart. Switching the speech model reloads it in the background and tells
you when it is ready; everything else takes effect at once or on your next
dictation.

- **General** — the dictation hotkey (click the box and press the combo you
  want; combos the app cannot listen for are rejected rather than saved, and a
  **Reset** button puts it back to `Ctrl+Win`); language (Auto / English /
  Tagalog); the speech model — `small` (default, balanced, ~486 MB), `base`
  (fastest, ~148 MB), `medium` (most accurate offered, ~1.5 GB) — each size
  downloads once, the first time you pick it, from this project's own release
  host (see the **Accuracy guide** below for how to choose). A **Processing**
  row (`CPU` / `Auto`) appears only when this run could actually use a GPU —
  that is, from source on Windows or Linux. The installed app is a CPU-only
  build and macOS has no CUDA at all, so there the row is simply not shown
  rather than offering a choice that changes nothing. Your `device` setting in
  `config.json` is read and obeyed either way.
- **Audio** — microphone, with **Refresh** and a **Test** button (you want
  "Heard you clearly"); **Sound effects**, the short tone when dictation
  starts and stops; and its **Volume**.
- **Behavior** — the text cleanup toggles
  (remove fillers, auto-capitalize, fix punctuation spacing, remove repeated
  words and repeated short phrases — "I'm gonna I'm gonna" → "I'm gonna" — and
  **remove hedge phrases**, which drops "you know", "I mean", "like" and
  "right" only when commas mark them as asides, so "I like it" and "turn
  right" are never touched); **Catch the first word** (the pre-roll buffer);
  the maximum recording length; and the phantom-phrase filter.
- **System** — launch at login, the on-screen pill, the **Scratchpad**, tray
  notifications, and the automatic update check.
- **Data & Privacy** — the dictation-history switch, **Clear all**,
  **Clear note…** for the Scratchpad, **Open folder** shortcuts to where your
  data lives and to the diagnostic log, and **Send feedback…**.

Only a few tuning knobs remain config-file-only — edit
`%APPDATA%\Rekounts\config.json` and relaunch: `beam_size` (transcription beam
width), `preroll_seconds`, and the two insertion keys below —
`insertion_mode` and `long_text_via_paste`.

### How your text gets inserted

Rekounts puts your dictation on the clipboard, presses `Ctrl+V`, and puts your
old clipboard contents straight back. That is the only way Settings offers, and
it is the right one for effectively every app.

Settings used to offer **Type keystrokes** as an alternative, which typed the
characters out one at a time instead of touching the clipboard. It is gone,
because it quietly destroys text: the characters go out as synthesized key
events that Windows 11's rebuilt Notepad — and other modern apps built the same
way — draw as a row of identical dots rather than your words. That is about how
those apps read input, not about how much you dictated, so there is no
dictation short enough to be safe. Nothing warns you; the text simply arrives
wrong.

Alongside it went **Paste long dictations**, which only ever meant anything in
keystroke mode.

#### If your app ignores Ctrl+V

A handful do — Windows Terminal, PuTTY and some virtual-machine windows are the
usual suspects. They swallow `Ctrl+V` without complaining, so nothing on our
side can tell that your dictation went nowhere. Typing is the only thing that
works there, and you can still ask for it. It takes **both** of these keys in
`config.json`, then a relaunch:

```json
"insertion_mode": "keystroke",
"long_text_via_paste": false
```

Both, because either one on its own does something you almost certainly do not
want:

| `insertion_mode` | `long_text_via_paste` | What happens |
| --- | --- | --- |
| `"paste"` (default) | anything | Everything is pasted. |
| `"keystroke"` | `true` (default) | Everything is pasted — same as above. |
| `"keystroke"` | `false` | Everything is typed out, literally. |

Know what the last row costs you: typing reaches the apps that refuse paste,
and can mangle your dictation in modern ones like Notepad. It is the right
answer only if the app you actually dictate into is one of the awkward ones.
Set it back to `"paste"` (or delete both keys) to return to normal.

## Where your stuff lives

| What | Path |
| --- | --- |
| Settings | `%APPDATA%\Rekounts\config.json` |
| Dictation history + dictionary | `%APPDATA%\Rekounts\history.db` |
| Scratchpad note | `%APPDATA%\Rekounts\scratchpad.json` |
| Logs | `%APPDATA%\Rekounts\logs\rekounts.log` |
| Speech models | `%APPDATA%\Rekounts\models\<name>\` |
| The program itself (if you used the installer) | `%LOCALAPPDATA%\Programs\Rekounts` |

On macOS the same files live under
`~/Library/Application Support/Rekounts/` (`config.json`, `history.db`,
`scratchpad.json`, `logs/`, `models/`), and launch-at-login is a LaunchAgent at
`~/Library/LaunchAgents/com.rekreatedigital.rekounts.plist` rather than a
registry entry.

Note that those are two different places on purpose: **uninstalling removes the
program, not your data.** `%APPDATA%\Rekounts` survives uninstalls, reinstalls
and upgrades unless you tick the uninstaller's "also delete my settings,
history and downloaded model" box.

Full detail — including what is *not* stored — is in
[docs/privacy.md](privacy.md).

### Upgrading from TalkativeAI

TalkativeAI was this app's placeholder name. If you used it, **you do not have to
do anything** — the first launch of Rekounts brings your settings, history,
dictionary and downloaded models across from `%APPDATA%\TalkativeAI`, and moves
your **Launch at login** entry to the new name.

Quit the old app first if it is still in your system tray: both versions listen
for the same hotkey, so Rekounts refuses to start alongside it and tells you to
close it. Your old `%APPDATA%\TalkativeAI` folder is left behind on purpose so
you can roll back; delete it whenever you are happy.

## Where the speech models come from

The speech models are downloaded from **this project's own release host**:

```
https://github.com/rekreatedigital/rekounts-models
```

The app **never contacts `huggingface.co`** — not on first run, not ever. That is
structural rather than a setting: the model files are fetched up front and the
speech engine is handed a local directory path, so there is no code path left
that could reach out for anything.

| Model | Download | Notes |
| --- | --- | --- |
| `base` | ~148 MB | Fastest on any CPU. |
| `small` | ~486 MB | Noticeably better on accented or natural speech. |
| `medium` | ~1.5 GB | Most accurate, clearly slower on CPU. |

Each download is verified against a SHA256 hash recorded in
[`rekounts/models.py`](../rekounts/models.py) before it is used, so a corrupted
or tampered file is rejected instead of run. Interrupted downloads resume rather
than starting over.

**Already have the model?** If a matching copy exists in your
`%USERPROFILE%\.cache\huggingface` cache from another tool, Rekounts copies it
into its own folder on first run and downloads nothing at all. Your cache is left
untouched.

The models are SYSTRAN's MIT-licensed CTranslate2 conversions of OpenAI's
MIT-licensed Whisper models, redistributed unmodified — see
[docs/model-license.md](model-license.md) for the attribution and license
notices, and for how to add another model.

## Run on startup

Flip **Launch at login** in Settings → System. The app adds a per-user entry
under `HKCU\...\CurrentVersion\Run` and re-checks it at every launch, so it
fixes itself if you move the app folder. (Turning the switch off removes the
entry.) Alternatively, drop a shortcut to `Rekounts.exe` or `run.bat` into
`shell:startup` (Win+R → `shell:startup`).

The installer's **"Start Rekounts automatically when I sign in to Windows"**
checkbox is the *same* switch, not a second one — it writes the same registry
entry, so the Settings toggle reads back ON afterwards and turning it off in
either place turns it off everywhere. If you have it on already, re-running the
installer leaves it on.
