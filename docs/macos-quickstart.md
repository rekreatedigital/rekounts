# Rekounts on a Mac — the short version

Hold two keys, talk, let go, and your words appear wherever your cursor is.
This page gets you from "I have a MacBook" to that, in eight steps. You do not
need to know what any of the commands mean, and you can copy and paste every
one of them.

> **Read this bit first, it is short.** There is no Mac download yet. You run
> Rekounts from its source code, which is what all the typing below is for.
> More importantly: **nobody has ever run Rekounts on a real Mac.** Every Mac
> feature is written and tested by machine, but no human has watched it work.
> So this is an experiment you are welcome to try, not a finished product —
> and if it does something odd, that is genuinely useful to know about
> ([tell us](#if-something-goes-wrong)).

Throughout, steps 1–5 are ordinary Mac and Python things that work the way
everyone's do. Steps 6–8 are Rekounts itself, and those are the unconfirmed
ones — they say so where it matters.

**You need:** macOS 12 (Monterey) or newer, on either an Apple Silicon (M1/M2/
M3/M4) or an Intel Mac. **Time:** about 15 minutes of your attention, plus a
download that runs on its own. **Space:** roughly 2 GB while installing — about
1.3 GB once it settles, since pip keeps a cache you can delete afterwards.

---

## Step 1 — Open Terminal

Terminal is a Mac app for typing commands. It is already installed.

Press **⌘ Space**, type `terminal`, press **Return**.

**You should see:** a window with a line of text ending in `%` and a blinking
cursor. That is it waiting for you.

> Everything below is "paste one block, press Return, wait". Leave this window
> open for the whole page — and afterwards too, because Rekounts stops when you
> close it.

---

## Step 2 — Check your Python version

Paste this and press Return:

```sh
python3 --version
```

**You should see:** something like `Python 3.12.4`.

- **3.11 or 3.12** → you are fine, go to step 3.
- **3.13 or newer** → too new, and it will fail later with a confusing error.
  One of the pieces Rekounts uses (PySide6) does not run on 3.13 yet. Install
  3.12 as well — the two live side by side and nothing breaks — using the
  **macOS 64-bit universal2 installer** on
  [python.org's 3.12 page](https://www.python.org/downloads/release/python-3120/).
  Then use `python3.12` in place of `python3` in step 4.
- **3.10 or lower** (macOS ships an older one), or **"command not found"** →
  install 3.12 from that same
  [3.12 page](https://www.python.org/downloads/release/python-3120/), click
  through with the defaults, then close Terminal, open it again, and re-run the
  command above.
- **A pop-up appears saying "The `python3` command requires the command line
  developer tools"** → this is normal on a fresh Mac. Click **Install** and
  wait for it to finish (a few minutes), then run the command again. Note that
  this usually gives you Python 3.9, which is too old — so follow the
  "3.10 or lower" branch above afterwards.

---

## Step 3 — Download Rekounts

```sh
cd ~ && git clone https://github.com/rekreatedigital/rekounts.git && cd rekounts
```

**You should see:** `Cloning into 'rekounts'...`, some progress lines, and then
your prompt back. You now have a `rekounts` folder in your home folder.

> **If a box pops up** saying the `git` command needs the command line developer
> tools, click **Install** and wait for it to finish (a few minutes), then paste
> the command again.
>
> **If you would rather not install anything:** open
> [the repository](https://github.com/rekreatedigital/rekounts) in your browser,
> click the green **Code** button → **Download ZIP**, double-click the
> downloaded file, and then paste `cd ~/Downloads/rekounts-master` instead of
> the command above. Everything after this works the same.

---

## Step 4 — Make a private workspace for it

This keeps Rekounts' Python bits in its own folder instead of mixed in with the
rest of your Mac.

```sh
python3 -m venv .venv && source .venv/bin/activate
```

**You should see:** your prompt now starts with `(.venv)`. That prefix means the
workspace is switched on. If you ever open a fresh Terminal window, you will
need to switch it on again — [see below](#starting-it-up-next-time).

---

## Step 5 — Install what it needs

```sh
pip install -r requirements.txt
```

**You should see:** a lot of scrolling, then `Successfully installed` followed
by a long list. This downloads about 800 MB, so give it a few minutes on a
normal connection.

> This exact install is run automatically on an **Apple Silicon** Mac (M1 and
> up) every time the project changes, and takes about 23 seconds there. On an
> **Intel** Mac it has never been tried at all — it may be fine, but if it fails
> here, that is a real finding and worth reporting.

Now check the install is sound:

```sh
QT_QPA_PLATFORM=offscreen python -m pytest -q
```

**You should see:** a line like `1167 passed, 20 skipped`. Both numbers will
differ from a Windows run and both grow over time — the Mac-only tests run here
and the Windows-only ones skip, which is exactly right. What matters is that it
does **not** say `failed`. If it does, stop here and
[get help](#if-something-goes-wrong) — carrying on will only confuse things.

---

## Step 6 — Start it

```sh
python -m rekounts
```

**The first start is slow, and — this is the important part — completely
silent.** It downloads the speech model once, about 486 MB, into
`~/Library/Application Support/Rekounts/models/`. After that Rekounts works
completely offline, with your Wi-Fi off, forever.

> ### ⚠️ For the first few minutes, nothing happens at all
>
> No menu-bar icon, no pill, no Dock icon, and **no output in Terminal** — the
> window will look frozen. That is the download, and it is normal. **Do not
> press Ctrl+C**, and do not close the window.
>
> If you want to watch it actually progressing, leave that window alone, open a
> **second** Terminal window (`⌘N`) and paste:
>
> ```sh
> tail -f ~/Library/Application\ Support/Rekounts/logs/rekounts.log
> ```
>
> You will see lines counting up to `100%`. Press `Ctrl+C` in *that* second
> window when you are done watching — it only stops the watching, not Rekounts.

**Then you should see** *(this is the part nobody has watched on a real Mac)*:

- a small **Rekounts icon in your menu bar**, at the top right of the screen;
- a small dark **pill** near the bottom-centre of your screen — that is how you
  know it is listening. It is faint until you point at it;
- a Rekounts icon in your Dock. That one only appears because you are running
  from source, and it is expected.

Leave the Terminal window alone now. Closing it quits Rekounts.

---

## Step 7 — Give macOS permission (the step everybody trips on)

macOS will not let any app read your keyboard or type for you until you say so,
and it refuses **silently** — no error, nothing happens, and it looks like a
broken app. So do this even if Rekounts has not complained.

> ### ⚠️ You are looking for **Terminal** in these lists, not "Rekounts"
>
> This is the thing that catches everyone. macOS gives permissions to the app
> that is *running*, and right now that app is Terminal — Rekounts is just
> something Terminal is running. So **"Rekounts" will not be in the list.** Tick
> **Terminal**.
>
> Rekounts' own warning message says "Enable Rekounts under…". On a from-source
> run like this one, that wording is wrong — read it as "enable Terminal".
>
> Worth knowing: this widens what *anything* you later run from Terminal is
> allowed to do. That is a real trade, and it goes away once there is a proper
> Mac download.

1. Open **System Settings** → **Privacy & Security** → **Input Monitoring**.
   *(On macOS 12 Monterey and 13 it is called **System Preferences** → **Security & Privacy** → the **Privacy** tab — and you must click the padlock at the bottom left and enter your password before anything can be ticked.)*
   Switch **Terminal** on. *(Without this, the hotkey does nothing at all.)*
2. Go back, then into **Accessibility**. Switch **Terminal** on there too.
   *(Without this, your words are transcribed but never appear anywhere.)*
3. **Quit Terminal completely** — click the Terminal menu → **Quit Terminal**,
   or press **⌘Q**. macOS only notices new permissions when an app starts fresh.
4. Open Terminal again and start Rekounts back up:

   ```sh
   cd ~/rekounts && source .venv/bin/activate && python -m rekounts
   ```

5. The **microphone** is the easy one — macOS asks you itself, with a normal
   pop-up, the first time you dictate. Click **Allow**.

> **If Terminal is not in one of those lists at all:** click the **+** button,
> then go to **Applications → Utilities → Terminal** and add it. *(This is our
> best reading of how macOS behaves here rather than something we have watched —
> normally an app appears in the list by itself once it has asked.)*

---

## Step 8 — Say something

1. Open **TextEdit** (⌘ Space, type `textedit`, Return) and start a new blank
   document. **Click inside it** so the cursor is blinking there.
2. Hold **Ctrl + Cmd** down together.
3. Keep holding, and say a sentence out loud.
4. Let go.

**You should see:** the pill widen while you talk, then a second or two later
your sentence typed into TextEdit.

That is the whole app. There is nothing else to learn.

- **Double-tap** Ctrl+Cmd instead of holding, and it keeps recording hands-free
  until you tap once more.
- **Nothing to type into?** Nothing is lost — everything you dictate is also
  saved in the Hub (menu bar icon → **Open Dashboard**), ready to copy.

---

## Starting it up next time

Two lines, every time, in a fresh Terminal window:

```sh
cd ~/rekounts && source .venv/bin/activate && python -m rekounts
```

To stop it: menu bar icon → **Quit**, or press **Ctrl+C** in the Terminal
window, or just close the window.

---

## If something goes wrong

**The fastest route: paste [docs/macos-help-prompt.md](macos-help-prompt.md)
into ChatGPT, Claude, Gemini or whatever AI you use.** It is a ready-made block
that tells the AI everything about Rekounts on a Mac, so it can actually help
you instead of guessing. There is a second version in there for the most common
problem — "it started, but dictating does nothing", which is almost always a
permission from step 7.

The two things worth checking yourself first:

- **Did you quit and reopen Terminal after granting permissions?** (Step 7.3.)
  This is the single most common cause. Granting a permission to a running app
  does nothing until it restarts.
- **The log file** records what actually happened:

  ```sh
  tail -n 40 ~/Library/Application\ Support/Rekounts/logs/rekounts.log
  ```

And if you would rather tell us directly: open an issue at
[github.com/rekreatedigital/rekounts/issues](https://github.com/rekreatedigital/rekounts/issues)
with your macOS version, whether your Mac is Apple Silicon or Intel, which step
above you were on, and the last 40 lines of that log. You would be the first
person to run this on real hardware, so anything you send back is genuinely new
information.

---

## A few things worth knowing

- **Leave Processing on `CPU`.** In Settings there is a **Processing** dropdown
  with an `Auto` option. On a Mac it does nothing — the speech engine can only
  use NVIDIA graphics cards, which no Mac has. Your Mac's own chip is not an
  option, and `Auto` just quietly runs on the CPU anyway.
- **If it feels slow**, open the Hub (menu bar → **Open Dashboard**) →
  **Settings** → **Model** and pick `base`. It is a smaller download (~148 MB),
  noticeably faster, and slightly less accurate. `small` is the default because
  it is the better trade on most machines.
- **The hotkey** is written `Ctrl+Win` in some places, because Rekounts stores
  it with one name on every system. On your Mac keyboard it is **Ctrl+Cmd**, and
  that is how the app displays it. You can change it in Settings.
- **Nothing you say leaves your Mac.** No account, no cloud, no analytics. See
  [privacy.md](privacy.md) for exactly what is stored where.
- **Your stuff lives in** `~/Library/Application Support/Rekounts/` — settings,
  history, the speech model and the log. Deleting the `rekounts` folder from
  the `rekounts` folder removes the app but not that.

---

## What is still unknown

You are not being asked to trust a tested product, so here is the honest list.
These are unknown because they have never been executed on Mac hardware — not
because anything is known to be wrong:

- **Whether a long hold works.** Holding the hotkey for 30 seconds *may* cut
  itself off after a fraction of a second. If your recordings stop the instant
  you start, that is this.
- **Whether the pill stays on screen** while you are typing into another app.
- **Whether the Scratchpad** (the floating note) can be dictated into.
- **Whether the warning messages appear** when a permission is missing — the one
  thing standing between you and an app that silently does nothing. Automated
  testing has already shown macOS answering "yes, you have Input Monitoring" to
  a machine that had granted nothing, so grant it in step 7 regardless of what
  Rekounts tells you.

The full picture, including what *is* proven and how, is in
[Running on macOS](../README.md#running-on-macos). If you have an hour and want
to settle some of these, [macos-one-hour.md](macos-one-hour.md) is the ordered
list, and [MACOS-TESTING.md](../MACOS-TESTING.md) is the exhaustive one — it has
63 checkboxes and not one of them is ticked yet.
