# macOS packaging: signing & notarization (documented, not yet attempted)

`Rekounts-macos.spec` builds an **unsigned** `dist/Rekounts.app` (LSUIElement
agent app, `NSMicrophoneUsageDescription` included). Unsigned is fine for
development on your own Mac, but distribution needs Developer ID signing and
notarization — both require the project owner's Apple Developer account
($99/yr), which is why this step is documented here rather than automated.

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

PyInstaller apps under the hardened runtime need at least
(`packaging/entitlements.plist`, to be created at signing time):

```xml
<key>com.apple.security.cs.allow-unsigned-executable-memory</key><true/>
<key>com.apple.security.cs.disable-library-validation</key><true/>
<key>com.apple.security.device.audio-input</key><true/>
```

The first two are required by CPython/ctypes/onnxruntime under the hardened
runtime; the third declares mic use. Do **not** add entitlements beyond these
— every extra one is attack surface and notarization review friction.

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
