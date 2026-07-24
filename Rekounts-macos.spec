# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for Rekounts on macOS (groundwork — NOT yet verified on
real hardware; see MACOS-TESTING.md and docs/macos-packaging.md).

Produces dist/Rekounts.app — a menu-bar (tray) app with no Dock icon:

  * LSUIElement=1: agent app — no Dock tile, no menu bar takeover; the app
    lives in the status bar, exactly like the Windows tray build.
  * NSMicrophoneUsageDescription: REQUIRED — without it macOS kills the
    process outright the first time the mic is opened (no prompt, no error).
  * The Whisper model is NOT bundled — it downloads once on first run to
    ~/Library/Application Support/Rekounts/models/<name>, exactly like the
    source build (see rekounts/models.py).

Import-order landmine (see rekounts/__main__.py): Qt must not load before the
Whisper model, or ctranslate2's and Qt's OpenMP runtimes collide. The frozen
app preserves this because it runs the same __main__.py.

Build (on a Mac):  .venv/bin/python -m PyInstaller --clean Rekounts-macos.spec

Signing/notarization are deliberately NOT attempted here — they need the
owner's Apple Developer account. The full procedure is documented in
docs/macos-packaging.md.
"""
import os
import re

from PyInstaller.utils.hooks import collect_all

datas, binaries, hiddenimports = [], [], []


def _read_version() -> str:
    src = open(os.path.join("rekounts", "__init__.py"), encoding="utf-8").read()
    m = re.search(r'^__version__\s*=\s*["\']([^"\']+)["\']', src, re.M)
    if not m:
        raise SystemExit("Could not find __version__ in rekounts/__init__.py")
    return m.group(1)


_VERSION = _read_version()

# Native / data-heavy deps: bundle their dylibs, data files (the silero VAD
# model, PortAudio) and submodules wholesale so nothing is missed.
for _pkg in ("ctranslate2", "faster_whisper", "onnxruntime", "av",
             "sounddevice", "_sounddevice_data", "tokenizers", "huggingface_hub"):
    _d, _b, _h = collect_all(_pkg)
    datas += _d
    binaries += _b
    hiddenimports += _h

a = Analysis(
    ["rekounts/__main__.py"],
    pathex=["."],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports + ["rekounts"],
    hookspath=[],
    runtime_hooks=[],
    excludes=[
        # CPU-only build: keep CUDA/GPU stacks out.
        "nvidia", "torch", "triton", "tensorflow", "jax",
        # Dev/test-only or unused at runtime.
        "pytest", "_pytest", "setuptools", "pip",
        "tkinter",
        # Qt modules the app never touches (only QtCore/QtGui/QtWidgets).
        "PySide6.QtQml", "PySide6.QtQuick", "PySide6.Qt3DCore",
        "PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets",
        "PySide6.QtMultimedia", "PySide6.QtCharts",
        "PySide6.QtDataVisualization", "PySide6.QtWebSockets",
    ],
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="Rekounts",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,        # build arch = host arch; universal2 needs fat wheels
    codesign_identity=None,  # unsigned groundwork build; see docs/macos-packaging.md
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="Rekounts",
)

app = BUNDLE(
    coll,
    name="Rekounts.app",
    icon=None,               # no .icns designed yet (matches the Windows spec)
    bundle_identifier="com.rekreatedigital.rekounts",
    version=_VERSION,
    info_plist={
        # Agent app: menu-bar only, no Dock icon — the macOS analogue of the
        # Windows tray-only build.
        "LSUIElement": True,
        # REQUIRED: without this key macOS terminates the app the moment the
        # microphone is opened, with no prompt and no catchable error.
        "NSMicrophoneUsageDescription":
            "Rekounts records your voice only while you hold the dictation "
            "hotkey, transcribes it locally on this Mac, and never sends "
            "audio anywhere.",
        "NSHumanReadableCopyright":
            "Copyright (C) 2026 Rekreate Digital. GPL-3.0.",
        "LSMinimumSystemVersion": "12.0",
        "NSHighResolutionCapable": True,
    },
)
