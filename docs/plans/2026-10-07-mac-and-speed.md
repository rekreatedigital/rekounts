# Plan: faster results after talking, and a Mac version that just works

*Written 2026-10-07 by the conductor session. This is an audit and a plan: no
code was changed, and nothing below has started yet. Next step: answer the four
decisions at the bottom, then a conductor session turns sessions A–D into
copy-paste prompts.*

## The short version

- **Long dictations are slow because the app waits until you stop talking, then
  transcribes everything at once.** The wait grows by about 5–6 seconds for
  every minute you talk. The fix is to transcribe in small pieces *while* you
  talk, so only the last few seconds are left when you stop. Simulated on the
  reference PC, a 5-minute dictation's wait dropped from 24 seconds to about 1.
- **The Mac version is written but has never run on a real Mac.** This audit
  found three likely showstoppers and several keyboard differences the app does
  not handle yet. Most of it can be fixed without a Mac; a final ~2-hour
  hands-on test needs one.

## How to pick this up

Open Claude Code in this repo and say something like:

> Read docs/plans/2026-10-07-mac-and-speed.md. My answers to the four
> decisions are: … Write the prompts for sessions A–D.

The usual workflow applies: one worktree session per lettered item below, each
owning the files listed so sessions don't collide, each reproducing a bug with a
test before fixing it, each ending in a PR the conductor reviews.

---

## 1. Speed

### What's happening (measured)

Measured from real dictations on the reference PC (Ryzen 7 7800X3D, `small`
model, CPU, the installed v0.4.3 build) by pairing each History entry's
timestamp with the log line where its transcription started:

| You talk for | You wait after letting go |
| --- | --- |
| 10 seconds | ~1.5–2 s |
| 1 minute | ~5–6 s |
| 2 minutes | ~10 s |
| 5 minutes | ~24–28 s |
| 10 minutes (the current cap) | ~50 s (extrapolated) |

Rule of thumb: **wait ≈ 1.2 s + 0.09 s per second of speech.** The cause is
`AppController._process` in `rekounts/controller.py`: the recorder hands over
the whole clip only after stop, and the transcriber starts from zero.

### The fix: transcribe while you talk (session A)

While recording, cut the audio at natural pauses into pieces of about 15–20
seconds and transcribe each piece in the background. When the user stops, only
the last piece is left; the pieces are joined, cleaned and pasted once, exactly
as today.

Simulated on the reference PC with the exact decode settings the app uses, on a
5-minute clip:

- wait after stop: **24.1 s → 1.0 s**
- each piece transcribed ~10× faster than real time, so the background work
  keeps up with plenty of room
- 5 of 788 words differed from transcribing the whole clip at once (e.g.
  "third" vs "3rd")
- about 17% more total CPU work (each piece pays one fixed engine pass)

What the design must keep true:

- **This is not live typing.** Nothing appears until the user finishes. Live
  typing was removed on purpose on 2026-07-25; this only changes *when* the work
  happens.
- Cut only at silences, and keep pieces at **20 seconds or less**. Pieces over
  ~25 s often spill into a second 30-second engine window and cost twice as much.
- Cancel (✕) still throws everything away, and audio still never touches disk.
- The phantom-phrase filter must still judge the *real* end of the dictation,
  not the end of each piece: collect segments, strip the tail once at the end.
- A computer too slow to keep up falls back to today's behavior, never worse.
- Once this ships, the 10-minute cap (`max_recording_seconds` in
  `rekounts/config.py`) can go up — see decision 4.

### Smaller tweaks (measured, also session A)

| Change | Effect on the reference PC | Verdict |
| --- | --- | --- |
| Log how long each step took (numbers only, never words) | — | **Do first** — today the log cannot show where time goes |
| `cpu_threads=8` (the default is 4) | 5–10% faster | Do it — but never 16, which is 15–25% *slower* |
| Warm up with the voice detector on | first dictation ~0.15 s faster | Do it — `Transcriber.warm_up` skips VAD today |
| `beam_size` 5 → 1 | ~20% faster on clips ≥ 60 s, ~nothing on short ones | Only if `tools/asr_bench.py` on real recordings shows no accuracy loss |
| `without_timestamps=True` | 24–35% faster | **Never** — silently dropped whole sentences (175 of 788 words at 5 min) |
| Turn off temperature fallback | no gain | Don't |
| Bigger models on CPU (`medium`, turbo, distil) | 2.4–3× slower than `small` | Not on CPU |

