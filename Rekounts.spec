# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for Rekounts (onedir).

Produces dist/Rekounts/Rekounts.exe — a windowed (no-console) tray app that
bundles Python, PySide6 (Qt), faster-whisper + CTranslate2, and PortAudio so end
users never have to install Python.

CPU-only: NVIDIA/CUDA packages are excluded (see `excludes`). The Whisper model is
NOT bundled — it downloads once on first run to
%APPDATA%\\Rekounts\\models\\<name>, from the project's own release host,
exactly like the source build (see rekounts/models.py).

Import-order landmine (see rekounts/__main__.py): Qt must not load before the
Whisper model, or ctranslate2's and Qt's OpenMP runtimes collide and hard-crash
the process. The frozen app preserves this because it runs the same __main__.py,
which imports Qt only inside main(), after the model is created.

Build:  build.bat   (or  .venv\\Scripts\\python -m PyInstaller --clean Rekounts.spec)

Last verified end-to-end on 2026-07-23 against master c37ac0d — BEFORE the
TalkativeAI -> Rekounts rename, so that pass exercised this spec under the old
name: built clean, reached the started log line, showed the tray icon + pill,
opened the Dashboard, and completed a full record -> VAD -> transcribe cycle.
The renamed build gets the same pass (docs/manual-smoke-test.md, including its
one-time upgrade section) at the v0.3.0 release step.
"""
import os
import re

from PyInstaller.utils.hooks import collect_all
from PyInstaller.utils.win32.versioninfo import (
    FixedFileInfo, StringFileInfo, StringStruct, StringTable, VarFileInfo,
    VarStruct, VSVersionInfo)

datas, binaries, hiddenimports = [], [], []


# --- Version resource --------------------------------------------------------
# Read the ONE version literal (rekounts/__init__.py) by regex rather than
# importing the package: importing it here would drag Qt/ctranslate2 into the
# build process, and pyproject.toml resolves its own version from the same line.
def _read_version() -> str:
    src = open(os.path.join("rekounts", "__init__.py"), encoding="utf-8").read()
    m = re.search(r'^__version__\s*=\s*["\']([^"\']+)["\']', src, re.M)
    if not m:
        raise SystemExit("Could not find __version__ in rekounts/__init__.py")
    return m.group(1)


_VERSION = _read_version()
# Windows wants a 4-part numeric tuple; "0.2.0" -> (0, 2, 0, 0).
_VTUPLE = tuple((list(int(p) for p in _VERSION.split(".")) + [0, 0, 0, 0])[:4])

# Without this resource the .exe shows blank Details in its file properties,
# which makes an already-unsigned binary look even more suspect to users (and to
# SmartScreen). Company/product names deliberately match the GPL header.
version_info = VSVersionInfo(
    ffi=FixedFileInfo(filevers=_VTUPLE, prodvers=_VTUPLE,
                      mask=0x3F, flags=0x0, OS=0x40004, fileType=0x1, subtype=0x0),
    kids=[
        StringFileInfo([StringTable("040904B0", [
            StringStruct("CompanyName", "Rekreate Digital"),
            StringStruct("FileDescription", "Rekounts — local voice dictation"),
            StringStruct("FileVersion", _VERSION),
            StringStruct("InternalName", "Rekounts"),
            StringStruct("LegalCopyright", "Copyright (C) 2026 Rekreate Digital. GPL-3.0."),
            StringStruct("OriginalFilename", "Rekounts.exe"),
            StringStruct("ProductName", "Rekounts"),
            StringStruct("ProductVersion", _VERSION),
        ])]),
        VarFileInfo([VarStruct("Translation", [0x0409, 1200])]),
    ],
)

# Native / data-heavy deps: bundle their DLLs, data files (e.g. the silero VAD
# model, the PortAudio DLL), and submodules wholesale so nothing is missed.
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
        # CPU-only build: keep CUDA/GPU stacks out (smaller, no accidental load).
        "nvidia", "torch", "triton", "tensorflow", "jax",
        # Dev/test-only or unused at runtime — keep the bundle lean.
        "pytest", "_pytest", "setuptools", "pip",
        "tkinter",
        # Qt modules the app never touches (it uses only QtCore/QtGui/QtWidgets).
        "PySide6.QtQml", "PySide6.QtQuick", "PySide6.Qt3DCore",
        "PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets",
        "PySide6.QtMultimedia", "PySide6.QtCharts",
        "PySide6.QtDataVisualization", "PySide6.QtWebSockets",
    ],
    noarchive=False,
)

# --- Deduplicate the MSVC C++ runtime (fixes a hard crash) -------------------
# PyInstaller collects DIFFERENT versions of these base runtime DLLs at the top
# level (from ctranslate2 / numpy) AND privately inside PySide6\ and shiboken6\.
# ctranslate2 loads first and maps the newer top-level msvcp140.dll; when Qt then
# loads, its older same-named copy double-loads on top and the process dies with
# an access violation (0xc0000005 in MSVCP140.dll). Keep only the single
# top-level copy of each base runtime DLL so every module shares one. The
# additive MSVCP140_1.dll / MSVCP140_2.dll are NOT deduped — they are separate
# DLLs that pair fine with the newer base.
_DEDUPE = {"msvcp140.dll", "vcruntime140.dll", "vcruntime140_1.dll"}
_kept = []
for _dest, _src, _kind in a.binaries:
    _base = os.path.basename(_dest).lower()
    _in_subdir = os.path.dirname(_dest) != ""
    if _base in _DEDUPE and _in_subdir:
        continue  # drop the subdir duplicate; the top-level copy remains
    _kept.append((_dest, _src, _kind))
a.binaries = _kept

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
    console=False,          # tray app: no console window
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    version=version_info,
    # icon=...: intentionally unset. The tray/dashboard glyph is drawn in code
    # and no Rekounts .ico has been designed yet — the name is final, the icon
    # asset simply does not exist. When one lands in the repo, point this at it
    # so the .exe, taskbar and Start menu match the tray.
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
