# Screenshots for the README

Both sets are generated. **Never screenshot either one by hand** — a manual
capture drifts from the app the moment the UI changes, and a hand-taken Hub shot
publishes whatever real dictations, microphone name and display name happened to
be on screen.

## The pill

```bat
.venv\Scripts\python.exe tools\capture_pill_shots.py
```

renders the real overlay widget and rewrites the seven `docs/img/pill-*.png`
tiles — the four resting states plus the three pending ones (a settings change
that has not landed yet). Rerun it after any change to `rekounts/ui/overlay.py`.

Tiles share one size so the README grid lines up. The hovered pending pill
spells out a whole sentence and does not fit, so it widens its own tile rather
than being cropped or having its text trimmed for the camera — the shot has to
be what the user actually sees.

## The Hub

```bat
.venv\Scripts\python.exe tools\capture_hub_shots.py
```

rewrites the four `docs/img/hub-*.png` images — Dictation, Insights, Dictionary,
Settings. Rerun it after any change to `rekounts/ui/dashboard.py`,
`rekounts/ui/settings_page.py` or `rekounts/ui/theme.py`.

It takes a few seconds, nothing appears on screen, and it is safe to run while
the app itself is running: it constructs the `Dashboard` widget directly, so it
never takes the single-instance mutex and never installs the keyboard hook.

**What it does.** Before importing anything from `rekounts`, it repoints
`APPDATA` at a fresh temp folder — the seam `tests/conftest.py` uses — so the
config and history it builds are throwaway and your real `%APPDATA%\Rekounts`
is neither read nor written. Into that sandbox it seeds three weeks of the
sample dictations from `scripts/seed_history.py` (fixed RNG seed, so reruns
don't reshuffle the shots) plus a handful of dictionary words, renders each page
at 2x, rounds the corners, and deletes the sandbox on the way out.

Two things are substituted so the published images can't leak the machine they
were captured on:

- the microphone dropdown gets two generic placeholder devices instead of the
  real device list;
- **Settings → Where your data lives** shows the generic
  `C:\Users\you\AppData\Roaming\Rekounts` instead of the sandbox temp path.

Everything else on screen is the app rendering its own state.

**Why not show the window and grab it?** Same two lessons as the pill tool:

- render with `QWidget.render()` rather than `show()` + `grab()`, so nothing
  flashes on screen and no window manager gets involved;
- use the **native** Qt platform. The `offscreen` platform has no font database
  and renders every glyph as a tofu box.

### If you change the shots

`WIN_W`/`WIN_H` at the top of the tool set the window size (900 × 600 — near the
Hub's own 880 × 620 default) and `SCALE` the device pixel ratio. Keep each PNG
under a few hundred KB; at 2x the dark UI compresses to about 60–100 KB.

Afterwards, **look at every image before committing** — open each one, read
every visible string, and confirm there is nothing in it you would not put on a
billboard. The README embeds all four at `width="820"`.

## Send Feedback

```bat
.venv\Scripts\python.exe tools\capture_feedback_shots.py
```

rewrites `docs/img/feedback-dialog.png` (the review window) and
`docs/img/feedback-menu.png` (the tray menu the entry lives in). Rerun it after
any change to `rekounts/ui/feedback_dialog.py`, `rekounts/feedback.py` or
`rekounts/ui/tray.py`.

Same sandbox as the Hub tool, plus two differences forced by what is being
photographed:

- **The machine's identity is pinned**, not just scrubbed: `USERNAME`,
  `USERPROFILE` and `COMPUTERNAME` are set to `you` / `C:\Users\you` / `PC`
  before `rekounts` is imported, so the image is the same wherever it is
  regenerated. The tool then **asserts** that the real user name, machine name
  and home path are absent from the captured block, and refuses to finish
  rather than publish a leak. This is a picture of the window whose entire job
  is to prove it leaks nothing.
- **The tray menu is popped up, not rendered.** A `QMenu` computes its action
  rectangles on the way to being shown and the Windows theme engine ignores a
  manually scaled render target, so `QWidget.render()` returns a blank
  rectangle. It is popped up at (-8000, -8000) — off every monitor, so still
  nothing flashes — and grabbed. That is why the whole process runs at
  `QT_SCALE_FACTOR=2` rather than rendering into a 2x pixmap: `widget.grab()`
  can only give 2x if the app was started that way.

The tray icon is created and hidden before the event loop can paint it, so this
is safe to run while the app itself is running.