The ~1-second minimum on short clips is the engine's fixed cost: it always
processes a 30-second window (0.78 s of the 1.03 s a 3-second clip takes). Only a
smaller model or a graphics card lowers it — see "Later" below.

---

## 2. Mac

### Where it stands

The macOS port is complete on paper and its automated tests pass on GitHub's
Apple-chip runners, but it has **never run on a real Mac** and no `.app` has
ever been built. CI cannot exercise real windows, permissions, the microphone,
the speech model, or packaging. There is no Mac download.

**Confirmed** below means the conductor read the code and the problem is there.
**Reported** means a review agent found it and the session must confirm it
first. Either way the project rule stands: reproduce with a test before fixing.

### Likely showstoppers (fixable without a Mac)

| # | Problem | Where | Status |
| --- | --- | --- | --- |
| S1 | **The pill can steal focus.** `_apply_state` calls `raise_()` on every state change, and Qt's Cocoa `raise()` also activates the app (`QT_MAC_SET_RAISE_PROCESS` defaults on). The user's app can lose focus mid-dictation and the paste lands nowhere. Use `orderFrontRegardless` on macOS. | `rekounts/ui/overlay.py:307` | Confirmed in code. Confirm on hardware in 2 minutes: dictate into TextEdit and watch whether its window greys out |
| S2 | **First launch copies the whole repo.** On macOS the "old data folder" is `~/Rekounts`; the quickstart clones to `~/rekounts`, and macOS disks ignore case, so the migration copies `.git`, `.venv` (~800 MB) and the source into Application Support. Nobody ever had Mac data at the old location — drop the macOS legacy migration. | `rekounts/paths.py:60-61`, `rekounts/migrate.py:238-252`, `docs/macos-quickstart.md:75` | Confirmed in code; reproduced by simulation |
| S3 | **The model download fails on python.org Python.** Downloads use `urllib` with the default certificate store, which python.org's macOS Python lacks until "Install Certificates.command" is run — and the quickstart points people to python.org. Use certifi's bundle explicitly (this also matters inside a packaged `.app`). | `rekounts/models.py:352-353`, `rekounts/ui/tray.py:127-131` | Confirmed in code |

### Keyboard differences

| # | Problem | Where | Status |
| --- | --- | --- | --- |
| K1 | **The Settings hotkey box swaps Cmd and Control.** Qt on macOS reports Command as `Key_Control` and Control as `Key_Meta`, and the map assumes Windows. Custom hotkeys are saved as the wrong keys; the default Ctrl+Cmd only survives because it uses both. | `rekounts/ui/settings_page.py:60-65` | Confirmed in code |
| K2 | **No Fn/🌐 key** — the standard Mac dictation key, and Wispr Flow's default. pynput 1.7.7 only ever reports Fn (keycode 63) as a release, and Qt sends no event for it. Needs custom handling of the secondary-Fn flag, plus telling users to set *System Settings → Keyboard → "Press 🌐 key to" → Do Nothing*. | pynput `keyboard/_darwin.py` (`_MODIFIER_FLAGS`), `rekounts/hotkey_manager.py` | Confirmed in pynput's source |
| K3 | **F-keys are brightness, volume and media keys** on Mac keyboards. The hotkey warning recommends "an F-key", but F8 plays music; the test plan's F8 step needs fn held. | `rekounts/hotkey_manager.py:146-149`, `docs/macos-one-hour.md`, `MACOS-TESTING.md` §2 | Confirmed |
| K4 | **Option + a letter types a symbol** (Option+D = ∂) into the focused app, because the hotkey is never swallowed. Warn about Option combos on Mac. | `hotkey_warning` in `rekounts/hotkey_manager.py` | Confirmed (macOS behavior) |
| K5 | **Secure Keyboard Entry** (a Terminal/iTerm option, and on automatically in password fields) silently blocks every global hotkey. Detect it (`IsSecureEventInputEnabled`) and explain — especially when the watchdog sees keys held but no events arrive. | new | Not handled anywhere |
| K6 | Paste sends the physical "V" key position, which is wrong on Dvorak-style layouts. | `rekounts/text_inserter.py:408, 548` | Confirmed in code; minor |
| K7 | Left/right-specific modifiers (e.g. "Right Option only", a popular Mac choice) can't be chosen. | `rekounts/hotkey_manager.py` | Nice-to-have |
| K8 | The Scratchpad has no Cmd+B/I/U or Cmd+W/M and the Hub has no Cmd+W. In the hotkey box, Cmd+Q quits the app and Cmd+Space/Cmd+Tab can't be captured. | `rekounts/ui/scratchpad.py`, `rekounts/ui/dashboard.py`, `rekounts/ui/settings_page.py` | Reported |
| K9 | Does the double-tap gesture collide with macOS's own Dictation shortcut (e.g. "Press Control key twice")? | — | Check on hardware |

