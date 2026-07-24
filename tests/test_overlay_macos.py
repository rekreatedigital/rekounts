"""The macOS overlay-visibility helpers (pure parts; native NSPanel state
needs real hardware — see MACOS-TESTING.md for the manual verification)."""
import rekounts.ui.overlay as overlay


def test_collection_behavior_is_all_spaces_plus_fullscreen_auxiliary():
    # CanJoinAllSpaces (1<<0) | FullScreenAuxiliary (1<<8): the pill follows
    # the user across Spaces and stays up over full-screen apps.
    assert overlay._mac_collection_behavior() == (1 << 0) | (1 << 8)


def test_native_tweaks_default_on_with_a_kill_switch():
    assert overlay._mac_native_enabled({}) is True
    assert overlay._mac_native_enabled({"REKOUNTS_MAC_OVERLAY_NATIVE": "1"}) is True
    assert overlay._mac_native_enabled({"REKOUNTS_MAC_OVERLAY_NATIVE": "0"}) is False


def test_nonactivating_panel_bit_matches_appkit():
    assert overlay._NS_NONACTIVATING_PANEL == 1 << 7


def test_helpers_are_noops_off_darwin():
    """The appliers must be safe to call on every platform. On macOS under the
    offscreen Qt platform (CI) the native tweak must bail on the platformName
    guard — an offscreen winId is not an NSView, and treating it as one is a
    segfault (this exact crash took down the first macos-latest run)."""
    import os
    import sys
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

    from PySide6 import QtWidgets
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    w = QtWidgets.QWidget()
    overlay._apply_mac_tool_window_attr(w)
    overlay._apply_mac_panel_behavior(w)     # must never raise, any platform
    if sys.platform != "darwin":
        attr = getattr(overlay.QtCore.Qt, "WA_MacAlwaysShowToolWindow", None)
        if attr is not None:
            assert w.testAttribute(attr) is False
    w.deleteLater()
    app.processEvents()
