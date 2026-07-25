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

**Time:** about 15 minutes of your attention, plus a download that runs on its
own. **Space:** roughly 1.5 GB.

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

## Step 2 — Check you have Python 3.11 or newer

Paste this and press Return:

```sh
python3 --version
```

**You should see:** something like `Python 3.12.4`.

- **3.11 or higher** → you are fine, go to step 3.
- **A lower number** (macOS ships an older one), or **"command not found"** →
  download the installer from
  [python.org/downloads](https://www.python.org/downloads/), open it, and click
  through with the defaults. Then close Terminal, open it again, and re-run the
  command above.

---

## Step 3 — Download Rekounts

```sh
cd ~/Documents && git clone https://github.com/rekreatedigital/rekounts.git && cd rekounts
```

**You should see:** `Cloning into 'rekounts'...`, some progress lines, and then
your prompt back. You now have a `rekounts` folder in your Documents.

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
python -m pytest -q
```

**You should see:** a line like `1165 passed, 5 skipped`. The numbers grow over
time; what matters is that it does **not** say `failed`. If it does, stop here
and [get help](#if-something-goes-wrong) — carrying on will only confuse things.

---

## Step 6 — Start it

```sh
python -m rekounts
```

**The first start is slow.** It downloads the speech model once — about 486 MB —
into `~/Library/Application Support/Rekounts/models/`. After that Rekounts works
completely offline, with your Wi-Fi off, forever.

**You should see** *(this is the part nobody has watched on a real Mac)*:

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
   Switch **Terminal** on. *(Without this, the hotkey does nothing at all.)*
2. Go back, then into **Accessibility**. Switch **Terminal** on there too.
   *(Without this, your words are transcribed but never appear anywhere.)*
3. **Quit Terminal completely** — click the Terminal menu → **Quit Terminal**,
   or press **⌘Q**. macOS only notices new permissions when an app starts fresh.
4. Open Terminal again and start Rekounts back up:

   ```sh
   cd ~/Documents/rekounts && source .venv/bin/activate && python -m rekounts
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
cd ~/Documents/rekounts && source .venv/bin/activate && python -m rekounts
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
  Documents removes the app but not that.

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
