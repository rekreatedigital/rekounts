# Mac troubleshooting context

Copy this along with the exact problem when asking for help:

> I am testing Rekounts, an offline dictation app at
> https://github.com/rekreatedigital/rekounts. Mac support is experimental.
> The target is Apple Silicon and Intel on macOS 13+, with Python 3.11/3.12
> from source. Please first establish my chip, macOS version, build/commit,
> whether I use the packaged app or source, and the exact failed step.
>
> The default hotkey is Ctrl+Cmd: hold/release for push-to-talk, double-tap
> for hands-free and tap to stop. Fn/Globe alone is unsupported; F-keys may
> control media, and Option-letter combinations may type symbols.
>
> Permissions… in the menu bar shows Input Monitoring, Accessibility and
> Microphone, with request buttons and links to System Settings. From source,
> grants generally belong to my terminal/editor; the packaged app uses
> Rekounts. Quit and reopen after changing Input Monitoring; from source,
> reopen the terminal too. A positive preflight is not proof a hotkey works.
>
> First launch downloads about 486 MB before Qt opens, so the interface can
> take minutes to appear. Data and logs live under
> ~/Library/Application Support/Rekounts/. The latest code bundles certificate
> roots for verified TLS and no longer migrates ~/Rekounts (which may be the repo).
>
> Dictation stays local and uses the CPU. Failed pastes are recoverable in
> History when enabled. Missing Accessibility is reported as undelivered.
> Native CI checks model loading, pill focus and Scratchpad routing, but real
> microphone input, granted global hotkeys, other-app paste, Spaces, hot-plug
> audio and signed upgrades still need hardware observation. Please consult
> docs/macos.md and MACOS-TESTING.md, and do not assume a mocked test proves
> behavior on this Mac. The log is logs/rekounts.log under the data folder;
> it contains no dictated text.
