# Stuck? Paste this into any AI

If Rekounts will not install or will not work on your Mac, the quickest way to
get unstuck is usually to ask whatever AI assistant you already use — ChatGPT,
Claude, Gemini, Copilot, any of them.

The problem is that none of them know what Rekounts is. So below are two blocks
that tell them. **Copy one whole block, paste it into the AI, fill in the bit at
the bottom, and send it.** They are written to be self-contained: the AI does not
need to look anything up.

- **[Block A](#block-a--it-will-not-install)** — a command failed, or the app
  will not start.
- **[Block B](#block-b--it-runs-but-dictation-does-nothing)** — it started fine,
  but dictating does nothing. This is the common one, and it is almost always a
  macOS permission.

Not sure which? If you got as far as seeing a Rekounts icon in your menu bar,
use Block B.

---

## Block A — it will not install

```text
I'm trying to run an app called Rekounts on my Mac and I'm stuck. Here's what
you need to know — please help me work out what went wrong.

WHAT REKOUNTS IS
A free, open-source, offline voice dictation app (GPL-3.0). You hold a hotkey,
speak, and it types your words into whatever app you're in. It's Python +
PySide6 (Qt) + faster-whisper, and it runs entirely on my machine — no cloud,
no account.

THE SITUATION ON MACOS
There is no Mac download. On macOS it only runs from source. It's explicitly
experimental: the Mac code is complete and passes automated tests, but it has
never been run on physical Mac hardware by anyone, so unexpected failures are
genuinely possible and "this is just broken" is a valid conclusion.
It needs macOS 12+ and Python 3.11 or 3.12 (NOT 3.13 or newer — PySide6, which it depends on, has no 3.13 build yet). The install is verified automatically on
Apple Silicon only — Intel Macs have never been tested.

THE EXACT STEPS I'M FOLLOWING
  cd ~/Documents && git clone https://github.com/rekreatedigital/rekounts.git
  cd rekounts
  python3 -m venv .venv && source .venv/bin/activate
  pip install -r requirements.txt     # ~800 MB
  python -m pytest -q                 # should end "... passed", no failures
  python -m rekounts                  # first run downloads a ~486 MB speech model

WHERE THINGS LIVE
  Data + settings: ~/Library/Application Support/Rekounts/
  Log file:        ~/Library/Application Support/Rekounts/logs/rekounts.log

WHAT I'M NOT ASKING
Don't suggest a Mac installer, a .app, Homebrew or a package manager — none
exist for this. Running from source is the only supported route.

MY SETUP
  macOS version:        [e.g. 14.5 — Apple menu > About This Mac]
  Apple Silicon/Intel:  [same window: "Chip M2" = Apple Silicon, "Processor Intel" = Intel]
  Python version:       [run: python3 --version]
  The step that failed: [which command above]

WHAT WENT WRONG
[paste the full error here — all of it, including the lines above the error]

Please tell me what's happening in plain language and what to try next. Ask me
to run diagnostic commands if that helps; I'll paste the output back.
```

---

## Block B — it runs, but dictation does nothing

```text
I'm running a dictation app called Rekounts on my Mac. It starts up, but
dictating doesn't do anything. Please help me diagnose it.

WHAT REKOUNTS IS
A free, open-source, offline dictation app (Python + Qt + faster-whisper). Hold
a hotkey, speak, release, and your words get typed into whatever app has the
cursor. It runs entirely locally.

HOW I RUN IT
From source, not as a Mac app — there is no Mac download. I start it by typing
`python -m rekounts` in Terminal, and it appears as a menu-bar icon plus a small
pill near the bottom of my screen. The hotkey is Ctrl+Cmd: hold it, talk, let
go. Double-tap latches it hands-free.

THE THREE PERMISSIONS IT NEEDS — AND THE BIG GOTCHA
macOS gates this app behind three separate consents, and denies them SILENTLY:
no error, nothing happens, it just looks broken.
  * Input Monitoring — without it the hotkey does literally nothing
  * Accessibility    — without it my words are transcribed but never typed out
  * Microphone       — macOS prompts for this one itself on first use
THE GOTCHA: because I run it from source, macOS attributes these permissions to
TERMINAL, not to Rekounts. "Rekounts" does not appear in those Privacy &
Security lists at all — the entry I have to tick is "Terminal" (or iTerm, or
VS Code if I started it from there). The app's own warning text says "Enable
Rekounts under..." which is wrong for this setup. Also: macOS only re-reads a
permission when the app STARTS, so after granting one I have to fully quit
Terminal (Cmd+Q) and relaunch, not just restart the app.

KNOWN-UNKNOWN BEHAVIOURS (this app has never been run on real Mac hardware)
  * A long hotkey hold may cut itself off after a fraction of a second, because
    of how macOS reports held keys. If recording stops the instant I start
    talking, this is a known suspect, not my mistake.
  * The startup warnings about missing permissions may not appear at all —
    macOS has been observed reporting Input Monitoring as granted when it
    wasn't. So "no warning" does NOT mean "permission is fine".
  * Nothing on a Mac uses the GPU, and Settings shows no Processing row at
    all — so that is not the problem.
If a dictation can't be delivered, that's not data loss: the transcript is still
saved in the app's own Dashboard (menu-bar icon > Open Dashboard).

WHAT EXACTLY HAPPENS
[Describe it: does the pill react when you hold the hotkey? Does it change while
you speak? Does anything appear anywhere? Did the mic pop-up ever show?]

WHAT I'VE ALREADY TICKED
  Input Monitoring: [Terminal ticked? yes/no]
  Accessibility:    [Terminal ticked? yes/no]
  Microphone:       [was I ever asked? did I allow it?]
  Did I fully quit and reopen Terminal afterwards? [yes/no]

MY SETUP
  macOS version:       [Apple menu > About This Mac]
  Apple Silicon/Intel: [same window]
  Python version:      [run: python3 --version]

THE LOG
[paste the output of:
   tail -n 40 ~/Library/Application\ Support/Rekounts/logs/rekounts.log ]

Please work out which of the three permissions is missing, or tell me if this
looks like one of the known-unknown failures above rather than something I can
fix. Plain language please.
```

---

## What to send back to us

Whatever the AI concludes, the project would like to know — you are very likely
the first person ever to have run this on a real Mac. Open an issue at
[github.com/rekreatedigital/rekounts/issues](https://github.com/rekreatedigital/rekounts/issues)
with:

- your **macOS version** and whether the Mac is **Apple Silicon or Intel**;
- your **Python version** (`python3 --version`);
- **what you did and what happened**, in your own words;
- the **last 40 lines of the log**:
  `tail -n 40 ~/Library/Application\ Support/Rekounts/logs/rekounts.log`;
- a **screenshot** if anything looked wrong on screen — literally nobody on this
  project has seen Rekounts running on a Mac.

**Things that worked are worth reporting too.** "Confirmed working on Mac
hardware" is currently a list of zero items, so a message saying "it installed
and dictation landed in TextEdit first time" is as valuable as a bug report.

Back to [the quickstart](macos-quickstart.md).
