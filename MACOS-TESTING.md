# Mac hardware acceptance checklist

Keep a separate result for **Apple Silicon and Intel**, and for each macOS
version claimed as supported. The dependency floor is macOS 13; CI currently
runs on macOS 15. A checkbox stays empty until somebody observes it on hardware.

Record: commit/build, chip, macOS version, keyboard layout, source or `.app`,
microphone, date, tester. Include the CI run URL and its two smoke reports when
using an Actions artifact. There is no completed hardware run recorded here yet.

## Install and first launch

- [ ] Correct architecture app opens from `/Applications`.
- [ ] Gatekeeper behavior recorded; notarized release passes without an override.
- [ ] First model download completes with no certificate error. Record the wait
      before the interface appears (progress feedback remains a known gap).
- [ ] No source checkout, `.git` or `.venv` is copied into Application Support.
- [ ] Quit/reopen with networking off works using the downloaded model.
- [ ] Menu-bar icon is visible in light and dark mode; one app instance only.

## Permissions, including denial

- [ ] Fresh setup shows Permissions even with notifications disabled/Focus on.
- [ ] Each Allow button requests the right consent; Open Settings goes to the
      matching pane. Unknown states say Not confirmed, not denied.
- [ ] Source instructions name the terminal/editor; packaged app uses Rekounts.
- [ ] Grant Input Monitoring, quit/reopen (terminal too for source), then test
      the hotkey. A passing preflight alone does not count as proof.
- [ ] Deny Microphone: app explains the failure and remains usable.
- [ ] Deny Accessibility: no text inserted; History marks it undelivered and
      the message names Accessibility. Grant it and retry successfully.
- [ ] Revoke Accessibility after startup and repeat: no false delivery success.
- [ ] Close/reopen Permissions from the menu; statuses refresh.

## Dictation and keyboard

- [ ] Ctrl+Cmd hold/release inserts a sentence in TextEdit.
- [ ] Hold for at least 30 seconds: no early release from the watchdog.
- [ ] Double-tap starts hands-free; a tap stops and inserts exactly once.
- [ ] Cancel discards the clip; finish inserts once; the next hotkey still works.
- [ ] Set Command-only and Control-only hotkeys separately. Settings saves and
      responds to the physical key chosen, not the other modifier.
- [ ] Function-key and Option-letter warnings describe actual keyboard behavior.
- [ ] Record conflicts with macOS Dictation shortcuts or Secure Keyboard Entry.
      Fn/Globe alone is not a supported hotkey.
- [ ] After sleep/wake, the hotkey and microphone still work.

## Insertion and clipboard

- [ ] Paste into TextEdit, Safari text input, VS Code and another daily-use app.
- [ ] Accents, emoji, punctuation and a long dictation arrive intact.
- [ ] Copy rich text or an image (Control+Shift+Cmd+4), dictate, then paste
      manually: the original clipboard contents survive.
- [ ] Begin with an empty clipboard: it is still empty after dictation.
- [ ] Copy something during insertion: the user's newer copy is not overwritten.
- [ ] Switch to another app before delivery: no text goes to the wrong app.
      Tracking is per application; switching windows within one app is a limit.
- [ ] If testing the config-only keystroke path, set both
      `insertion_mode="keystroke"` and `long_text_via_paste=false`, and test
      emoji at chunk boundaries. Restore the default paste configuration after.

## Windows and Scratchpad

- [ ] Pill remains visible with another app focused, including during transitions.
- [ ] Clicking finish/cancel does not take focus from the insertion target.
- [ ] Pill works on multiple displays, Spaces and over a full-screen app.
- [ ] Open Hub, Scratchpad and Feedback from the menu: each comes to the front.
- [ ] Type and dictate into Scratchpad; text goes there without using clipboard.
- [ ] Leave Scratchpad visible and focus TextEdit: dictation goes to TextEdit.
- [ ] Cmd+B/I/U format the note, Cmd+W closes it; reopening preserves content.
- [ ] Resize, minimize and drag the note; geometry survives restart visibly.
- [ ] Quit with the note open exits on the first attempt and preserves edits.
- [ ] UI text, dialogs and menu-bar icon are readable in both OS appearances.

## Audio, login and upgrades

- [ ] Built-in mic, a connected headset and the system-default choice work.
- [ ] Connect AirPods/USB mic after launch; record discovery and switching behavior.
      CoreAudio/PortAudio hot-plug behavior is not established by unit tests.
- [ ] Remove the selected mic; recovery is understandable and does not lose data.
- [ ] Sound cues work; switching them off takes effect immediately.
- [ ] Enable launch at login for the installed app; log out/in and dictate.
- [ ] Disable launch at login; next login does not start Rekounts.
- [ ] Upgrade a signed build: settings, History, Scratchpad and model survive,
      and permission grants still work. Ad-hoc CI builds do not establish this.

Attach the log at `~/Library/Application Support/Rekounts/logs/rekounts.log` to
failure reports, plus exact steps and observed behavior. Never mark a hardware
item passed based only on a mocked test or CI preflight answer.
