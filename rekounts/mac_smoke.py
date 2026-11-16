"""Opt-in native Mac checks used by CI, including inside the frozen .app.

No mic, permission requests, global listener or posted keyboard events. The
model must already be on disk; the check itself never accesses the network.
"""
from __future__ import annotations

import argparse
import json
import platform
import sys
import tempfile
import time
import traceback
from pathlib import Path


def run(model_dir: Path) -> dict:
    if sys.platform != "darwin":
        raise RuntimeError("The native smoke check requires macOS.")
    if not model_dir.is_dir():
        raise RuntimeError("Pass an already downloaded speech model directory.")

    # Preserve production's native-library load order: model before Qt.
    from rekounts.transcriber import Transcriber
    started = time.monotonic()
    transcriber = Transcriber(str(model_dir), "cpu", "en")
    load_seconds = time.monotonic() - started
    import numpy as np
    started = time.monotonic()
    result = transcriber.transcribe(np.zeros(32000, dtype=np.float32))
    assert isinstance(result, str)
    inference_seconds = time.monotonic() - started

    from rekounts.network import tls_context
    assert tls_context().cert_store_stats()["x509_ca"] > 0
    # Imports prove the bundle collected the lazily loaded frameworks too.
    import AppKit
    import ApplicationServices
    import AVFoundation
    import Quartz
    assert callable(ApplicationServices.AXIsProcessTrustedWithOptions)
    assert callable(Quartz.CGRequestListenEventAccess)
    assert AVFoundation.AVMediaTypeAudio

    from PySide6 import QtGui, QtWidgets
    from rekounts.scratchpad_store import ScratchpadStore
    from rekounts.ui.overlay import Overlay, _mac_window
    from rekounts.ui.scratchpad import Scratchpad, ScratchpadRouter
    from rekounts.ui.permissions_dialog import PermissionsDialog
    from rekounts.ui.branding import app_icon

    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    if QtGui.QGuiApplication.platformName() != "cocoa":
        raise RuntimeError("Native window checks require QT_QPA_PLATFORM=cocoa.")
    app.setQuitOnLastWindowClosed(False)
    # Exercise the same activation policy as the LSUIElement app bundle even
    # when invoked from a terminal. No Dock tile is available to activate us.
    AppKit.NSApplication.sharedApplication().setActivationPolicy_(
        AppKit.NSApplicationActivationPolicyAccessory)
    assert not app_icon().isNull()

    def wait_for(predicate, message, timeout=5):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            app.processEvents()
            if predicate():
                return
            time.sleep(0.02)
        raise AssertionError(message)

    def front_pid():
        front = AppKit.NSWorkspace.sharedWorkspace().frontmostApplication()
        return int(front.processIdentifier()) if front else None

    finders = AppKit.NSRunningApplication.runningApplicationsWithBundleIdentifier_(
        "com.apple.finder")
    assert finders, "Finder must be running in the CI desktop session."
    finder = finders[0]
    finder.activateWithOptions_(AppKit.NSApplicationActivateIgnoringOtherApps)
    finder_pid = int(finder.processIdentifier())
    wait_for(lambda: front_pid() == finder_pid, "Could not activate Finder.")

    pill = Overlay()
    try:
        for state in ("idle", "recording", "processing", "idle"):
            pill._apply_state(state)
            # Allow Cocoa to process deferred activation after ordering a panel.
            until = time.monotonic() + 0.3
            while time.monotonic() < until:
                app.processEvents()
                time.sleep(0.02)
            assert front_pid() == finder_pid, f"The {state} pill stole focus."
            panel = _mac_window(pill)
            assert panel is not None and panel.isVisible()
            assert not panel.hidesOnDeactivate()

        with tempfile.TemporaryDirectory(prefix="rekounts-mac-smoke-") as temp:
            store = ScratchpadStore(Path(temp) / "scratchpad.json")
            pad = Scratchpad(store=store)
            try:
                pad.open_and_raise()
                wait_for(pad.wants_dictation, "The Scratchpad did not become active.")

                class NeverPaste:
                    def insert(self, text):
                        raise AssertionError("Focused Scratchpad routed text to another app.")

                ScratchpadRouter(pad, NeverPaste()).insert("Native Mac smoke check")
                wait_for(lambda: "Native Mac smoke check" in pad.edit.toPlainText(),
                         "The Scratchpad did not receive the dictation.")
                assert pad.close(), "Scratchpad close vetoes application quit."
                pad.open_and_raise()
                wait_for(pad.wants_dictation, "The Scratchpad could not reopen.")
                assert "Native Mac smoke check" in pad.edit.toPlainText()
            finally:
                pad.close()
                pad.deleteLater()

        # Construction probes permissions but never requests them. Show/hide
        # proves this new UI and its native framework dependencies are bundled.
        permissions = PermissionsDialog()
        permissions.show()
        app.processEvents()
        permissions.close()
    finally:
        pill.hide()
        pill.deleteLater()
        app.processEvents()

    return {
        "status": "passed", "architecture": platform.machine(),
        "macos": platform.mac_ver()[0], "frozen": bool(getattr(sys, "frozen", False)),
        "model_load_seconds": round(load_seconds, 3),
        "silence_inference_seconds": round(inference_seconds, 3),
        "checks": ["speech engine and VAD", "bundled TLS roots", "native frameworks",
                   "nonactivating overlay", "accessory Scratchpad focus and routing",
                   "Scratchpad close and reopen", "permissions window"],
        "not_tested": ["real microphone", "granted global hotkey", "paste into other apps",
                       "login", "Spaces and full-screen apps", "Gatekeeper"],
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model-dir", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        report = run(args.model_dir.resolve())
        code = 0
    except Exception:
        report = {"status": "failed", "error": traceback.format_exc()}
        code = 1
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    # A windowed PyInstaller app may have no stdout. The report is authoritative.
    if sys.stdout is not None:
        print(json.dumps(report, indent=2))
    return code
