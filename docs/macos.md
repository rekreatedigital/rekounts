# Running on macOS — the engineering picture

What is implemented, what is genuinely unknown, and why there is no macOS
download. If you just want to try it on your Mac, start with
**[the macOS quickstart](macos-quickstart.md)** instead — same thing, written
step by step for a person rather than an engineer.

## Running on macOS

> **Just want to dictate on your MacBook?** →
> **[docs/macos-quickstart.md](macos-quickstart.md)** is the same thing
> written for a person rather than an engineer: eight numbered steps, what you
> should see after each one, and the permission trap spelled out. If it goes
> wrong, [docs/macos-help-prompt.md](macos-help-prompt.md) is a block to
> paste into whatever AI you use, so it can help without knowing this project.
>
> The rest of this section is the engineering picture — what is implemented,
> what is genuinely unknown, and why there is no download.

**Status: experimental, from source only, and not yet confirmed on a physical
Mac.** Read that as written. The macOS port is complete in the sense that every
platform-specific piece has a real mac implementation — pasting via Quartz
events, NSPasteboard clipboard preservation, launch-at-login as a LaunchAgent,
data under `~/Library/Application Support/Rekounts`, permission checks that tell
you which consent is missing — and CI installs the full mac dependency set and
executes those code paths on every push. What CI cannot do is grant macOS
permissions, so the behaviours that depend on them have been *reasoned about*,
not *observed*. The open ones are listed below, and the checklist someone with a
Mac should work through is [MACOS-TESTING.md](../MACOS-TESTING.md).

There is deliberately **no macOS download**. An unverified `.app` that silently
does nothing because a permission was never granted is worse than no `.app`.

### Setup

The terse version; [the quickstart](macos-quickstart.md) is the same thing
step by step, for someone who has not done this before.

You need **macOS 12 (Monterey) or newer** and Python **3.11 or 3.12**
(`brew install python@3.12`, or python.org). Not 3.13+: the pinned
`PySide6==6.7.2` declares `Requires-Python: <3.13`, so the install fails.

```sh
git clone https://github.com/rekreatedigital/rekounts.git && cd rekounts
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt      # ~800 MB, once
python -m pytest -q                  # sanity check: expect all green
python -m rekounts                   # or: python launch.py
```

CI installs that dependency set on an **Apple Silicon** runner on every push, in
about 23 seconds. **Intel has never been installed by CI or by hand**, so it is
untested rather than known-good — if you are on one, whether `pip install`
even completes is itself a useful data point.

The first launch downloads the speech model once (~486 MB for the default
`small`) to `~/Library/Application Support/Rekounts/models/`. After that it runs
with the network unplugged, exactly as on Windows.

Rekounts lives in the **menu bar**. Run from source it also shows a normal
Dock icon — the no-Dock-icon treatment (`LSUIElement`) only exists in the
future `.app` bundle, which nothing ships yet. There is no window until you
open the Hub.

### The permissions, and the thing that surprises everyone

macOS gates each of the app's three core abilities behind a separate consent,
and **denies them silently** — no dialog, no error, the events simply never
arrive. Rekounts checks at startup and names any it can see is missing, so that
a missing permission does not just look like a broken app.

That check is weaker than it reads, and the weakness is measured rather than
theoretical: on the `macos-latest` CI runner
`CGPreflightListenEventAccess()` returns `True` with nobody having granted
anything ([MACOS-TESTING.md §2](../MACOS-TESTING.md)). So **no warning is not
evidence that Input Monitoring is granted** — grant it either way.

| Consent | What stops working without it | Where |
| --- | --- | --- |
| **Input Monitoring** | the global hotkey — nothing responds at all | System Settings → Privacy & Security → Input Monitoring |
| **Accessibility** | pasting the dictated text into other apps | …→ Accessibility |
| **Microphone** | recording (this one prompts by itself on first use) | …→ Microphone |

