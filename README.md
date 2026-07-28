# Rekounts

[![tests](https://github.com/rekreatedigital/rekounts/actions/workflows/tests.yml/badge.svg)](https://github.com/rekreatedigital/rekounts/actions/workflows/tests.yml)
[![License: GPL-3.0](https://img.shields.io/badge/license-GPL--3.0-blue.svg)](LICENSE)

**Hold a key, talk, and your words get typed wherever your cursor is.** Email,
Word, a chat box, your code editor — anywhere you can type, you can talk
instead.

It runs on your own computer. Your voice is never uploaded, there's no account
to make, and it's free — not a trial, not a "Pro" tier waiting for you later.

**[Download for Windows](https://github.com/rekreatedigital/rekounts/releases/latest)**
· [rekounts.com](https://rekounts.com)

> Windows 10/11 is the version you download. Macs can run it from source today,
> but it's experimental and nobody has tried it on real Mac hardware yet —
> [start here](docs/macos-quickstart.md) if you want to be the first. No Linux
> version.

While you're talking, the only thing on screen is a small pill above your
taskbar:

| | |
|:---:|:---:|
| ![The idle pill](docs/img/pill-idle.png) | ![Recording: cancel, live waveform, finish](docs/img/pill-recording.png) |
| *Idle — barely there* | *Recording — cancel · waveform · finish* |

## Getting it

1. Download **`Rekounts-Setup.exe`** from the
   [latest release](https://github.com/rekreatedigital/rekounts/releases/latest)
   and run it.
2. **Windows will warn you.** You'll see *"Windows protected your PC"* — click
   **More info**, then **Run anyway**. That happens because the installer isn't
   code-signed, not because anything's wrong with it. Once, and never again.
3. Click through the installer. Two optional boxes: a desktop shortcut, and
   whether to start Rekounts when you sign in. Both are off unless you tick
   them, and you can change your mind later.
4. **The first launch is slow and looks like nothing is happening.** It's
   downloading the speech model once — about 486 MB. Give it a few minutes.
   After that it starts in seconds and works with your Wi-Fi off.
5. Look for the Rekounts icon near the clock (you may need to click the `^` to
   show hidden icons).

No administrator rights and no UAC prompt — it installs for your account only.
**To upgrade**, just run the newer installer over the top; it keeps your
settings, your history and the model you already downloaded.

Prefer not to install anything? There's a portable ZIP on the same page — unzip
it anywhere and run `Rekounts.exe`.

## Talking to it

One key — **`Ctrl+Win`** by default — does everything:

| You do | What happens |
| --- | --- |
| **Hold** it, speak, **release** | Your text is inserted when you let go. |
| **Double-tap** it | Hands-free — it keeps recording while you talk. |
| **Tap** it while hands-free | Stops and inserts. |

While you're recording, the pill expands into **✕ │ waveform │ ✓** — click **✕**
to throw the recording away, or **✓** to finish early. A hands-free recording
you forget about stops itself after 10 minutes, and warns you 30 seconds before.

Don't like `Ctrl+Win`? Change it in Settings.

## The Scratchpad

<p align="center">
  <img src="docs/img/scratchpad.png" width="380"
       alt="The Scratchpad — a dark sticky note with a bulleted list and a formatting toolbar" />
  <br /><em>A note that's already listening</em>
</p>

Sometimes you just want to get a thought down, and opening Notepad to catch it
is a step too many. Right-click the tray icon → **Open Scratchpad** and you get
a floating note that's already listening.

Dictate into it while it's focused; click into anything else and your words go
there instead, exactly like always. You can edit it and format it — bold,
italic, underline, strikethrough, bullets — and your note, its size and its
position are all still there tomorrow.

No title bar: drag it by any empty part, resize from any edge, and the close and
minimize buttons only fade in when your pointer is over it. Closing hides the
note; it never throws it away.

## The Hub

<p align="center">
  <img src="docs/img/hub-dictation.png" width="820"
       alt="The Hub's Dictation page — history grouped by day" />
  <br /><em>Everything you've dictated, grouped by day, searchable</em>
</p>

Right-click the tray icon → **Open Dashboard**. Five pages, all on your machine:

- **Dictation** — everything you've said, newest first, with a search box. Copy
  or delete any entry, or clear the lot.
- **Insights** — words today, this week and all time, your words per minute,
  your daily streak, and the last three weeks as a chart.
- **Dictionary** — teach it names and jargon it keeps getting wrong, with an
  optional "sounds like" spelling.
- **Settings** — every change applies the moment you make it. No Save button,
  no restart.
- **Account** — a local display name and picture for the sidebar. There's no
  sign-in and no server; it's decoration.

## Your privacy, in short

Your voice is recorded into memory, transcribed on your own processor, and
never written to disk. Nothing about you is sent anywhere.

The app makes exactly **two** network requests, ever: downloading the speech
model the first time you use it, and asking GitHub whether there's a newer
version when you click **Check for Updates**. That's it. No analytics, no
telemetry, no account, no server — there's nothing to breach because there's
nothing on the other end.

Everything it keeps lives in `%APPDATA%\Rekounts` on your disk, and you can
delete it whenever you like. The full detail, checked against the source, is in
**[the privacy page](docs/privacy.md)**.

## If something goes wrong

- **Nothing gets typed** → Settings → **Test** your microphone. "Silent" means
  it's the wrong mic, or muted in Windows.
- **The hotkey does nothing** → something else is probably using it. Change it
  in Settings. (It also can't see keystrokes while an *administrator* window is
  focused — that's a Windows rule, not a bug. Click a normal window.)
- **Text went nowhere in an admin app** → Windows won't let a normal app type
  into an elevated one. Your words are still saved in the Hub, ready to copy.
- **Nothing arrives in Windows Terminal, PuTTY or a VM window** → a few apps
  ignore `Ctrl+V`, which is how Rekounts inserts text. There are two
  hand-edited settings for them: see
  **[if your app ignores Ctrl+V](docs/settings.md#if-your-app-ignores-ctrlv)**.
- **Tagalog is rough** → switch the speech model to `medium` in Settings.

Still stuck? Right-click the tray icon → **Send Feedback…**. It shows you
exactly what it's about to include, then opens a prefilled GitHub issue or an
email in your own mail app — already written, and not sent until you send it.
Your dictations are never part of it.

Your log lives at `%APPDATA%\Rekounts\logs\rekounts.log` (Settings → **Data &
Privacy** → **Open folder** takes you there). It never contains what you
dictated.

## Digging deeper

- **[Getting the best accuracy](docs/accuracy.md)** — choosing a speech model,
  measuring it on your own voice, and what a GPU is worth.
- **[Every setting](docs/settings.md)** — the full tour, and where your data
  lives.
- **[Privacy](docs/privacy.md)** — what's stored, and every moment it touches
  the network.
- **[Running on macOS](docs/macos.md)** — what's built, what's unknown, and why
  there's no Mac download. The friendly version is
  **[the quickstart](docs/macos-quickstart.md)**.
- **[Building from source](docs/building.md)** — running it yourself, the tests,
  and packaging the app.
- **[Changelog](CHANGELOG.md)** — what changed and when.

## Licence

GPL-3.0 — see [LICENSE](LICENSE). Free software: use it, read it, change it,
share it. If you distribute a modified version, it stays free too.

The speech models are Whisper, released by OpenAI under the MIT licence and
converted by SYSTRAN — details and attribution in
[docs/model-license.md](docs/model-license.md). "Rekounts" and the logo are
covered separately in [TRADEMARKS.md](TRADEMARKS.md).

Found a security problem? [SECURITY.md](SECURITY.md) has the private reporting
link. Want to help? [CONTRIBUTING.md](CONTRIBUTING.md).
