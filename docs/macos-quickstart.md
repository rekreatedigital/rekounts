# Try Rekounts on a MacBook

The target is **Apple Silicon (M1 or newer) and Intel Macs running macOS 13 or
newer**. Mac support is still experimental; the download is a preview.
Passing automated tests does not replace a real dictation test on your Mac.

## Use a test app

Start with [the free Mac preview and installation guide](macos-preview.md).
It has separate Apple Silicon and Intel disk images and a short hands-on test.
No Python installation or Apple Developer membership is needed to try it.

For newer development builds:

After the Mac jobs pass in [GitHub Actions](https://github.com/rekreatedigital/rekounts/actions),
their artifacts contain separate `arm64` and `x86_64` test apps. Choose `arm64`
for Apple Silicon or `x86_64` for Intel. Apple menu → **About This Mac** shows
which processor you have.

Extract the ZIP and move **Rekounts.app** to **Applications** before opening it
or enabling launch at login. These test builds are ad-hoc signed and have not
been notarized. If macOS blocks one, follow
[Apple's instructions](https://support.apple.com/en-us/102445) for a trusted app;
do not disable Gatekeeper globally. A test build may need permissions granted
again after an update.

## Run from source instead

You need **Python 3.11 or 3.12**. The pinned PySide6 6.7.2 does not support Python
3.13+. If you use Homebrew, `brew install python@3.12` provides a separate Python
3.12. Python's [Mac downloads](https://www.python.org/downloads/macos/) also list
the universal installers. Use `python3.12` explicitly so macOS's older Python
or a newer incompatible Python is not selected accidentally.

Open Terminal and run each line:

```sh
cd ~
git clone https://github.com/rekreatedigital/rekounts.git
cd rekounts
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
QT_QPA_PLATFORM=offscreen python -m pytest -q
python -m rekounts
```

If you already have a checkout, use it instead of cloning again. The tests
should report no failures. Leave Terminal open while Rekounts runs.

## First launch and permissions

The first launch downloads the default speech model (about 486 MB) before the
interface appears. This can take several minutes. Later launches reuse it and
dictation works offline. Data lives in
`~/Library/Application Support/Rekounts/`.

Look for the Rekounts icon in the menu bar. The setup window appears when a
permission is denied or unconfirmed; you can always reopen **Permissions…**
from that menu. Use its **Allow…** and **Open Settings** buttons for:

1. **Input Monitoring** — reading the global hotkey.
2. **Accessibility** — pasting your words into other apps.
3. **Microphone** — hearing your voice.

For the test app, enable **Rekounts**. From source, enable **Terminal**, iTerm
or the editor you launched it from; Rekounts usually will not have a separate
entry. After changing Input Monitoring, quit and reopen Rekounts. From source,
quit and reopen the terminal too, then run:

```sh
cd ~/rekounts
source .venv/bin/activate
python -m rekounts
```

## Check that it works

Open TextEdit with an empty document. Hold **Ctrl+Cmd**, say a sentence and let
go. Your words should appear there. Then try a 30-second hold, double-tap for
hands-free, and dictation into the Scratchpad from the menu bar.

Use Ctrl+Cmd first: MacBook function keys normally control media or brightness,
and Option with a letter can type a symbol. Fn/Globe alone is not supported.
Secure Keyboard Entry and password fields can prevent global hotkeys.

If text does not arrive, check Permissions and the Hub's History. Record your
chip, macOS version, app/source build, exact step and result in
[MACOS-TESTING.md](../MACOS-TESTING.md). The log is
`~/Library/Application Support/Rekounts/logs/rekounts.log`; it does not contain
your dictation text. [This help prompt](macos-help-prompt.md) includes the
context needed to troubleshoot.
