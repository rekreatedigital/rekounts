# Rekounts on macOS

The Mac target is **Apple Silicon and Intel, macOS 13 or newer**, using Python
3.11 or 3.12 when running from source. This is the dependency floor, not a claim
that every MacBook and macOS release has been tested. The pinned ONNX Runtime
1.23.2 wheels require macOS 13; the previous unqualified macOS 12 claim no longer
matches the dependencies.

**Status: experimental.** Windows remains the published download. A Mac release
needs successful builds on both architectures and a completed
[hardware checklist](../MACOS-TESTING.md). Automated tests cannot grant the
permissions needed to prove real microphone, global hotkey and paste behavior.

For setup, use the [quickstart](macos-quickstart.md). For packaging, use
[the Mac build instructions](macos-packaging.md).

## What the automated checks cover

The [tests workflow](../.github/workflows/tests.yml) has independent
`macos-26` (Apple Silicon) and `macos-15-intel` jobs. Each installs the full
runtime, runs the suite against real PyObjC frameworks, builds a native `.app`,
and checks the bundle's architecture, metadata, certificate bundle and ad-hoc
signature. Each successful job publishes a test ZIP as an Actions artifact.
These are development artifacts, not notarized releases.

`python -m rekounts --mac-smoke-test` and the same command inside the bundle:

- Load a local speech model before Qt and transcribe faster-whisper's JFK test
  clip, checking expected words. This exercises decoding and VAD, not a general
  speech-accuracy or speed benchmark.
- Use the real Cocoa window server to check that the recording pill leaves
  Finder active through idle, recording and processing transitions.
- Activate the Scratchpad under the accessory-app policy, route text into it,
  and close and reopen it without losing the note.
- Construct the permission window and check the bundled native frameworks.

The checks never open the microphone, request permissions, post keyboard events
or upload audio. An unattended runner may not allow Finder to become active.
CI explicitly permits that precondition to be unavailable so packaging can
continue; its JSON reports then say `passed_noninteractive_checks` and list
the untested window behavior. A product assertion still fails the job once the
desktop precondition succeeds. A green run still needs the hands-on checklist.

## Mac behavior

The default `ctrl+win` config token means **Ctrl+Cmd**. Hold to record and release
to insert; double-tap for hands-free, then tap to finish. Settings records the
physical Command and Control keys correctly despite Qt's Mac naming convention.
Option-letter shortcuts can type symbols in other apps; function keys may
control media unless standard function keys are enabled. The app warns about
these choices. Fn/Globe by itself is not supported.

Text is pasted with Cmd+V. The clipboard is restored across all available
formats, including an initially empty clipboard. If Accessibility is explicitly
denied, the dictation is marked undelivered and retained in History, rather than
being recorded as a successful paste. A posted paste still cannot prove that
the receiving app accepted it.

The pill uses native window ordering on macOS so a state change does not activate
Rekounts. The Hub and Scratchpad explicitly activate when the user opens them.
Closing the Scratchpad preserves it for reopening and permits application quit.

Data lives in `~/Library/Application Support/Rekounts`. No automatic migration
reads `~/Rekounts`: on a case-insensitive disk that can be the source checkout,
including its `.git` and `.venv` folders. Model downloads and update checks use
verified TLS with bundled certificate roots, including in the frozen app.

## Permissions

The **Permissions…** menu opens a persistent setup window with three independent
states and buttons to request access or open the matching Privacy pane:

| Permission | Used for |
| --- | --- |
| Input Monitoring | Global dictation hotkey |
| Accessibility | Pasting into other apps |
| Microphone | Recording your voice |

The window appears after startup when a state is denied or unconfirmed. It works
even when tray notifications are disabled. An unknown state is labeled **Not
confirmed**, not denied. After changing Input Monitoring, quit and relaunch.

From source, macOS generally attributes access to the terminal or editor that
launched Python. Enable that app, then quit and reopen it too. A packaged `.app`
has its own identity. Source launch-at-login uses Python directly and can have a
different permission identity; validate login behavior with the packaged app.

Preflight answers are not proof of delivery: CI has returned `True` for Input
Monitoring without an interactive grant. The long-hold test remains required.

## Remaining limits and release gates

- Hardware tests are outstanding for both architectures, including permissions
  granted and denied, external microphones/AirPods, Spaces, full-screen apps,
  sleep/wake, login and Secure Keyboard Entry.
- First startup downloads the model before Qt opens; the UI can take several
  minutes to appear. This follows the existing native-library import-order
  constraint and still needs better progress feedback.
- The current engine uses the CPU on Mac; it has no Apple GPU backend.
- Focus tracking is per application, not per window within one application.
- Letter hotkeys and the paste key assume a US/ANSI-compatible keyboard layout.
- Developer ID signing, notarization, permission persistence across upgrades
  and Gatekeeper testing remain release requirements.

The older [Mac and speed audit](plans/2026-10-07-mac-and-speed.md) is a historical
snapshot. The checklist and actual CI reports are the record of verification.
