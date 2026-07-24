"""System-tray icon + menu.

The tray shows the app's one icon (``assets/icon.ico`` via
``rekounts.ui.branding``) — the same monochrome waveform mark as the `.exe`, the
Start-menu shortcut and the website. The constructor stays backward-compatible —
the original `TrayApp(app, on_open_settings, on_quit)` call still works; every new
capability is an optional keyword the conductor wires in at merge time.
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

from rekounts import __version__
from rekounts.device_utils import canonical_microphone_name, list_microphones
from rekounts.ui.branding import app_icon

log = logging.getLogger(__name__)

# The ONE network call this app makes. Public, unauthenticated GitHub REST
# endpoint, reached on an explicit "Check for Updates" click — or, if and only if
# the user has switched on "Check for updates automatically" (OFF by default),
# once per launch. Nothing about the user is sent: it is a plain GET for a public
# release, with no query string, no token and no identifier beyond the
# User-Agent GitHub requires.
GITHUB_REPO = "rekreatedigital/rekounts"

# Compared against the RELEASE tag, not the newest commit: master moves daily and
# means nothing to someone running a build, whereas a release is the thing they
# can actually install. See _fetch_latest.
RELEASES_API = "https://api.github.com/repos/{slug}/releases/latest"
RELEASES_PAGE = "https://github.com/{slug}/releases/latest"
UPDATE_TIMEOUT_S = 8

# How long after launch the opt-in automatic check runs. Late enough to stay out
# of the way of the model warm-up (the thing the user is actually waiting for),
# short enough that it has happened by the time they first open the tray menu.
AUTO_CHECK_DELAY_MS = 10_000


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


# ------------------------------------------------------------ release compare
def parse_version(text):
    """``"v0.3.0"`` / ``"0.3"`` / ``"v1.2.3-rc1"`` -> a comparable tuple, or None.

    Only the leading dotted-numeric run is read; a ``-rc1`` / ``+build`` suffix is
    ignored rather than ordered, because GitHub's ``releases/latest`` already
    excludes pre-releases, so a suffix only ever turns up on a tag that was
    hand-published and is not worth guessing about.

    None means "unparseable", and every caller treats that as "say nothing" — an
    odd tag must never be reported as an available upgrade.
    """
    if not isinstance(text, str):
        return None
    m = re.match(r"\s*[vV]?(\d+(?:\.\d+)*)", text)
    if not m:
        return None
    return tuple(int(part) for part in m.group(1).split("."))


def is_newer(candidate, current) -> bool:
    """True if ``candidate`` is a strictly later version than ``current``.

    Both are tuples from :func:`parse_version`; they are zero-padded to the same
    length first so ``0.4`` and ``0.4.0`` compare equal instead of the shorter one
    losing.
    """
    if not candidate or not current:
        return False
    width = max(len(candidate), len(current))
    pad = (0,) * width
    return (candidate + pad)[:width] > (current + pad)[:width]


def fetch_latest_release(slug: str, timeout: float = UPDATE_TIMEOUT_S) -> dict:
    """The GitHub API's newest published, non-pre-release release for ``slug``."""
    req = urllib.request.Request(
        RELEASES_API.format(slug=slug),
        headers={"Accept": "application/vnd.github+json",
                 "User-Agent": f"Rekounts/{__version__}"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


class _Signals(QtCore.QObject):
    # Marshal worker-thread toasts back onto the GUI thread.
    toast = QtCore.Signal(str)
    # An available update: the message, and the page to open if the toast is
    # clicked. Separate from `toast` so an ordinary message can never inherit a
    # stale link.
    update_found = QtCore.Signal(str, str)


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
        self.tray.setIcon(app_icon())
        self.tray.setToolTip("Rekounts")
        self._sig.toast.connect(self.notify)
        self._sig.update_found.connect(self._announce_update)
        # Set only by a toast that has somewhere to go; clicking any other toast
        # does nothing. See notify().
        self._pending_url = None
        self.tray.messageClicked.connect(self._open_pending_url)

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
        # Wrapped rather than connected directly: QAction.triggered passes its
        # `checked` bool to the slot, which would land in _check_for_updates'
        # `silent` parameter and turn a menu click into a silent check.
        check_updates = on_check_updates or self._check_for_updates
        updates.triggered.connect(lambda _checked=False: check_updates())
        help_action = menu.addAction("Help")
        help_action.triggered.connect(on_help or self._open_help)

        menu.addSeparator()
        menu.addAction("Quit", on_quit)

        self.tray.setContextMenu(menu)
        self.tray.show()

        # Opt-in, default OFF (config DEFAULTS), and never overridden by a
        # caller-supplied on_check_updates: a host that replaced the manual check
        # would be surprised by us firing our own network call behind it.
        self._auto_timer = None
        if on_check_updates is None and self._auto_check_enabled():
            self._auto_timer = QtCore.QTimer()
            self._auto_timer.setSingleShot(True)
            self._auto_timer.timeout.connect(
                lambda: self._check_for_updates(silent=True))
            self._auto_timer.start(AUTO_CHECK_DELAY_MS)

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
    def _auto_check_enabled(self) -> bool:
        """Is the opt-in automatic check switched on? Defaults to no.

        Anything unexpected — no config, an exception — answers no. The safe
        direction for a network call is always "don't".
        """
        if self.config is None:
            return False
        try:
            return bool(self.config.get("auto_check_updates"))
        except Exception:                                    # pragma: no cover
            log.debug("could not read auto_check_updates; assuming off")
            return False

    def _check_for_updates(self, silent: bool = False):
        """Ask GitHub for the newest release.

        ``silent`` is the opt-in automatic check: it says nothing unless there is
        actually an update, so a launch with no news — or with no network — is
        completely quiet. A click is never silent; the user asked, so they get an
        answer either way.
        """
        if not silent:
            self.notify("Checking GitHub for updates…")
        threading.Thread(target=self._fetch_latest, args=(silent,),
                         daemon=True).start()

    def _fetch_latest(self, silent: bool = False):
        # Slug resolution shells out to git, so it happens here on the worker
        # thread, never on the GUI thread or at import time.
        slug = _resolve_repo_slug()
        try:
            data = fetch_latest_release(slug)
        except Exception as e:
            # A 404 is the ordinary state of a repo with no published release
            # yet, not a fault worth alarming anyone about.
            log.warning("update check failed: %s", e)
            if not silent:
                self._sig.toast.emit(
                    "Could not reach GitHub to check for updates.")
            return

        tag = (data.get("tag_name") or "").strip()
        page = (data.get("html_url") or "").strip() or RELEASES_PAGE.format(slug=slug)
        latest = parse_version(tag)
        current = parse_version(__version__)

        if is_newer(latest, current):
            self._sig.update_found.emit(
                f"Rekounts {tag.lstrip('vV')} is available "
                f"(you have {__version__}).\nClick to open the release page.",
                page)
        elif silent:
            return                       # up to date, and nobody asked — say nothing
        elif latest is None:
            # An unparseable tag is reported as-is rather than guessed at, so the
            # user still learns something instead of being told "up to date".
            self._sig.toast.emit(
                f"Latest release on GitHub: {tag or 'unknown'}. "
                f"You have {__version__}.")
        else:
            self._sig.toast.emit(f"You are on the latest release ({__version__}).")

    def _announce_update(self, message: str, url: str):
        """Show the update toast, and arm it so clicking opens the release page."""
        self.notify(message, url=url)

    def _open_pending_url(self):
        """The user clicked a toast that had somewhere to go."""
        url = self._pending_url
        if not url:
            return
        # Launching a browser can block for a moment; keep it off the GUI thread.
        threading.Thread(target=webbrowser.open, args=(url,), daemon=True).start()

    def _open_help(self):
        # Off the GUI thread: slug resolution shells out to git, and launching
        # the browser can itself take a moment.
        threading.Thread(target=self._open_help_url, daemon=True).start()

    def _open_help_url(self):
        webbrowser.open(f"https://github.com/{_resolve_repo_slug()}#readme")

    # -------------------------------------------------------------- toast
    def notify(self, message: str, url: str | None = None):
        """The single choke-point every toast passes through.

        Tray-originated toasts (mic/language switches, the update check) and
        app-originated ones (routed here from the bridge) all land here, so the
        "Tray notifications" switch is honored in exactly one place instead of
        being wrapped around some callers and bypassed by others. A broken gate
        must never swallow a real message, so any error means "show it".

        ``url`` makes this toast clickable. It is assigned unconditionally, and
        every ordinary toast clears it back to None, so a click can only ever
        follow the link of the message currently on screen.
        """
        self._pending_url = url
        try:
            enabled = self._notifications_enabled()
        except Exception:
            enabled = True
        if not enabled:
            return
        self.tray.showMessage("Rekounts", message)
