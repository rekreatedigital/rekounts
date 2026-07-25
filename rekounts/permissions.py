"""macOS permission (TCC) detection for first-run onboarding.

macOS gates each of Rekounts' three core capabilities behind a separate,
per-app user consent, and denies them SILENTLY — no dialog, no error code the
app can catch at the point of use, the events simply never arrive:

  * **Input Monitoring** — the global hotkey listener (pynput's event tap)
    receives no key events without it.
  * **Accessibility** — synthesized keystrokes (the Cmd+V paste, and typed
    delivery in keystroke mode) are dropped by the window server without it.
    Note *dropped*, not refused: ``CGEventPost`` reports no error, so without
    this check a missing grant looks exactly like a dictation that vanished.
  * **Microphone** — recording; this one at least prompts automatically the
    first time the mic is opened.

A missing permission is therefore indistinguishable from a broken app unless
we check explicitly and say so. This module does the checking; ``__main__``
turns the answers into tray notices at startup.

Everything is defensive and injectable:

  * On any platform but darwin every check returns ``None`` ("not applicable")
    and :func:`missing_permission_messages` returns ``[]``.
  * The pyobjc frameworks are imported lazily per check; an import or call
    failure reads as ``None`` ("unknown"), never an exception — a missing
    wheel must not take down startup, and "unknown" is deliberately NOT
    reported as missing (no false alarms on machines we cannot read).
  * ``check_permissions`` takes the platform, each probe, and whether this is a
    frozen build as parameters, so the policy is unit-testable with fakes on
    every OS (the pattern of tests/test_startup.py's registry fakes).

The guidance is per-BUILD as well as per-OS, because macOS grants a consent to
the running bundle: from source that bundle is the terminal, not Rekounts. See
:func:`_enable_step`.
"""
from __future__ import annotations

import logging
import sys
from dataclasses import dataclass

log = logging.getLogger(__name__)

# AVAuthorizationStatus values (AVFoundation).
_AV_NOT_DETERMINED = 0
_AV_RESTRICTED = 1
_AV_DENIED = 2
_AV_AUTHORIZED = 3


@dataclass
class PermissionState:
    """One capability's consent state: granted True/False, or None = unknown /
    not yet determined (the OS will prompt on first use)."""

    name: str
    granted: bool | None
    guidance: str


def _probe_input_monitoring():
    """True/False per CGPreflightListenEventAccess, or None if unreadable.

    Preflight only — never CGRequestListenEventAccess here: checking must not
    pop a system dialog at every launch. The guidance text tells the user
    where to grant it.
    """
    try:
        import Quartz
        return bool(Quartz.CGPreflightListenEventAccess())
    except Exception:
        return None


def _probe_accessibility():
    """True/False per AXIsProcessTrusted, or None if unreadable."""
    try:
        from ApplicationServices import AXIsProcessTrusted
        return bool(AXIsProcessTrusted())
    except Exception:
        return None


def _probe_microphone():
    """True/False/None for microphone consent (None = not yet asked/unknown).

    ``notDetermined`` maps to None on purpose: the first real recording makes
    macOS show its own consent prompt, which is the best possible onboarding —
    warning beforehand would be noise. Only an explicit denial is worth a
    notice.
    """
    try:
        import AVFoundation
        status = AVFoundation.AVCaptureDevice.authorizationStatusForMediaType_(
            AVFoundation.AVMediaTypeAudio)
        if status in (_AV_DENIED, _AV_RESTRICTED):
            return False
        if status == _AV_AUTHORIZED:
            return True
        return None
    except Exception:
        return None


# The System Settings pane path for each consent, spelled out because the
# panes moved in macOS 13+ and users reasonably cannot find them.
_SETTINGS_PATH = "System Settings > Privacy & Security > %s"


def _enable_step(pane: str, frozen: bool, reopen: bool = True) -> str:
    """Where to grant one consent — naming the app macOS will actually list.

    macOS attributes a TCC consent to the running BUNDLE, and a from-source run
    is not Rekounts.app: the bundle is whatever launched Python, i.e. the
    terminal or editor the app was started in. So the old advice — "Enable
    Rekounts under ... Input Monitoring" — sent a source user hunting for an
    entry that is not in the list and cannot be added, from which the only
    reasonable conclusion is that the app is broken.

    The packaged .app keeps today's wording verbatim, because there it is
    exactly right. We deliberately do NOT try to work out WHICH terminal is
    hosting us: that needs native APIs this port should not grow before it has
    run on real hardware, and "your terminal, or whichever app you started it
    from" is already enough to find the row.
    """
    where = _SETTINGS_PATH % pane
    tail = ", then quit and reopen Rekounts" if reopen else ""
    if frozen:
        return f"Enable Rekounts under {where}{tail}."
    return (
        "Running from source, macOS gives this to the app Rekounts was "
        "launched from, so “Rekounts” will not appear in the list. Enable "
        f"your terminal (or whichever app you started it from) under {where}, "
        "then quit that app and start Rekounts again.")


def check_permissions(platform=None, input_monitoring=None, accessibility=None,
                      microphone=None, frozen=None) -> list[PermissionState]:
    """The three consent states, with human guidance for each.

    All probes injectable for tests; production passes nothing and gets the
    real (lazy pyobjc) probes. Non-darwin platforms have no TCC — empty list.

    ``frozen`` selects which app the guidance tells the user to enable (see
    :func:`_enable_step`) and is injectable for the same reason the probes are:
    both branches have to be assertable without building a .app.
    """
    platform = platform if platform is not None else sys.platform
    if platform != "darwin":
        return []
    if frozen is None:
        frozen = getattr(sys, "frozen", False)
    input_monitoring = input_monitoring or _probe_input_monitoring
    accessibility = accessibility or _probe_accessibility
    microphone = microphone or _probe_microphone

    def read(probe):
        """A raising probe reads as unknown — never as denied, never as a
        crash: a broken check must not fabricate a scary permission toast."""
        try:
            return probe()
        except Exception:
            return None

    return [
        PermissionState(
            "Input Monitoring", read(input_monitoring),
            "Rekounts can't see the dictation hotkey. "
            + _enable_step("Input Monitoring", frozen)),
        PermissionState(
            "Accessibility", read(accessibility),
            "Rekounts can't paste dictated text. "
            + _enable_step("Accessibility", frozen)),
        PermissionState(
            "Microphone", read(microphone),
            "Rekounts can't hear you: microphone access is denied. "
            + _enable_step("Microphone", frozen, reopen=False)),
    ]


def missing_permission_messages(states: list[PermissionState] | None = None
                                ) -> list[str]:
    """Messages worth showing the user: only DEFINITE denials (granted False).

    ``None`` (unknown, or a consent macOS will prompt for on first use) is
    deliberately silent — warning about what we cannot read produces false
    alarms, and the mic's own system prompt is better onboarding than a toast.
    """
    if states is None:
        states = check_permissions()
    return [s.guidance for s in states if s.granted is False]
