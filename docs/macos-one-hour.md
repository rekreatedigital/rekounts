# One hour on a MacBook

Use the matching Intel or Apple Silicon test app from a successful Actions run.
Move it to `/Applications`, then follow [the quickstart](macos-quickstart.md).
Record the chip, macOS version and build/commit before testing. The dependency
floor is macOS 13; native CI uses macOS 15 (Intel) and 26 (Apple Silicon).

1. **Permissions (10 minutes).** Start without grants. Check that the setup
   window appears even with notifications off. Grant Input Monitoring,
   Accessibility and Microphone, then quit and reopen. From source, grant and
   reopen the terminal instead.
2. **Dictation (10 minutes).** In TextEdit, hold Ctrl+Cmd for a sentence and then
   for 30 seconds. Check double-tap hands-free and cancel/finish. Use Ctrl+Cmd
   initially; function keys can control media on a MacBook.
3. **Focus and note (10 minutes).** Watch TextEdit during pill state changes:
   it must stay active. Open the Scratchpad, type and dictate into it, then
   focus TextEdit and dictate there while the note stays visible. Close/reopen
   the note and quit/restart the app; content must survive.
4. **Clipboard and denial (10 minutes).** Copy an image using
   Control+Shift+Cmd+4, dictate, then paste manually: the image should survive.
   Revoke Accessibility while running and retry: History must say undelivered,
   with a notice naming the missing permission.
5. **Daily use (20 minutes).** Try Safari, another text app, AirPods/USB mic
   connection after startup, a full-screen app, another Space, and sleep/wake.
   Record what worked and what failed, including time from stopping to insertion.

Fill the corresponding items in [MACOS-TESTING.md](../MACOS-TESTING.md). A pass
from source does not prove the packaged accessory app works, and one architecture
does not establish the other. Login, signed upgrades and older macOS deployment
versions need separate checks.
