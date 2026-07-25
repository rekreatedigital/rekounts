"""The Send Feedback dialog — a review screen, not a submit form.

The one rule this window exists to enforce: **the user reads the diagnostics
before any of it moves.** So it has Copy, it has Save, and it deliberately has
no Send button. The two channel buttons hand a prefilled URL to the browser or
the mail client — the same thing "Check for Updates" does when it opens a
release page — and the message is still sitting unsent in the user's own app
afterwards, for them to edit and send.

What goes in the block, and what is scrubbed out of it, is decided in
``rekounts/feedback.py``; this file only shows it.
"""

import logging
import threading
import webbrowser

from PySide6 import QtGui, QtWidgets

from rekounts import feedback
from rekounts.ui import theme
from rekounts.ui.branding import app_icon

log = logging.getLogger(__name__)

INTRO = (
    "Rekounts has no server, so nothing is sent from this window. Pick how you "
    "would rather reach the developer and the report opens — already filled in "
    "— in your browser or your mail client. You read it, change anything you "
    "like, and send it yourself."
)

CHANNEL_HINT = (
    "An issue is public and searchable, and you get replies on it — it needs a "
    "GitHub account. Email needs nothing at all."
)

PROMISE = (
    "This is the whole of what Rekounts fills in about your machine. Your "
    "dictations, your Scratchpad, your Dictionary and your history are never "
    "part of it, and your user name and folder paths are taken out."
)

# The dialog is opened from the tray as well as from the Hub, so it cannot rely
# on inheriting the Hub's stylesheet from a parent — it carries its own copy,
# plus the few rules the Hub never needed because it has no dialogs.
_EXTRA_STYLE = f"""
QDialog {{ background: {theme.BG}; color: {theme.TEXT}; font-size: 13px; }}
QPlainTextEdit {{
    background: {theme.CARD}; border: 1px solid {theme.BORDER};
    border-radius: 10px; padding: 10px; color: {theme.TEXT};
    selection-background-color: {theme.TEXT_3};
}}
QCheckBox {{ color: {theme.TEXT_2}; font-size: 12px; }}
"""