### Other Mac problems

| # | Problem | Where | Status |
| --- | --- | --- | --- |
| O1 | Permission onboarding is only a tray notification. It needs a real first-run window: three rows with live checkmarks, buttons that deep-link to the right Privacy pane, the system "request" prompts, and a relaunch after Input Monitoring is granted. | `rekounts/permissions.py`, `rekounts/ui/tray.py:452-458`, `rekounts/__main__.py:1420` | Confirmed (toast only). Reported: the toast may not show at all on a Mac (from source it comes from "Python", Focus mode hides it, the notifications switch turns it off) |
| O2 | The Hub, Scratchpad and Feedback windows opened from the menu bar may open behind the current app (macOS 14+ refuses activation for menu-bar-only apps). Activate explicitly. | `rekounts/ui/dashboard.py:625-629`, `rekounts/ui/scratchpad.py:662-671` | Reported |
| O3 | The mic list never refreshes on macOS (PortAudio freezes its device table at startup): AirPods connected later never appear, "System default" means "default at launch", and if that mic disappears recording fails until restart. | `rekounts/device_utils.py`, `rekounts/audio_recorder.py` | Reported |
| O4 | Fonts set in points render ~25% smaller on macOS (Qt treats 1 pt as 1 px there): Scratchpad note text ~10 px, pill hints ~9 px. Use pixel sizes. | `scratchpad.py:249-250, 306-308`, `overlay.py:458-462, 649-651`, `dashboard.py:269, 707-708` | Reported |
| O5 | No dark appearance is forced: light-mode dialogs can show near-white text on light backgrounds, a light title bar sits on the charcoal Hub, and there may be blue focus rings and doubled shadows. | `rekounts/ui/theme.py` | Reported |
| O6 | The menu-bar icon is the solid charcoal app tile, not a monochrome template icon, so it reads as a blob and doesn't adapt to light/dark menu bars. | `rekounts/ui/tray.py:179`, `rekounts/ui/branding.py:30`, `tools/make_icon.py` | Reported |
| O7 | Windows wording on a Mac: "Tray notifications", "from the tray menu", `%USERPROFILE%` in diagnostics, and the mic Test says "muted" when macOS actually denied the mic. | `settings_page.py:761-775, 878, 977`, `feedback.py:85`, `migrate.py:257` | Reported |
| O8 | Sound cues via `afplay` can play the wrong tone (file names collide) or switch off for the session after one hiccup. Consider `NSSound`. | `rekounts/sounds.py:238-247, 351-357` | Reported |
| O9 | Launch-at-login from source runs `.venv/bin/python` directly, so macOS asks for permissions for "Python", not the terminal the user granted. A downloaded unsigned `.app` gets moved to a temporary path by macOS (App Translocation), which breaks the login item. | `rekounts/startup.py:62-77, 286-303` | Reported |
| O10 | The Scratchpad refuses close events, so Quit (and macOS log-out/restart) can need a second try. | `rekounts/ui/scratchpad.py:861-870` | Reported; may affect Windows too |
| O11 | Opening Rekounts again while it is running shows nothing (it should show the Hub). From source the app is called "Python" everywhere and has a Dock icon. | `rekounts/__main__.py:849-851` | Reported |
| O12 | Packaging: no `.app` has ever been built. Unsigned/ad-hoc builds get a new identity every build, so users re-grant all three permissions after every update; macOS 15 removed the right-click → Open bypass (the docs are out of date); the spec builds Apple-chip only; and a menu-bar-only app plus a silent ~486 MB first download looks dead for minutes. | `Rekounts-macos.spec:98-104`, `docs/macos-packaging.md:42-52` | Reported |
| O13 | Install: `requirements.txt` doesn't pin ctranslate2, onnxruntime or tokenizers; Intel Macs have never been tried; the quickstart links Python 3.12.0 and has no Homebrew route; "⇧⌘4 to the clipboard" should be ⌃⇧⌘4. | `requirements.txt`, `docs/macos-quickstart.md`, `docs/macos-one-hour.md` | Reported |

