# Building and developing

Running from source, the test suite, and packaging the standalone Windows app.
If you only want to *use* Rekounts, the [README](../README.md) has the installer
and you don't need any of this.

## Building the standalone app

```bat
build.bat
```

One run produces everything a release needs, in `dist\`:

| | |
| --- | --- |
| `Rekounts\Rekounts.exe` | the app (~380 MB — it bundles Python, Qt and the speech engine) |
| `Rekounts-<version>-win64.zip` | the portable download |
| `Rekounts-Setup-<version>.exe` | the installer |

The speech model is *not* bundled; it downloads once on first run from this
project's own release host (see
[Where the speech models come from](#where-the-speech-models-come-from)).

The installer step needs **Inno Setup 6.3 or newer**, a build-time dependency
only — nothing in the app uses it:

```bat
winget install -e --id JRSoftware.InnoSetup
```

Without it, `build.bat` still builds the app and the ZIP, says the installer was
skipped, and exits successfully. `build.bat --no-installer` skips it deliberately.
The installer script itself is [installer/rekounts.iss](../installer/rekounts.iss);
its header explains the three guarantees it exists to keep (no admin, your data
survives an uninstall, one launch-at-login mechanism).

### The icon

`assets/icon.ico` is committed, but generated — regenerate it (and the
installer's wizard bitmaps) with:

```bat
.venv\Scripts\python tools\make_icon.py
```

The mark is the site favicon transcribed into that script, which is the icon's
source of record. The same `.ico` is used by the `.exe`, the tray, the app's
windows, the installer and the Start-menu shortcut.

The same command also writes `assets/icon.icns` — the macOS bundle icon, ten
sizes from 16 to 1024 px. It is generated from the identical mark and committed
like the `.ico`, and writing it needs no Mac.

### Publishing a speech model (maintainers)

Model files are release assets on a separate public repo, so downloads keep
working even while this repo is private. Adding or refreshing one is a single
command:

```bat
.venv\Scripts\python scripts\publish_models.py base      :: fetch, verify, upload
.venv\Scripts\python scripts\publish_models.py --all
.venv\Scripts\python scripts\publish_models.py turbo --hashes --upstream org/repo
```

It fetches the upstream files, checks their SHA256 against the manifest in
`rekounts/models.py` (refusing to publish on a mismatch), and uploads them
with the required license notices. `--hashes` prints the manifest entry for a
model you are adding; `--dry-run` does everything except upload.

## Development

```bat
.venv\Scripts\python -m pytest        :: 1,300+ unit tests
```

CI installs `requirements-test.txt` (a much smaller set than the runtime
`requirements.txt`) and runs the suite on Windows (Python 3.11 and 3.12) plus
`ruff check .`; both are quick enough to run locally the same way. The suite
also runs on Linux and macOS in CI — the app itself is Windows-only, but the
tests fake the Windows-specific pieces, and keeping them green off-Windows
protects the seam a future macOS port will use. Hardware- and UI-dependent
behavior is covered by
[docs/manual-smoke-test.md](manual-smoke-test.md). See
[ARCHITECTURE.md](../ARCHITECTURE.md) for the module map and data flow.

The version string lives in exactly one place, `rekounts/__init__.py`;
`pyproject.toml` and the `.exe`'s file properties both read it from there.