> ### ⚠️ Running from source grants the permissions to your TERMINAL, not to Rekounts
>
> This is the part that catches people out. macOS attributes permissions to the
> **running process's bundle**, and when you launch with `python -m rekounts`
> that bundle is Terminal.app, iTerm, or whatever you typed the command into.
> So:
>
> * The entry you tick under Input Monitoring and Accessibility is **Terminal**
>   (or iTerm2, or VS Code if you run it from an integrated terminal) — you will
>   look for "Rekounts" in those lists and it will not be there. The app's own
>   startup notice says *"Enable Rekounts under…"*, which is the right wording
>   for the packaged `.app` and the wrong wording for a from-source run
>   (`rekounts/permissions.py`); read it as "enable your terminal".
> * Everything you run from that terminal afterwards inherits the same grants.
>   That is a real, permanent widening of what a shell on your Mac may do, and
>   it is worth being deliberate about — consider a dedicated terminal app for
>   this rather than the one you use all day.
> * Launching from a *different* terminal means granting again, per app.
> * After granting, **quit and reopen the terminal**, then relaunch Rekounts.
>   macOS only re-reads the grant when the process starts.
>
> A packaged, signed `.app` would get its own identity and its own three grants,
> which is the main reason packaging matters here and not just cosmetically —
> [docs/macos-packaging.md](macos-packaging.md).

### What is genuinely unknown

Not "probably fine" — unknown, because it has never been executed on hardware.
These are in priority order and are exactly what
[docs/macos-one-hour.md](macos-one-hour.md) works through:

1. **Long push-to-talk holds.** The recording watchdog reads physical key state
   through `CGEventSourceKeyState`. If that lies about held keys under macOS's
   permission model, a hold could self-release about a third of a second in.
   There is a gate meant to prevent it (the watchdog is only enabled once the
   Input Monitoring preflight passes) and CI confirms the gate reads the real
   preflight — but not that the poll then tells the truth.
2. **The dictation pill staying visible.** Its entire job is to be on screen
   while *another* app is frontmost. macOS hides tool windows on app deactivate;
   three layers of countermeasure are in place and none has been seen working.
   `REKOUNTS_MAC_OVERLAY_NATIVE=0` disables the native ones if they misbehave.
3. **The Scratchpad taking focus.** It is plain Qt with no platform branches at
   all, and it was written before macOS was in scope. Dictation routes into the
   note only while the note is the *active* window, and a frameless window in a
   menu-bar-only app is precisely the case where "active" gets complicated.
4. **Whether a `.app` builds and runs.** `Rekounts-macos.spec` and the icon and
   entitlements it needs are written; PyInstaller has never been run on them.

### Known limits on macOS (by design, not bugs)

- **Focus tracking is per-app, not per-window.** Windows gives a stable handle
  per window; macOS does not, cheaply, so "did focus move while I transcribed?"
  is answered at the granularity of the frontmost *application*. Switching
  between two windows of the same app will not abort a delivery.
- **Hotkey letters and digits assume a US/ANSI layout.** The same trade the
  Windows path already makes. Modifier-only combos (the default `Ctrl+Cmd`) and
  function keys are layout-independent.
- **No GPU option.** The speech engine's only accelerator backend is NVIDIA
  CUDA, and there is no macOS build of it — so Settings shows no **Processing**
  row on a Mac at all.
- The default hotkey `ctrl+win` is **Ctrl+Cmd** on a Mac keyboard — the config
  token is shared across platforms; only the label differs.

If you get stuck, [docs/macos-help-prompt.md](macos-help-prompt.md) is a
self-contained block to paste into any AI assistant — it carries the setup, the
three permissions, the terminal-attribution trap and the known-unknowns above,
so the assistant can diagnose without this repo in front of it.

If you do try it, the most useful thing you can send back is a filled-in
[MACOS-TESTING.md](../MACOS-TESTING.md) with
`~/Library/Application Support/Rekounts/logs/rekounts.log` attached — including
the parts that worked, since "confirmed working on hardware" is currently a list
of zero items.
