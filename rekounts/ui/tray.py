"""System-tray icon + menu.

Minimal monochrome: a white microphone glyph on a dark rounded tile (no
gradients), matching the redesigned dashboard. The constructor stays
backward-compatible — the original `TrayApp(app, on_open_settings, on_quit)`
call still works; every new capability is an optional keyword the conductor
wires in at merge time.
"""

import json
import logging
import os
import re
import subprocess
import sys
import threading
import urllib.request
import webbrowser

from PySide6 import QtCore, QtGui, QtWidgets

from rekounts.device_utils import canonical_microphone_name, list_microphones

log = logging.getLogger(__name__)

# The ONE network call this app is permitted to make, and only on an explicit
# "Check for Updates" click. Public, unauthenticated GitHub REST endpoint.
GITHUB_REPO = "rekreatedigital/rekounts"


def _make_icon() -> QtGui.QIcon:
    """Monochrome mic glyph: white on a dark rounded tile."""
    s = 64
    pix = QtGui.QPixmap(s, s)
    pix.fill(QtGui.QColor(0, 0, 0, 0))
    p = QtGui.QPainter(pix)
    p.setRenderHint(QtGui.QPainter.Antialiasing)

    # dark charcoal rounded tile (matches dashboard surfaces)
    p.setBrush(QtGui.QColor("#1a1c22"))
    p.setPen(QtGui.QPen(QtGui.QColor("#2a2d35"), 2))
    p.drawRoundedRect(QtCore.QRectF(3, 3, s - 6, s - 6), 15, 15)

    # white microphone glyph
    white = QtGui.QColor(240, 242, 245)
    p.setBrush(white)
    p.setPen(QtCore.Qt.NoPen)
    p.drawRoundedRect(QtCore.QRectF(26, 14, 12, 24), 6, 6)          # capsule
    pen = QtGui.QPen(white, 3)
    pen.setCapStyle(QtCore.Qt.RoundCap)
    p.setPen(pen)
    p.setBrush(QtCore.Qt.NoBrush)
    p.drawArc(QtCore.QRectF(20, 20, 24, 24), 200 * 16, 140 * 16)    # cradle
    p.drawLine(32, 44, 32, 50)                                      # stem
    p.drawLine(26, 50, 38, 50)                                      # base
    p.end()
    return QtGui.QIcon(pix)


def _origin_repo_slug():
    """'owner/repo' parsed from the git origin remote, or None.

    Returns None whenever git can't answer - a frozen .exe (no .git alongside
    it, often no git on PATH), a source tarball, or a non-GitHub remote. The
    caller falls back to GITHUB_REPO, so this only ever *corrects* a stale
    hardcoded slug; it never breaks the check.
    """
    if getattr(sys, "frozen", False):
        return None
    repo_root = os.path.dirname(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))))
    # exists(), not isdir(): in a git worktree ".git" is a file, not a folder.
    if not os.path.exists(os.path.join(repo_root, ".git")):
        return None
    try:
        # CREATE_NO_WINDOW keeps a console from flashing on a GUI-only build.
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        out = subprocess.run(
            ["git", "-C", repo_root, "remote", "get-url", "origin"],
            capture_output=True, text=True, timeout=5, creationflags=flags)
        if out.returncode != 0:
            return None
        url = (out.stdout or "").strip()
    except Exception as e:
        log.debug("could not read git origin: %s", e)
        return None
    # https://github.com/owner/repo(.git)  |  git@github.com:owner/repo(.git)
    m = re.search(r"github\.com[:/]+([^/]+/[^/]+?)(?:\.git)?/?$", url)
    return m.group(1) if m else None


def _resolve_repo_slug() -> str:
    """GITHUB_REPO, corrected against the origin remote when git can tell us."""
    slug = _origin_repo_slug()
    if slug and slug.lower() != GITHUB_REPO.lower():
        log.warning("hardcoded GITHUB_REPO %r does not match origin %r; "
                    "using origin", GITHUB_REPO, slug)
        return slug
    return GITHUB_REPO


class _Signals(QtCore.QObject):
    # Marshal worker-thread toasts back onto the GUI thread.
    toast = QtCore.Signal(str)