class FeedbackDialog(QtWidgets.QDialog):
    """Review the diagnostics, then choose a channel (or neither).

    ``opener`` is the seam the tests use: it receives the finished URL instead
    of a real browser. ``slug`` skips the git lookup, which otherwise happens on
    a worker thread because it shells out.
    """

    def __init__(self, config=None, parent=None, opener=None, slug=None):
        super().__init__(parent)
        self.config = config
        self._opener = opener or self._open_in_background
        self._slug = slug

        self.setWindowTitle("Send feedback")
        self.setWindowIcon(app_icon())
        self.setStyleSheet(theme.STYLE + _EXTRA_STYLE)
        self.setMinimumWidth(560)

        root = QtWidgets.QVBoxLayout(self)
        root.setContentsMargins(24, 22, 24, 20)
        root.setSpacing(14)

        title = QtWidgets.QLabel("Send feedback")
        title.setProperty("role", "page-title")
        root.addWidget(title)
        root.addWidget(self._paragraph(INTRO))

        channels = QtWidgets.QHBoxLayout()
        channels.setContentsMargins(0, 0, 0, 0)
        channels.setSpacing(8)
        self.issue_btn = self._ghost("Open a GitHub issue…", self.open_github)
        self.email_btn = self._ghost(f"Email {feedback.SUPPORT_EMAIL}…",
                                     self.open_email)
        channels.addWidget(self.issue_btn)
        channels.addWidget(self.email_btn)
        channels.addStretch(1)
        root.addLayout(channels)
        root.addWidget(self._paragraph(CHANNEL_HINT))

        head = QtWidgets.QHBoxLayout()
        head.setContentsMargins(0, 6, 0, 0)
        label = QtWidgets.QLabel("What gets attached")
        label.setProperty("role", "section")
        head.addWidget(label)
        head.addStretch(1)
        self.include_log = QtWidgets.QCheckBox(
            f"Include the last {feedback.LOG_TAIL_LINES} log lines")
        self.include_log.setChecked(False)
        # Nothing to include, and a tickbox that silently does nothing is worse
        # than one that says why.
        if not self._log_exists():
            self.include_log.setEnabled(False)
            self.include_log.setToolTip("No log file on this machine yet.")
        self.include_log.toggled.connect(lambda _checked: self.refresh())
        head.addWidget(self.include_log)
        root.addLayout(head)

        self.view = QtWidgets.QPlainTextEdit()
        self.view.setReadOnly(True)
        self.view.setLineWrapMode(QtWidgets.QPlainTextEdit.NoWrap)
        self.view.setFont(QtGui.QFontDatabase.systemFont(
            QtGui.QFontDatabase.FixedFont))
        self.view.setMinimumHeight(190)
        root.addWidget(self.view, 1)

        root.addWidget(self._paragraph(PROMISE))

        buttons = QtWidgets.QHBoxLayout()
        buttons.setContentsMargins(0, 4, 0, 0)
        buttons.setSpacing(8)
        self.copy_btn = self._ghost("Copy", self.copy)
        self.save_btn = self._ghost("Save…", self.save)
        buttons.addWidget(self.copy_btn)
        buttons.addWidget(self.save_btn)
        buttons.addStretch(1)
        close = self._ghost("Close", self.reject)
        close.setDefault(True)
        buttons.addWidget(close)
        root.addLayout(buttons)

        self.status = QtWidgets.QLabel("")
        self.status.setProperty("role", "row-hint")
        self.status.setVisible(False)
        root.addWidget(self.status)

        self.refresh()

    # ------------------------------------------------------------- helpers
    @staticmethod
    def _paragraph(text):
        label = QtWidgets.QLabel(text)
        label.setProperty("role", "hint")
        label.setWordWrap(True)
        return label

    @staticmethod
    def _ghost(text, slot):
        btn = QtWidgets.QPushButton(text)
        btn.setObjectName("Ghost")
        btn.clicked.connect(lambda _checked=False: slot())
        return btn

    @staticmethod
    def _log_exists() -> bool:
        try:
            return feedback.log_path().exists()
        except Exception:                                    # pragma: no cover
            return False

    def _say(self, message):
        self.status.setText(message)
        self.status.setVisible(bool(message))

    # -------------------------------------------------------- the block
    def diagnostics(self) -> str:
        """Exactly the text on screen — which is exactly what the links carry."""
        return self.view.toPlainText()

    def refresh(self):
        lines = feedback.LOG_TAIL_LINES if self.include_log.isChecked() else 0
        try:
            text = feedback.collect(self.config, log_lines=lines)
        except Exception:
            log.exception("could not build the diagnostics block")
            text = ""
        self.view.setPlainText(text)
        self._say("")

    # ---------------------------------------------------------- channels
    def open_github(self):
        """Open the prefilled issue form. Nothing is submitted by doing so."""
        block = self.diagnostics()

        def go():
            slug = self._slug or self._resolve_slug()
            self._opener(feedback.github_issue_url(block, slug))

        # Slug resolution shells out to git, so it happens off the GUI thread —
        # the same reason the tray's Help entry does.
        if self._slug:
            go()
        else:
            threading.Thread(target=go, daemon=True).start()
        self._say("Opening your browser. Nothing is sent until you submit it "
                  "there.")

    def open_email(self):
        """Open a prefilled message in the machine's mail client, unsent."""
        self._opener(feedback.mailto_url(self.diagnostics()))
        self._say("Opening your mail client. Nothing is sent until you press "
                  "send there.")

    @staticmethod
    def _resolve_slug() -> str:
        from rekounts.ui.tray import _resolve_repo_slug
        return _resolve_repo_slug()

    @staticmethod
    def _open_in_background(url):
        threading.Thread(target=webbrowser.open, args=(url,),
                         daemon=True).start()

    # ------------------------------------------------------- copy & save
    def copy(self):
        QtWidgets.QApplication.clipboard().setText(self.diagnostics())
        self._say("Copied. Paste it wherever you like.")

    def save(self, path=None):
        """Write the block to a text file the user picks.

        ``path`` is for the tests; in the app the file dialog supplies it, and
        cancelling it does nothing at all.
        """
        if path is None:
            path, _ = QtWidgets.QFileDialog.getSaveFileName(
                self, "Save diagnostics", "rekounts-diagnostics.txt",
                "Text files (*.txt)")
        if not path:
            return
        try:
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(self.diagnostics() + "\n")
        except Exception as e:
            log.warning("could not save diagnostics: %s", e)
            self._say(f"Could not save that file: {e}")
            return
        self._say(f"Saved to {path}")


def show_feedback(config=None, parent=None):
    """Open the dialog modally. The one entry point the tray and Hub call."""
    dialog = FeedbackDialog(config, parent)
    dialog.exec()
    return dialog