### Speed on a Mac

The speech engine (CTranslate2) has no Mac graphics support, so Macs always
transcribe on the CPU — session A's background transcription matters even more
there. Session D adds a CI job that loads the model on GitHub's Apple-chip runner
and times a clip, so there are real Mac numbers before anyone touches hardware.
If Macs are still slow after that, an Apple-chip engine (MLX Whisper) is the
follow-up.

### Already handled well — don't redo

- The pill never takes keyboard focus (`WindowDoesNotAcceptFocus` +
  `WA_ShowWithoutActivating`), stays visible while another app is active
  (`WA_MacAlwaysShowToolWindow`), and has a kill switch for its native tweaks
  (`REKOUNTS_MAC_OVERLAY_NATIVE=0`).
- Data lives under `~/Library/Application Support/Rekounts`; a file lock
  prevents a second instance; folders open via `QDesktopServices`.
- `platform_text` already names Cmd/Option correctly and hides the GPU row on Mac.
- The paste path waits for physical modifiers to lift and restores every
  pasteboard type.
- The spec already sets `LSUIElement`, the microphone usage string, the bundle
  id and the icon; the entitlements are minimal.
- Scratchpad dictation writes into the note directly — no paste, no
  Accessibility needed.
- The docs are honest that nothing is hardware-verified. `MACOS-TESTING.md` and
  `docs/macos-one-hour.md` are the checklist for the hardware pass.

---

## 3. Sessions

Wave 1 runs in parallel. File ownership is strict so the four branches don't
conflict; anything outside a session's list goes through the conductor.

| Session | Scope | Owns | Done when |
| --- | --- | --- | --- |
| **A. Speed** | Step timing in the log; background transcription in ≤ 20 s pieces; `cpu_threads=8`; VAD warm-up; the beam-size call via `tools/asr_bench.py`; a committed latency benchmark tool; the new cap default (decision 4) | `rekounts/controller.py`, `rekounts/transcriber.py`, `rekounts/audio_recorder.py`, a new chunking module, `rekounts/config.py`, `rekounts/__main__.py`, a new tool under `tools/` | A 5-minute dictation waits ≤ ~2 s on the reference PC; no accuracy regression on real recordings; ✕ still discards everything; tests green |
| **B. Mac keyboard** | K1–K8 (K7 optional), Mac-aware hotkey warnings, the Secure Keyboard Entry notice, Fn/🌐 support (default per decision 3), and the `settings_page.py` wording items from O7 | `rekounts/hotkey_manager.py`, `rekounts/ui/settings_page.py`, `rekounts/text_inserter.py` (mac backend), `rekounts/ui/platform_text.py` | Every K item reproduced in a test first, then fixed; Windows behavior unchanged |
| **C. Mac must-fix + looks** | S1–S3, O2–O8 (minus the `settings_page.py` wording), O10 | `rekounts/ui/overlay.py`, `rekounts/paths.py`, `rekounts/migrate.py`, `rekounts/models.py`, `rekounts/ui/tray.py`, `rekounts/ui/dashboard.py`, `rekounts/ui/scratchpad.py`, `rekounts/ui/theme.py`, `rekounts/ui/branding.py`, `tools/make_icon.py`, `rekounts/device_utils.py`, `rekounts/sounds.py`, `rekounts/feedback.py`, `rekounts/startup.py` | Showstoppers fixed with regression tests; screenshots of the Hub, pill and Scratchpad at Mac sizes in the PR (the maintainer judges these visually) |
| **D. Mac app + checks** | Build `Rekounts.app` in CI on the Apple-chip runner and check its Info.plist; a CI job on the real macOS window server that checks the pill doesn't activate the app and the Scratchpad can become active; load the model after Qt and time a clip (real Mac speed numbers); a stable self-signed identity for test builds; the O12–O13 doc fixes | `Rekounts-macos.spec`, `packaging/`, `.github/workflows/`, `requirements.txt`, `docs/macos*.md`, `MACOS-TESTING.md` | CI produces a downloadable test `.app` and the new checks run green |

