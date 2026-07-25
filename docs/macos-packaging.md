# macOS packaging: signing & notarization (documented, not yet attempted)

`Rekounts-macos.spec` builds an **unsigned** `dist/Rekounts.app` (LSUIElement
agent app, `NSMicrophoneUsageDescription` included, `assets/icon.icns` as the
bundle icon). Unsigned is fine for development on your own Mac, but distribution
needs Developer ID signing and notarization — both require the project owner's
Apple Developer account ($99/yr), which is why this step is documented here
rather than automated.

## What is done, and what the $99 buys

Everything that needs no Apple account is in the repo already:

| Piece | State |
| --- | --- |
| `Rekounts-macos.spec` | written; LSUIElement, mic usage string, CPU-only excludes |
| `assets/icon.icns` | **generated and committed** (`tools/make_icon.py`), all ten iconutil OSTypes, 16→1024 px |
| `packaging/entitlements.plist` | **written and reviewed**; three entitlements, reasoning for each and for every one left out |
| the procedure below | written |
| a build | never run — no Mac |
| a signature | needs the account |
| notarization | needs the account |

So the account is the *only* remaining blocker for a distributable `.app`, and
the work it unblocks is running the commands below, not figuring them out.

### The bill, exactly

* **Apple Developer Program — $99/year, per account, recurring.** There is no
  one-off option and no free tier that produces a notarizable build. Let it
  lapse and the certificate stops being valid for *new* signatures; builds
  already notarized and stapled keep working.
* **Enrolment takes 24–48 h** in practice (identity verification), sometimes
  longer for a company entity. As Rekreate Digital rather than an individual it
  also needs a D-U-N-S number, which is free but is its own multi-day wait — if
  a company enrolment is the intent, start that first, not last.
* A Mac is required for the signing and notarization steps themselves
  (`codesign`, `xcrun notarytool`, `stapler` are macOS-only). It does not have
  to be a *purchased* Mac — an hour on a borrowed one is enough per release —
  but it cannot be this Windows box, and it cannot be a GitHub runner without
  putting the signing certificate into repository secrets.
* **Nothing here costs anything to keep unsigned.** An unsigned app runs fine
  after a right-click → Open; the cost is paid in the friction described under
  "Why it matters more for THIS app", not in money.

## Why it matters more for THIS app

The TCC permissions Rekounts depends on (Input Monitoring, Accessibility,
Microphone) are tied to the app's **code signature**. An unsigned or ad-hoc
signed build gets its grants invalidated every time the binary changes, so
users would re-grant three permissions after every update. A stable Developer
ID signature makes the grants stick across updates.

## One-time setup (owner)

1. Enroll in the Apple Developer Program with the Rekreate Digital account.
2. In Xcode (or developer.apple.com), create a **Developer ID Application**
   certificate and install it in the login keychain of the build Mac.
3. Create an app-specific password for `notarytool`:
   appleid.apple.com > Sign-In and Security > App-Specific Passwords, then
   store it: `xcrun notarytool store-credentials rekounts-notary
   --apple-id <apple-id> --team-id <TEAMID> --password <app-specific-pw>`.

## Per-release procedure

```sh
# 1. Build (on a Mac, from the repo root, venv active)
python -m PyInstaller --clean Rekounts-macos.spec

# 2. Sign every nested binary + the bundle, hardened runtime on
codesign --deep --force --options runtime --timestamp \
  --entitlements packaging/entitlements.plist \
  --sign "Developer ID Application: Rekreate Digital (TEAMID)" \
  dist/Rekounts.app

# 3. Notarize (zip, submit, wait)
ditto -c -k --keepParent dist/Rekounts.app dist/Rekounts.zip
xcrun notarytool submit dist/Rekounts.zip \
  --keychain-profile rekounts-notary --wait

# 4. Staple the ticket so Gatekeeper passes offline
xcrun stapler staple dist/Rekounts.app

# 5. Verify like a user would
spctl --assess --type execute -vv dist/Rekounts.app
```

### Entitlements

**`packaging/entitlements.plist` now exists** — written, commented and pinned by
`tests/test_icon_asset.py`, so the signing command above needs no editing. It
declares exactly three:

```xml
<key>com.apple.security.cs.allow-unsigned-executable-memory</key><true/>
<key>com.apple.security.cs.disable-library-validation</key><true/>
<key>com.apple.security.device.audio-input</key><true/>
```

The first two are required by CPython/ctypes/onnxruntime under the hardened
runtime; the third declares mic use. Do **not** add entitlements beyond these
— every extra one is attack surface and notarization review friction. The file
itself records why each of the tempting extras (`app-sandbox`, `network.*`,
`automation.apple-events`, `allow-jit`) is deliberately absent.

It has never been through a `codesign` run, so treat the *list* as reviewed and
the *outcome* as untested: if the hardened runtime kills the app at import, the
error in Console.app names the missing entitlement, and that is the moment to
add a fourth — with a note saying what demanded it.

### `--deep` caveat

`codesign --deep` is deprecated for complex bundles; if notarization rejects
the build, sign inside-out instead: every `.so`/`.dylib` under
`Rekounts.app/Contents/`, then the `Rekounts` executable, then the bundle,
each with `--options runtime --timestamp`.

## Distribution form

A plain zip of the stapled `.app` is enough for GitHub Releases (`ditto -c -k
--keepParent`). A DMG is cosmetic and can come later. Privacy invariant
reminder: notarization uploads the app TO APPLE for scanning — it adds no
telemetry to the app itself and changes nothing about the app's own
no-network behavior.
