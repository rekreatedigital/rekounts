"""Visible, repeatable macOS permission setup, independent of notifications."""
import sys

from PySide6 import QtCore, QtGui, QtWidgets

from rekounts.permissions import check_permissions, permission_settings_url, request_permission
from rekounts.ui import theme
from rekounts.ui.window_utils import show_and_activate

_PURPOSES = {
    "Input Monitoring": "Respond to your dictation hotkey in other apps.",
    "Accessibility": "Paste your words into the app you are using.",
    "Microphone": "Hear your voice and transcribe it on this Mac.",
}


class PermissionsDialog(QtWidgets.QDialog):
    def __init__(self, parent=None, *, probe=None, requester=None, opener=None,
                 frozen=None, on_quit=None):
        super().__init__(parent)
        self._probe = probe or check_permissions
        self._requester = requester or request_permission
        self._opener = opener or QtGui.QDesktopServices.openUrl
        self._previous_input = None
        self._restart_required = False
        self.states = []
        self.setWindowTitle("Set up Rekounts on your Mac")
        self.setMinimumWidth(540)
        self.setStyleSheet(f"""
            QDialog {{ background: {theme.BG}; color: {theme.TEXT}; }}
            QLabel {{ color: {theme.TEXT}; font-size: 13px; }}
            QPushButton {{ padding: 7px 12px; min-height: 18px;
                font-size: 13px; color: {theme.TEXT};
                background: {theme.CARD_HI}; border: 1px solid {theme.BORDER};
                border-radius: 6px; }}
            QPushButton:disabled {{ color: {theme.TEXT_3}; }}
        """)
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(18)
        title = QtWidgets.QLabel("Allow dictation on this Mac")
        title.setStyleSheet("font-size: 21px; font-weight: 600;")
        layout.addWidget(title)
        frozen = getattr(sys, "frozen", False) if frozen is None else frozen
        self.guidance = QtWidgets.QLabel(
            "Enable Rekounts in System Settings → Privacy & Security. "
            "Your audio stays on this Mac." if frozen else
            "Running from source: enable your terminal (or the app you started "
            "Rekounts from) in System Settings → Privacy & Security. Rekounts "
            "will not appear as a separate app in those lists.")
        self.guidance.setWordWrap(True)
        layout.addWidget(self.guidance)
        self.status_labels, self.allow_buttons, self.settings_buttons = {}, {}, {}
        for name, purpose in _PURPOSES.items():
            row = QtWidgets.QVBoxLayout()
            heading = QtWidgets.QHBoxLayout()
            heading.addWidget(QtWidgets.QLabel(name), 1)
            status = self.status_labels[name] = QtWidgets.QLabel()
            heading.addWidget(status)
            row.addLayout(heading)
            description = QtWidgets.QLabel(purpose)
            description.setWordWrap(True)
            row.addWidget(description)
            actions = QtWidgets.QHBoxLayout()
            allow = self.allow_buttons[name] = QtWidgets.QPushButton("Allow…")
            allow.clicked.connect(lambda _=False, n=name: self.request(n))
            actions.addWidget(allow)
            settings = self.settings_buttons[name] = QtWidgets.QPushButton("Open Settings")
            settings.clicked.connect(lambda _=False, n=name: self.open_settings(n))
            actions.addWidget(settings)
            actions.addStretch()
            row.addLayout(actions)
            layout.addLayout(row)
        self.summary = QtWidgets.QLabel()
        self.summary.setWordWrap(True)
        layout.addWidget(self.summary)
        restart = QtWidgets.QLabel(
            "After changing Input Monitoring, quit and reopen Rekounts. "
            "From source, quit and reopen the terminal as well.")
        restart.setWordWrap(True)
        layout.addWidget(restart)
        actions = QtWidgets.QHBoxLayout()
        if on_quit is not None:
            quit_button = QtWidgets.QPushButton("Quit Rekounts")
            quit_button.clicked.connect(lambda: on_quit())
            actions.addWidget(quit_button)
        actions.addStretch()
        done = QtWidgets.QPushButton("Done")
        done.clicked.connect(self.close)
        actions.addWidget(done)
        layout.addLayout(actions)
        self._timer = QtCore.QTimer(self)
        self._timer.setInterval(1000)
        self._timer.timeout.connect(self.refresh)
        self.refresh()

    def needs_setup(self):
        return any(state.granted is not True for state in self.states)

    def refresh(self):
        self.states = self._probe()
        for state in self.states:
            self.status_labels[state.name].setText(
                "Allowed" if state.granted is True else
                "Needs access" if state.granted is False else "Not confirmed")
            self.allow_buttons[state.name].setEnabled(state.granted is not True)
            if state.name == "Input Monitoring":
                if self._previous_input is False and state.granted is True:
                    self._restart_required = True
                self._previous_input = state.granted
        if self._restart_required:
            message = "Input Monitoring changed. Quit and reopen before testing the hotkey."
        elif self.needs_setup():
            message = "Allow each permission, then try dictating into TextEdit."
        else:
            message = "Access is allowed. Try your dictation hotkey in TextEdit."
        self.summary.setText(message)

    def request(self, name):
        requested = self._requester(name)
        self.refresh()
        if not requested:
            self.summary.setText("Open Settings to allow " + name + ".")

    def open_settings(self, name):
        if not self._opener(QtCore.QUrl(permission_settings_url(name))):
            self.summary.setText(
                "Open System Settings → Privacy & Security → " + name + ".")

    def open_and_raise(self):
        show_and_activate(self)

    def showEvent(self, event):
        super().showEvent(event)
        self.refresh()
        self._timer.start()

    def hideEvent(self, event):
        self._timer.stop()
        super().hideEvent(event)
