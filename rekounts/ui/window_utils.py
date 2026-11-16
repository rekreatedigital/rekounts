"""Activation for windows the user explicitly opens from the menu bar."""
import logging
import sys

from PySide6 import QtGui

log = logging.getLogger(__name__)


def activate_application():
    """Accessory apps need application activation before a window can be key."""
    if sys.platform != "darwin" or QtGui.QGuiApplication.platformName() != "cocoa":
        return
    try:
        import AppKit
        AppKit.NSApplication.sharedApplication().activateIgnoringOtherApps_(True)
    except Exception:
        log.debug("Could not activate the Mac application", exc_info=True)


def show_and_activate(widget):
    if widget.isMinimized():
        widget.showNormal()
    else:
        widget.show()
    activate_application()
    widget.raise_()
    widget.activateWindow()
