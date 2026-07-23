"""Launch-on-login ("startup") management.

Enable, disable, or query whether Rekounts starts automatically when the user
logs in. On Windows this is a value under the per-user Run key:

    HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\Run\\Rekounts

The value is a command line Windows runs at login. We register the *current*
runtime so it works whether the app is running from source (the windowless
interpreter + the repo's ``launch.py``) or as a frozen PyInstaller ``.exe``.

The module-level functions — :func:`enable`, :func:`disable`, :func:`is_enabled`,
:func:`set_enabled`, :func:`default_command`, :func:`current_command` — are the
public API a Settings checkbox or tray toggle should call. Example::

    import rekounts.startup as startup
    startup.set_enabled(checkbox.isChecked())   # from a settings toggle
    checkbox.setChecked(startup.is_enabled())   # to reflect current state

The work is delegated to a platform *backend* so a macOS ``LaunchAgent`` backend
can be added later (see :func:`get_backend`) without changing any caller.
"""
from __future__ import annotations

import os
import sys

APP_NAME = "Rekounts"
# The Run value the app registered under its old name. It has to be actively
# removed on upgrade, not merely left alone: it points at the OLD checkout, so
# leaving it would make Windows launch a second, stale copy of the app at every
# login alongside the new one — two tray icons and two fighting hotkey hooks.
LEGACY_APP_NAME = "TalkativeAI"
_RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
# Task Manager's Startup tab records its enable/disable decision here, PARALLEL
# to the Run key above. A Run entry that is "disabled" here is skipped by Windows
# at login even though the Run value still exists — so any honest reading of
# "are we enabled?" has to consult it, and any enable() has to clear it.
_APPROVED_KEY = (
    r"Software\Microsoft\Windows\CurrentVersion\Explorer\StartupApproved\Run")


def _quote(path: str) -> str:
    """Wrap a filesystem path in double quotes for a Windows command line."""
    return '"' + path + '"'


def default_command() -> str:
    """The command line to register so the app starts at login.

    - **Frozen** (PyInstaller exe): the exe itself.
    - **From source**: the windowless interpreter (``pythonw.exe``) plus the
      repo's ``launch.py``, both as absolute paths so login can run it from any
      working directory. ``launch.py`` puts the venv's site-packages on the path.
    """
    if getattr(sys, "frozen", False):
        return _quote(sys.executable)

    exe_dir = os.path.dirname(sys.executable)
    pythonw = os.path.join(exe_dir, "pythonw.exe")
    if not os.path.exists(pythonw):
        pythonw = sys.executable  # fall back to whatever launched us

    pkg_dir = os.path.dirname(os.path.abspath(__file__))
    repo_root = os.path.dirname(pkg_dir)
    launcher = os.path.join(repo_root, "launch.py")
    if os.path.exists(launcher):
        return _quote(pythonw) + " " + _quote(launcher)
    # Last resort: run the module (relies on the repo being importable).
    return _quote(pythonw) + " -m " + APP_NAME.lower()


class StartupBackend:
    """Interface for a platform-specific startup mechanism."""

    def enable(self, name: str, command: str) -> None:
        raise NotImplementedError

    def disable(self, name: str) -> None:
        raise NotImplementedError

    def current(self, name: str) -> str | None:
        """Return the registered command for ``name``, or ``None`` if not set."""
        raise NotImplementedError

    def is_enabled(self, name: str) -> bool:
        return self.current(name) is not None

    def was_disabled_externally(self, name: str) -> bool:
        """Did the platform's OWN startup manager switch ``name`` OFF?

        On Windows that is Task Manager's Startup tab, which records its
        decision in the registry — never in our config. A platform without such
        a switch has nothing to report. The distinction matters on upgrade: an
        honest caller must read this before trusting a config flag that may
        predate the user's disable (see :func:`legacy_startup_was_disabled`).
        """
        return False

    def purge(self, name: str) -> None:
        """Remove every trace of ``name``, not just its Run value.

        :meth:`disable` is the user-facing "turn this off" for the app's OWN
        entry, which should keep any Task Manager state the user set. Purging is
        for a name that no longer exists at all, where a leftover StartupApproved
        flag would be orphaned junk.
        """
        self.disable(name)


