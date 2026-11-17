# Install the free Mac preview

Download from the [0.4.4 preview release](https://github.com/rekreatedigital/rekounts/releases/tag/v0.4.4-preview.1).
This preview is for testing on a real Mac before a supported Mac release.
It is not Developer ID signed or notarized by Apple. You do not need an Apple
Developer membership or payment to try it.

## Choose your download

Open Apple menu → **About This Mac**:

| What it says | Download |
| --- | --- |
| Chip: Apple M1 or newer | `Rekounts-macos-arm64-preview.dmg` |
| Processor: Intel | `Rekounts-macos-x86_64-preview.dmg` |

Both require macOS 13 or newer. Automated checks ran on macOS 15 (Intel) and
26 (Apple Silicon). macOS 13 and 14, microphone capture, the global hotkey and
pasting into other apps still need hands-on testing. This is a Mac desktop
app; it is not an iPhone or iPad app.

## Install and open

1. Open the downloaded `.dmg` file. Drag **Rekounts.app** onto **Applications**.
2. Eject the disk image, then open Rekounts from Applications.
3. If macOS blocks it, and you trust the download, open **System Settings →
   Privacy & Security → Open Anyway** for Rekounts after the first launch
   attempt. Confirm Open. Follow [Apple's current instructions](https://support.apple.com/en-us/102445).
   Managed Macs may not permit this exception. Do not disable macOS security
   globally or run Terminal commands to remove its checks.
4. Wait for the first speech-model download (about 486 MB). The interface can
   take several minutes to appear. Later launches reuse that model.
5. In Rekounts' Permissions window, allow **Microphone**, **Accessibility** and
   **Input Monitoring**. You can reopen Permissions from its menu-bar icon.
6. Quit and reopen Rekounts after granting access.

## A short first test

1. Open TextEdit and click in a new document. Hold **Control + Command**, speak
   a short sentence, and release. Confirm the words appear in TextEdit.
2. Try a browser text box. The small recording pill should not take focus
   away from the text field.
3. Copy some text, dictate another sentence, then paste manually. Confirm your
   original clipboard text is still there.
4. Open Scratchpad from the Rekounts menu. Dictate into it, close it, and reopen
   it. Confirm the note is preserved.
5. Quit, turn Wi-Fi off, reopen, and dictate again using the downloaded model.

Reply with your Mac chip, macOS version and which steps passed or failed.
For example: `M2 / macOS 15.7 / TextEdit passed / browser paste failed`.
Avoid including private dictation. A fuller checklist is in
[MACOS-TESTING.md](../MACOS-TESTING.md).

The current app reports version **0.4.4**, published as `v0.4.4-preview.1`.
It includes background preparation for longer dictations: recognition uses the
same selected model and accuracy settings, and the complete text appears once
you stop. See the [release notes](https://rekounts.com/preview.html#changes).

To update an existing Mac installation, quit Rekounts, drag the new app into
Applications and choose Replace, then reopen it. Settings and history stay in
your user data folder. Updating an ad-hoc signed preview may require granting
permissions again.

This preview is separate from the stable Windows download. **Check for Updates**
opens a release page; it does not install an update itself, and the stable update
check does not offer prereleases. Use the [Mac download page](https://rekounts.com/mac.html)
to get this preview.