class TrayApp:
    def __init__(self, app, on_open_settings, on_quit,
                 on_open_dashboard=None, on_check_updates=None, on_help=None,
                 config=None, on_mic_changed=None, on_language_changed=None,
                 languages=None, notifications_enabled=None):
        """
        Backward-compatible: only the first three args are required.

        Optional wiring (conductor):
          on_open_dashboard()          -> open the Hub
          config                       -> Config; enables Microphone/Language menus
          on_mic_changed(name)         -> apply a live mic switch (name or None)
          on_language_changed(code)    -> apply a live language switch
          languages                    -> [(label, code), ...] for the Language menu
          on_check_updates()           -> override the default GitHub check
          on_help()                    -> override the default (open repo in browser)
          notifications_enabled()      -> live gate for EVERY toast (see notify())
        """
        self.app = app
        self.config = config
        self.on_mic_changed = on_mic_changed or (lambda name: None)
        self.on_language_changed = on_language_changed or (lambda code: None)
        self._languages = languages or []
        # One gate for every toast. Read live so toggling "Tray notifications"
        # in Settings applies at once. Defaults to always-on for backward-compat
        # (older callers/tests that don't pass a provider).
        self._notifications_enabled = notifications_enabled or (lambda: True)

        self._sig = _Signals()
        self.tray = QtWidgets.QSystemTrayIcon()
        self.tray.setIcon(_make_icon())
        self.tray.setToolTip("Rekounts")
        self._sig.toast.connect(self.notify)

        # Keep a hard reference: a QMenu owned only by the C++ side of
        # setContextMenu() can be garbage-collected out from under PySide6.
        self.menu = QtWidgets.QMenu()
        menu = self.menu

        if on_open_dashboard:
            open_dash = menu.addAction("Open Dashboard")
            open_dash.triggered.connect(on_open_dashboard)

        menu.addAction("Settings…", on_open_settings)

        # Submenus are created empty and filled on aboutToShow so both the
        # device list and the radio checkmarks reflect reality at open time
        # (Settings can change the mic/language behind the tray's back).
        self._mic_menu = None
        self._lang_menu = None
        self._mic_group = None
        self._lang_group = None
        if config is not None:
            self._mic_menu = menu.addMenu("Microphone")
            self._mic_menu.aboutToShow.connect(self._refresh_microphone_menu)
            if self._languages:
                self._lang_menu = menu.addMenu("Language")
                self._lang_menu.aboutToShow.connect(self._refresh_language_menu)

        menu.addSeparator()
        updates = menu.addAction("Check for Updates")
        updates.triggered.connect(on_check_updates or self._check_for_updates)
        help_action = menu.addAction("Help")
        help_action.triggered.connect(on_help or self._open_help)

        menu.addSeparator()
        menu.addAction("Quit", on_quit)

        self.tray.setContextMenu(menu)
        self.tray.show()

    # ----------------------------------------------------------- submenus
    def _refresh_microphone_menu(self):
        """Rebuild the Microphone submenu from the live device list.

        Cheap enough for aboutToShow: list_microphones() reads PortAudio's
        cached device table (well under a millisecond) and builds a handful of
        actions, so the menu never blocks on opening.
        """
        sub = self._mic_menu
        sub.clear()
        # A new group each rebuild; the old one dies with the cleared actions.
        self._mic_group = group = QtGui.QActionGroup(sub)
        group.setExclusive(True)

        stored = self.config.get("microphone")
        try:
            names = list_microphones()
            # Tolerate a config holding a legacy truncated MME name so the
            # checkmark lands on the mic actually in use.
            current = canonical_microphone_name(stored)
        except Exception as e:                              # pragma: no cover
            log.warning("could not list microphones: %s", e)
            names, current = [], stored

        default = sub.addAction("System default")
        default.setCheckable(True)
        default.setChecked(stored is None)
        default.triggered.connect(lambda: self._apply_mic(None))
        group.addAction(default)

        for name in names:
            act = sub.addAction(name)
            act.setCheckable(True)
            act.setChecked(name == current)
            act.triggered.connect(lambda _=False, n=name: self._apply_mic(n))
            group.addAction(act)

    def _refresh_language_menu(self):
        """Rebuild the Language submenu, checking the current config value."""
        sub = self._lang_menu
        sub.clear()
        self._lang_group = group = QtGui.QActionGroup(sub)
        group.setExclusive(True)
        current = self.config.get("language")
        for label, code in self._languages:
            act = sub.addAction(label)
            act.setCheckable(True)
            act.setChecked(code == current)
            act.triggered.connect(lambda _=False, c=code, l=label: self._apply_language(c, l))
            group.addAction(act)

    def _apply_mic(self, name):
        self.config.set("microphone", name)
        self.config.save()
        self.on_mic_changed(name)
        self.notify(f"Microphone set to {name or 'system default'}.")

    def _apply_language(self, code, label):
        self.config.set("language", code)
        self.config.save()
        self.on_language_changed(code)
        self.notify(f"Language set to {label}.")

    # -------------------------------------------------------- update check
    def _check_for_updates(self):
        """Single permitted network call — only fires on explicit user click."""
        self.notify("Checking GitHub for updates…")
        threading.Thread(target=self._fetch_latest, daemon=True).start()

    def _fetch_latest(self):
        # Slug resolution shells out to git, so it happens here on the worker
        # thread, never on the GUI thread or at import time.
        url = f"https://api.github.com/repos/{_resolve_repo_slug()}/commits/master"
        try:
            req = urllib.request.Request(
                url, headers={"Accept": "application/vnd.github+json",
                              "User-Agent": "Rekounts"})
            with urllib.request.urlopen(req, timeout=8) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            sha = (data.get("sha") or "")[:7]
            date = (data.get("commit", {}).get("author", {}).get("date", ""))[:10]
            msg = (data.get("commit", {}).get("message", "") or "").splitlines()[0]
            self._sig.toast.emit(
                f"Latest on GitHub: {sha} ({date})\n{msg[:80]}")
        except Exception as e:
            log.warning("update check failed: %s", e)
            self._sig.toast.emit("Could not reach GitHub to check for updates.")

    def _open_help(self):
        # Off the GUI thread: slug resolution shells out to git, and launching
        # the browser can itself take a moment.
        threading.Thread(target=self._open_help_url, daemon=True).start()

    def _open_help_url(self):
        webbrowser.open(f"https://github.com/{_resolve_repo_slug()}#readme")

    # -------------------------------------------------------------- toast
    def notify(self, message: str):
        """The single choke-point every toast passes through.

        Tray-originated toasts (mic/language switches, the update check) and
        app-originated ones (routed here from the bridge) all land here, so the
        "Tray notifications" switch is honored in exactly one place instead of
        being wrapped around some callers and bypassed by others. A broken gate
        must never swallow a real message, so any error means "show it".
        """
        try:
            enabled = self._notifications_enabled()
        except Exception:
            enabled = True
        if not enabled:
            return
        self.tray.showMessage("Rekounts", message)