class WindowsRegistryBackend(StartupBackend):
    """Registers startup via the per-user HKCU ``...\\CurrentVersion\\Run`` key.

    ``winreg_module`` is injectable so tests can pass an in-memory fake instead of
    touching the real registry; production leaves it ``None`` to use stdlib
    ``winreg``.
    """

    def __init__(self, run_key: str = _RUN_KEY, winreg_module=None,
                 approved_key: str = _APPROVED_KEY):
        if winreg_module is None:
            import winreg as winreg_module  # noqa: PLC0415 (Windows-only, lazy)
        self._winreg = winreg_module
        self._run_key = run_key
        self._approved_key = approved_key

    def enable(self, name: str, command: str) -> None:
        wr = self._winreg
        key = wr.CreateKey(wr.HKEY_CURRENT_USER, self._run_key)
        try:
            wr.SetValueEx(key, name, 0, wr.REG_SZ, command)
        finally:
            wr.CloseKey(key)
        # A prior Task Manager "disable" would otherwise keep Windows from
        # honoring the Run entry we just (re)wrote, so enabling would silently do
        # nothing. Clear it so turning us on actually turns us on.
        self._clear_approval(name)

    def disable(self, name: str) -> None:
        wr = self._winreg
        try:
            key = wr.OpenKey(wr.HKEY_CURRENT_USER, self._run_key, 0,
                             wr.KEY_SET_VALUE)
        except FileNotFoundError:
            return  # Run key doesn't exist -> nothing to remove
        try:
            try:
                wr.DeleteValue(key, name)
            except FileNotFoundError:
                pass  # value already absent -> disabled is the desired state
        finally:
            wr.CloseKey(key)

    def current(self, name: str) -> str | None:
        wr = self._winreg
        try:
            key = wr.OpenKey(wr.HKEY_CURRENT_USER, self._run_key, 0, wr.KEY_READ)
        except FileNotFoundError:
            return None
        try:
            try:
                value, _type = wr.QueryValueEx(key, name)
                return value
            except FileNotFoundError:
                return None
        finally:
            wr.CloseKey(key)

    def is_enabled(self, name: str) -> bool:
        """True only if we are registered AND not disabled in Task Manager.

        ``current()`` answers "is a Run command registered?"; this answers the
        honest "will Windows actually launch us at login?", which also depends on
        the StartupApproved flag the user can flip in Task Manager's Startup tab.
        """
        return self.current(name) is not None and not self._is_approval_disabled(name)

    def _is_approval_disabled(self, name: str) -> bool:
        """True when Task Manager's Startup tab has DISABLED this entry.

        The StartupApproved\\Run value is a REG_BINARY blob whose first byte
        encodes the state: even (0x02/0x06) = enabled, odd (0x03) = disabled. A
        missing key or value means the user never touched it there — not disabled.
        """
        wr = self._winreg
        try:
            key = wr.OpenKey(wr.HKEY_CURRENT_USER, self._approved_key, 0,
                             wr.KEY_READ)
        except FileNotFoundError:
            return False
        try:
            try:
                value, _type = wr.QueryValueEx(key, name)
            except FileNotFoundError:
                return False
        finally:
            wr.CloseKey(key)
        return bool(value) and value[0] % 2 == 1

    def was_disabled_externally(self, name: str) -> bool:
        """Task Manager's Startup-tab state for ``name`` (see the base class)."""
        return self._is_approval_disabled(name)

    def purge(self, name: str) -> None:
        """Delete the Run value AND any Task Manager enable/disable flag."""
        self.disable(name)
        self._clear_approval(name)

    def _clear_approval(self, name: str) -> None:
        """Remove any Task Manager "disabled" flag for this entry.

        Deleting the StartupApproved value returns the item to its default
        ENABLED state (Run value present, no override). Best-effort and
        idempotent — a missing key/value is already the desired state.
        """
        wr = self._winreg
        try:
            key = wr.OpenKey(wr.HKEY_CURRENT_USER, self._approved_key, 0,
                             wr.KEY_SET_VALUE)
        except FileNotFoundError:
            return
        try:
            try:
                wr.DeleteValue(key, name)
            except FileNotFoundError:
                pass
        finally:
            wr.CloseKey(key)


