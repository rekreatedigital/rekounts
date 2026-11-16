# Build and validate the Mac app

Build separately for **Apple Silicon (`arm64`)** and **Intel (`x86_64`)** on a
Mac of the matching architecture. `target_arch=None` selects the host
architecture; it does not produce a universal app. Both builds target macOS 13
or later because of the pinned ONNX Runtime wheels. Native CI currently runs
on macOS 15 (Intel) and 26 (Apple Silicon); older deployment versions still
need hardware testing.

## Development build

In an activated Python 3.11/3.12 virtual environment:

```sh
python -m pip install -r requirements.txt
python -m pip install pyinstaller==6.22.3
python -m PyInstaller --noconfirm --clean Rekounts-macos.spec
python tools/check_macos_bundle.py dist/Rekounts.app
codesign --verify --deep --strict dist/Rekounts.app
```

PyInstaller applies an **ad-hoc signature** when no signing identity is supplied.
This satisfies the executable-signature requirement; it is not Developer ID
signing or notarization. The bundle is a menu-bar app (`LSUIElement`) with its
own microphone purpose string, icon and `com.rekreatedigital.rekounts` identity.
The speech model is downloaded on first normal launch, not included in the app.

The [tests workflow](../.github/workflows/tests.yml) builds both architectures,
checks `lipo`, metadata and signatures, and uploads ZIPs made with `ditto` so
bundle symlinks survive. It runs this native check from source and in the app:

```sh
python -c "from rekounts.models import ensure_model; ensure_model('base')"
mkdir -p build
curl --fail --location --output build/mac-smoke-jfk.flac \
  https://raw.githubusercontent.com/SYSTRAN/faster-whisper/v1.0.3/tests/data/jfk.flac
QT_QPA_PLATFORM=cocoa dist/Rekounts.app/Contents/MacOS/Rekounts \
  --mac-smoke-test \
  --model-dir "$HOME/Library/Application Support/Rekounts/models/base" \
  --audio-file build/mac-smoke-jfk.flac \
  --report build/macos-bundle-smoke.json
```

The check activates Finder and test windows, loads the model, and verifies
overlay focus and Scratchpad routing. It does not record audio, request access,
start a global listener or send keystrokes. Use it in a desktop session.
The command above requires the desktop checks. CI adds
`--allow-unavailable-desktop`: if Finder cannot be activated, reports explicitly
list window checks as untested while model and packaging verification continue.
It does not suppress a Rekounts window failure on an available desktop.

For a manual test, move the app to `/Applications` before opening it. Follow
[Apple's current Gatekeeper guidance](https://support.apple.com/en-us/102445)
for a development build you trust. Do not promise that right-click → Open works
on every macOS version. Check permission grants again after replacing an ad-hoc
build.

## Release signing and notarization

A public release also needs the owner's Developer ID Application identity and
notarization credentials. No credentials are stored or created by this repo.
With the signing certificate already in the build Mac's keychain:

```sh
export REKOUNTS_MAC_SIGNING_IDENTITY="Developer ID Application: YOUR NAME (TEAMID)"
python -m PyInstaller --noconfirm --clean Rekounts-macos.spec
codesign --verify --deep --strict dist/Rekounts.app
ditto -c -k --keepParent dist/Rekounts.app dist/Rekounts-notarize.zip
xcrun notarytool submit dist/Rekounts-notarize.zip \
  --keychain-profile rekounts-notary --wait
xcrun stapler staple dist/Rekounts.app
spctl --assess --type execute -vv dist/Rekounts.app
ditto -c -k --keepParent dist/Rekounts.app dist/Rekounts-macos.zip
```

Configure the `rekounts-notary` keychain profile separately with the owner's
account. The spec passes the identity and `packaging/entitlements.plist` to
PyInstaller, which signs collected binaries and enables hardened runtime.
See [PyInstaller's signing documentation](https://pyinstaller.org/en/stable/feature-notes.html#macos-binary-code-signing).
The final distribution ZIP is recreated after stapling.

Signing, notarization and permission persistence across upgrades are unverified
until tested with the actual identity. Finish [MACOS-TESTING.md](../MACOS-TESTING.md)
on both architectures before publishing a Mac download.