**Wave 2 — E. Mac first-run window** (O1, plus Fn/🌐 setup guidance if decision 3
picks Fn). Owns `rekounts/permissions.py`, a new `rekounts/ui/onboarding.py`, and
the hooks in `rekounts/__main__.py` and `rekounts/ui/tray.py`, so it starts after
A and C merge.

**Wave 3 — F. Hands-on test on a real Mac (~2 hours)** of the CI-built `.app`,
using `docs/macos-one-hour.md` and `MACOS-TESTING.md`, then fixes. After that: a
signed, notarized release (decision 2) and a "Download for Mac" button on
rekounts.com — with a stable-named asset, like the Windows one, so the button
never 404s.

**Later, optional:**

- **G.** A graphics-card add-on for Windows/NVIDIA: measured ~3.5× faster for
  `small`, and it makes `large-v3-turbo` practical (see `docs/accuracy.md`). The
  installed build is CPU-only today.
- **H.** An Apple-chip speech engine (MLX Whisper), if Mac speed disappoints
  after A and F.
- **I.** faster-whisper 1.0.3 → current (newer voice detector, batched mode).
  Regression-test the phantom filter carefully.

---

## 4. Decisions needed before starting

1. **Mac access.** Is there a Mac available, even borrowed for ~2 hours — and
   is it Apple-chip (M1–M4) or Intel? *Recommendation:* support Apple-chip Macs
   only.
2. **Apple Developer account ($99/year)** for a signed, notarized Mac download.
   Without it macOS warns loudly and users re-grant permissions after every
   update. *Recommendation:* yes, before the Mac version goes public; testers
   use the CI build until then.
3. **Mac default hotkey:** Ctrl+Cmd (same as Windows) or Fn/🌐 (what Mac users
   expect; Wispr Flow's default). *Recommendation:* ship Fn as an option in
   session B, and make it the default only after the hands-on test proves it.
4. **Recording cap after session A:** 30 or 60 minutes (today it is 10).
   *Recommendation:* 30, still adjustable in Settings.

---

## Appendix: how the speed numbers were measured

**Real use.** Each History entry's timestamp (written after the paste) was
paired with faster-whisper's `Processing audio with duration …` log line (written
when transcription starts) for the clip of the same length. Only timings and
lengths were read — never transcript text.

**Benchmark.** A 925-word passage read by Windows' built-in voice (~154
words/minute) was cut at pauses into clips and transcribed with the app's exact
call — `small`, int8, CPU, `beam_size=5`, `condition_on_previous_text=False`, VAD
`threshold=0.3` and `min_silence_duration_ms=500` — on faster-whisper 1.0.3 and
ctranslate2 4.8.1, the versions the installed build ships. Medians, in seconds:

| Clip | Baseline | beam 1 | 8 threads | 16 threads | beam 1 + 8 threads |
| --- | --- | --- | --- | --- | --- |
| 3.4 s | 1.03 | 0.99 | 0.93 | 0.96 | 0.92 |
| 11 s | 1.37 | 1.27 | 1.24 | 1.44 | 1.16 |
| 30 s | 2.39 | 2.72\* | 2.30 | 2.98 | 2.53\* |
| 60 s | 5.64 | 4.52 | 5.29 | 6.52 | 4.26 |
| 121 s | 10.30 | 8.21 | 9.77 | 12.28 | 7.65 |
| 301 s | 24.07 | 18.90 | 22.76 | 28.48 | 17.88 |

\* Greedy decoding left one sentence unfinished on this clip and needed a second
30-second window.

Where the time goes on the 5-minute clip: encoder 8.7 s (a fixed ~0.78 s per
30-second window), decoder 13.9 s, voice detection 1.2 s, preprocessing 0.2 s.

Other models on the 60 s clip, CPU: `base` 1.88 s · `small` 5.64 s · `medium`
16.73 s · `distil-large-v3` 13.35 s · `large-v3-turbo` 14.22 s.

**Streaming simulation** on the 5-minute clip, cut at the first pause after
15 s with a 30 s maximum (18 pieces of 15–21 s plus a 2.6 s tail): final wait
1.01 s; every piece transcribed at 0.08–0.10× real time; 5 of 788 words differed
from the whole-clip result; word error against the script was 1.0% in pieces vs
1.1% whole.