def get_backend() -> StartupBackend:
    """Return the startup backend for the current platform.

    Only Windows is implemented today; the abstraction leaves room for a macOS
    ``LaunchAgent`` backend (a plist in ``~/Library/LaunchAgents``) to be added
    here later.
    """
    if sys.platform.startswith("win"):
        return WindowsRegistryBackend()
    raise NotImplementedError(
        "Launch-on-login is only implemented on Windows so far.")


# --- public API (what the UI calls) -----------------------------------------

def enable(command: str | None = None, backend: StartupBackend | None = None) -> None:
    """Register the app to launch at login (idempotent)."""
    backend = backend or get_backend()
    backend.enable(APP_NAME, command or default_command())


def disable(backend: StartupBackend | None = None) -> None:
    """Remove the launch-at-login entry (idempotent)."""
    (backend or get_backend()).disable(APP_NAME)


def is_enabled(backend: StartupBackend | None = None) -> bool:
    """True if Windows will actually launch the app at login.

    Not merely "is a Run entry registered" — on Windows this also respects a
    disable set in Task Manager's Startup tab, so the answer matches reality.
    """
    return (backend or get_backend()).is_enabled(APP_NAME)


def current_command(backend: StartupBackend | None = None) -> str | None:
    """The command currently registered for launch-at-login, or ``None``."""
    return (backend or get_backend()).current(APP_NAME)


def set_enabled(enabled: bool, command: str | None = None,
                backend: StartupBackend | None = None) -> None:
    """Enable or disable launch-at-login from a single boolean (e.g. a checkbox)."""
    if enabled:
        enable(command, backend=backend)
    else:
        disable(backend=backend)


def legacy_is_registered(backend: StartupBackend | None = None) -> bool:
    """True if a launch-at-login entry still exists under the OLD app name."""
    return (backend or get_backend()).current(LEGACY_APP_NAME) is not None


def legacy_startup_was_disabled(backend: StartupBackend | None = None) -> bool:
    """True when Task Manager shows the OLD name's autostart switched OFF.

    Task Manager records a disable in the registry (StartupApproved), never in
    our config — so a migrated config.json can carry a stale
    ``launch_on_startup: true`` from before the user disabled TalkativeAI
    there. The registry flag is the user's actual last word on autostart, and
    :func:`purge_legacy` deletes it: any caller that intends to register the
    new name from the migrated config must read this FIRST and honor it, or an
    upgrade silently resurrects an autostart the user turned off (see the
    reconcile in ``__main__``).
    """
    return (backend or get_backend()).was_disabled_externally(LEGACY_APP_NAME)


def purge_legacy(backend: StartupBackend | None = None) -> bool:
    """Remove the old name's launch-at-login entry. Returns True if one existed.

    The Run COMMAND does not need to be inferred from the old entry: config.json
    carries ``launch_on_startup`` and is migrated wholesale, so the caller's
    normal reconcile re-registers under the new name from the user's setting.
    One thing here IS authoritative though, and purging destroys it — the old
    entry's Task Manager disable flag. Consult
    :func:`legacy_startup_was_disabled` BEFORE calling this, or a stale config
    ``true`` overrides a disable the user made in Task Manager. Beyond that,
    this only clears the stale entry that would otherwise start the old
    checkout at every login.
    """
    backend = backend or get_backend()
    existed = backend.current(LEGACY_APP_NAME) is not None
    backend.purge(LEGACY_APP_NAME)
    return existed
