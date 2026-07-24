"""Reliable, safe text insertion for Rekounts.

Public interface (unchanged for callers):

    TextInserter(mode="paste", ...).insert(text) -> InsertResult

`insert()` now RETURNS an outcome (see :class:`InsertResult`) instead of None so
the controller/history layer can record every dictation and keep it recoverable
even when pasting wasn't possible. The value is a ``str`` subclass, so existing
code that ignores the return keeps working and history can store it directly.

Design notes / why this file is shaped this way
------------------------------------------------
All platform-specific work lives behind a small backend object
(:class:`_Win32Backend` on Windows, :class:`_MacBackend` on macOS,
:class:`_NullBackend` elsewhere / on import failure). This keeps the policy in
:class:`TextInserter` fully unit-testable with a fake backend, and kept the
macOS backend a pure slot-in with no policy changes.

Robustness measures (each maps to an audited failure mode):
  * Clipboard backup/restore uses the native Win32 clipboard and preserves ALL
    reasonable formats (text, images via CF_DIB, files via CF_HDROP, and any
    registered format such as HTML/RTF) — not just text like pyperclip did.
  * Restore only happens if the clipboard still holds OUR text (checked via
    GetClipboardSequenceNumber), so we never clobber something the user copied
    between paste and restore.
  * Before synthesizing Ctrl+V we wait (bounded) for the user to release any
    physical modifier keys, so a held push-to-talk chord (e.g. Ctrl+Win) can't
    turn Ctrl+V into Ctrl+Win+V (the clipboard-history popup).
  * Elevated (admin) target windows are detected; a non-admin process cannot
    inject into them (Windows UIPI), so we return BLOCKED instead of silently
    doing nothing.
  * The foreground window is captured and re-checked; if focus moved, we abort
    with NO_TARGET rather than dumping text into the wrong app.
  * The keystroke path uses SendInput + KEYEVENTF_UNICODE (ctypes) instead of
    pynput's character typing (the documented drop-chars failure mode on Windows).

"Is a text field focused?" — decision & limits
----------------------------------------------
There is no cheap, universal Windows API for "the focused element accepts text":
  * UI Automation (IUIAutomation.GetFocusedElement -> CurrentControlType) is the
    closest, but it needs COM, can block, and browsers/Electron/UWP report control
    types inconsistently (many editable surfaces don't advertise Edit/Document).
  * GetGUIThreadInfo(...).hwndCaret only works for classic Win32 controls that
    create a *system* caret; modern apps draw their own caret, so it yields
    constant false negatives.
Robust field-level detection isn't achievable without heavy/unreliable deps, so we
DON'T attempt it. Instead we detect only the clear-cut "no target" cases cheaply
(no foreground window, or focus is the desktop/taskbar/alt-tab surface) and
otherwise attempt the paste and report the outcome honestly. History is the safety
net either way. See the PR for the full rationale.
"""

import logging
import sys
import time
from enum import Enum

log = logging.getLogger(__name__)


class InsertResult(str, Enum):
    """Outcome of an :meth:`TextInserter.insert` call.

    ``str`` subclass so ``result == "pasted"`` works and history can store it raw.
    """

    PASTED = "pasted"        # text placed via clipboard paste
    TYPED = "typed"          # text sent via synthesized keystrokes
    NO_TARGET = "no_target"  # no text surface focused / focus changed
    BLOCKED = "blocked"      # target is elevated (admin) — UIPI blocks injection
    FAILED = "failed"        # an unexpected error prevented insertion
    SKIPPED = "skipped"      # nothing to insert (empty text)

    def __str__(self) -> str:  # so f"{result}" / logging shows "pasted", not the enum repr
        return self.value


# ---------------------------------------------------------------------------
# Windows constants (kept local so the module has no hard pywin32 import at top)
# ---------------------------------------------------------------------------
CF_UNICODETEXT = 13
VK_CONTROL = 0x11
VK_MENU = 0x12      # Alt
VK_SHIFT = 0x10
VK_LWIN = 0x5B
VK_RWIN = 0x5C
VK_RETURN = 0x0D
VK_V = 0x56

# Clipboard formats backed by GDI/OLE handles that pywin32 cannot round-trip by
# value. We skip these on backup/restore; images still survive via CF_DIB and
# files via CF_HDROP, which DO round-trip.
_SKIP_CLIPBOARD_FORMATS = {
    2,      # CF_BITMAP        (use CF_DIB instead)
    3,      # CF_METAFILEPICT
    9,      # CF_PALETTE
    14,     # CF_ENHMETAFILE
    0x80,   # CF_OWNERDISPLAY
    0x82,   # CF_DSPBITMAP
    0x83,   # CF_DSPMETAFILEPICT
    0x8E,   # CF_DSPENHMETAFILE
}

# Foreground "windows" that are not a place text can land.
_NO_TARGET_CLASSES = {
    "Progman",                  # desktop
    "WorkerW",                  # desktop wallpaper host
    "Shell_TrayWnd",            # taskbar
    "Shell_SecondaryTrayWnd",   # secondary-monitor taskbar
    "DV2ControlHost",           # start menu / search flyout
    "MultitaskingViewFrame",    # task view
    "ForegroundStaging",        # alt-tab
    "XamlExplorerHostIslandWindow",  # alt-tab / task view (Win11)
}


# ---------------------------------------------------------------------------
# Backends
# ---------------------------------------------------------------------------
class _NullBackend:
    """Fallback backend for non-Windows or when the Win32 layer is unavailable.

    Preserves the app's original best-effort behavior (pyperclip + pynput) so the
    module never hard-fails; the guards degrade to no-ops.
    """

    available = False

    def __init__(self):
        self._kb = None
        self._pyperclip = None
        try:
            from pynput.keyboard import Controller
            self._kb = Controller()
        except Exception:  # pragma: no cover - only when pynput missing
            pass
        try:
            import pyperclip
            self._pyperclip = pyperclip
        except Exception:  # pragma: no cover
            pass

    # --- window / focus ---
    def foreground_window(self):
        return None

    def is_no_target(self, hwnd):
        return False

    def is_blocked(self, hwnd):
        return False

    # --- modifiers ---
    def modifiers_down(self):
        return False

    # --- clipboard ---
    def clipboard_sequence(self):
        return None

    def backup_clipboard(self):
        if self._pyperclip is None:
            return None
        try:
            return {"__text__": self._pyperclip.paste()}
        except Exception:
            return None

    def restore_clipboard(self, snapshot):
        if snapshot is None or self._pyperclip is None:
            return
        try:
            self._pyperclip.copy(snapshot.get("__text__", ""))
        except Exception:
            pass

    def set_clipboard_text(self, text):
        if self._pyperclip is None:
            raise RuntimeError("no clipboard available")
        self._pyperclip.copy(text)

    # --- input synthesis ---
    def send_paste(self):
        if self._kb is None:
            raise RuntimeError("no keyboard available")
        from pynput.keyboard import Key
        with self._kb.pressed(Key.ctrl):
            self._kb.press("v")
            self._kb.release("v")

    def type_unicode(self, text, delay=0.0):
        if self._kb is None:
            raise RuntimeError("no keyboard available")
        self._kb.type(text)


# macOS virtual key codes (kVK_*, Carbon HIToolbox — stable hardware codes).
_KVK_ANSI_V = 9
_KVK_RETURN = 36
# Left/right modifier keycodes, polled by modifiers_down(): a held push-to-talk
# chord (e.g. Ctrl+Cmd) would otherwise turn the synthesized Cmd+V into
# Ctrl+Cmd+V in the target app.
_KVK_MODIFIERS = (
    54, 55,   # right/left Command
    56, 60,   # left/right Shift
    58, 61,   # left/right Option
    59, 62,   # left/right Control
)
# CGEventKeyboardSetUnicodeString caps the string per event; 20 UTF-16 units is
# the commonly-safe chunk (Apple's own samples use small chunks).
_MAC_UNICODE_CHUNK = 20


class _MacBackend:
    """macOS backend built on Quartz (CoreGraphics events) + AppKit (NSPasteboard).

    Requires the pyobjc Quartz/Cocoa frameworks (already pulled in by pynput's
    darwin extra). Synthesized events need the user's **Accessibility** consent;
    without it macOS drops them silently — rekounts.permissions surfaces that at
    startup so it never looks like a broken app.

    Capability map (mirrors _Win32Backend's contract):
      * foreground "window"  -> the frontmost application's pid (NSWorkspace).
        There is no cheap stable per-window handle across apps on macOS; the
        frontmost app is the right granularity for "did focus move while we
        transcribed" and is what Cmd+V lands in anyway.
      * clipboard sequence   -> NSPasteboard.changeCount (bumps on every write,
        exactly like GetClipboardSequenceNumber).
      * clipboard backup     -> every type of every pasteboard item, restored
        via new NSPasteboardItems — images/RTF/files survive, not just text.
      * paste                -> a Cmd+V keyboard event pair posted at the HID
        tap with the Command flag set on the events themselves (no separate
        modifier press to get stuck).
      * typing               -> CGEventKeyboardSetUnicodeString in small
        chunks; newline is sent as a real Return keycode like the Windows path.
      * is_blocked           -> always False: macOS has no UIPI equivalent
        (Accessibility consent is all-or-nothing and reported at startup).
    """

    available = True

    def __init__(self, quartz=None, appkit=None):
        if quartz is None:
            import Quartz as quartz
        if appkit is None:
            import AppKit as appkit
        self._q = quartz
        self._ak = appkit
        self._pasteboard = appkit.NSPasteboard.generalPasteboard()

    # -- window / focus -----------------------------------------------------
    def foreground_window(self):
        try:
            app = self._ak.NSWorkspace.sharedWorkspace().frontmostApplication()
            if app is None:
                return None
            return int(app.processIdentifier())
        except Exception:
            return None

    def is_no_target(self, hwnd):
        # No frontmost app at all is the only clear-cut "text cannot land
        # anywhere" case; everything else gets an honest paste attempt.
        return not hwnd

    def is_blocked(self, hwnd):
        return False

    # -- modifiers ----------------------------------------------------------
    def modifiers_down(self):
        try:
            state = self._q.kCGEventSourceStateHIDSystemState
            for code in _KVK_MODIFIERS:
                if self._q.CGEventSourceKeyState(state, code):
                    return True
            return False
        except Exception:
            return False

    # -- clipboard ----------------------------------------------------------
    def clipboard_sequence(self):
        try:
            return int(self._pasteboard.changeCount())
        except Exception:
            return None

    def backup_clipboard(self):
        try:
            items = self._pasteboard.pasteboardItems() or []
            snapshot = []
            for item in items:
                data = {}
                for t in (item.types() or []):
                    try:
                        payload = item.dataForType_(t)
                        if payload is not None:
                            data[str(t)] = payload
                    except Exception:
                        pass   # a type that can't be read by value; skip it
                if data:
                    snapshot.append(data)
            return snapshot
        except Exception:
            return None

    def restore_clipboard(self, snapshot):
        if not snapshot:
            return
        try:
            items = []
            for entry in snapshot:
                item = self._ak.NSPasteboardItem.alloc().init()
                for t, payload in entry.items():
                    try:
                        item.setData_forType_(payload, t)
                    except Exception:
                        pass   # best-effort per type
                items.append(item)
            self._pasteboard.clearContents()
            self._pasteboard.writeObjects_(items)
        except Exception:
            pass   # best-effort, like the Win32 restore

    def set_clipboard_text(self, text):
        self._pasteboard.clearContents()
        ok = self._pasteboard.setString_forType_(
            text, self._ak.NSPasteboardTypeString)
        if not ok:
            raise RuntimeError("NSPasteboard rejected the text")

    # -- input synthesis ----------------------------------------------------
    def _post(self, event):
        self._q.CGEventPost(self._q.kCGHIDEventTap, event)

    def send_paste(self):
        """Synthesize a clean Cmd+V (physical modifiers already released)."""
        q = self._q
        down = q.CGEventCreateKeyboardEvent(None, _KVK_ANSI_V, True)
        up = q.CGEventCreateKeyboardEvent(None, _KVK_ANSI_V, False)
        # The Command flag rides on the V events themselves, so there is no
        # separate synthetic modifier press that could be left stuck down.
        q.CGEventSetFlags(down, q.kCGEventFlagMaskCommand)
        q.CGEventSetFlags(up, q.kCGEventFlagMaskCommand)
        self._post(down)
        self._post(up)

    def _send_keycode(self, code):
        q = self._q
        self._post(q.CGEventCreateKeyboardEvent(None, code, True))
        self._post(q.CGEventCreateKeyboardEvent(None, code, False))

    def _send_text_chunk(self, chunk):
        q = self._q
        # Length is in UTF-16 code units (what CGEventKeyboardSetUnicodeString
        # expects), not Python characters — astral-plane chars count as two.
        units = len(chunk.encode("utf-16-le")) // 2
        down = q.CGEventCreateKeyboardEvent(None, 0, True)
        q.CGEventKeyboardSetUnicodeString(down, units, chunk)
        up = q.CGEventCreateKeyboardEvent(None, 0, False)
        q.CGEventKeyboardSetUnicodeString(up, units, chunk)
        self._post(down)
        self._post(up)

    def type_unicode(self, text, delay=0.0):
        # Mirror the Windows path: \r dropped, \n as a real Return keycode
        # (many apps ignore a "typed" newline character), the rest in unicode
        # chunks that need no keymap and survive any layout.
        for line_i, line in enumerate(text.replace("\r", "").split("\n")):
            if line_i:
                self._send_keycode(_KVK_RETURN)
                if delay:
                    time.sleep(delay)
            if delay:
                # Per-character pacing for apps that drop fast synthetic input.
                for ch in line:
                    self._send_text_chunk(ch)
                    time.sleep(delay)
            else:
                for start in range(0, len(line), _MAC_UNICODE_CHUNK):
                    self._send_text_chunk(line[start:start + _MAC_UNICODE_CHUNK])


class _Win32Backend:
    """Windows backend built on ctypes (user32/kernel32/advapi32) + win32clipboard.

    Every capability is guarded independently: if one Win32 call is unavailable we
    degrade that single feature (e.g. skip the elevation check) rather than losing
    the whole backend.
    """

    available = True

    _INPUT_KEYBOARD = 1
    _KEYEVENTF_KEYUP = 0x0002
    _KEYEVENTF_UNICODE = 0x0004

    def __init__(self):
        import ctypes
        from ctypes import wintypes

        self._ctypes = ctypes
        self._wintypes = wintypes
        self._user32 = ctypes.WinDLL("user32", use_last_error=True)
        self._kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        try:
            self._advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
        except Exception:  # pragma: no cover
            self._advapi32 = None

        # GetAsyncKeyState returns SHORT; high bit set == key currently down.
        self._user32.GetAsyncKeyState.restype = ctypes.c_short
        self._user32.GetAsyncKeyState.argtypes = [ctypes.c_int]
        self._user32.GetForegroundWindow.restype = wintypes.HWND
        self._user32.GetClipboardSequenceNumber.restype = wintypes.DWORD
        self._user32.GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
        self._user32.GetClassNameW.restype = ctypes.c_int
        self._user32.GetWindowThreadProcessId.argtypes = [
            wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
        self._user32.GetWindowThreadProcessId.restype = wintypes.DWORD

        try:
            import win32clipboard
            self._clip = win32clipboard
        except Exception:  # pragma: no cover - pywin32 is in requirements
            self._clip = None

        self._we_elevated = None  # cached; None until first check

        self._build_input_structs()

    # -- SendInput plumbing -------------------------------------------------
    def _build_input_structs(self):
        ctypes = self._ctypes
        wintypes = self._wintypes

        ULONG_PTR = wintypes.WPARAM  # pointer-sized, correct on 32- and 64-bit

        class KEYBDINPUT(ctypes.Structure):
            _fields_ = [
                ("wVk", wintypes.WORD),
                ("wScan", wintypes.WORD),
                ("dwFlags", wintypes.DWORD),
                ("time", wintypes.DWORD),
                ("dwExtraInfo", ULONG_PTR),
            ]

        class MOUSEINPUT(ctypes.Structure):
            _fields_ = [
                ("dx", wintypes.LONG),
                ("dy", wintypes.LONG),
                ("mouseData", wintypes.DWORD),
                ("dwFlags", wintypes.DWORD),
                ("time", wintypes.DWORD),
                ("dwExtraInfo", ULONG_PTR),
            ]

        class HARDWAREINPUT(ctypes.Structure):
            _fields_ = [
                ("uMsg", wintypes.DWORD),
                ("wParamL", wintypes.WORD),
                ("wParamH", wintypes.WORD),
            ]

        class _INPUTunion(ctypes.Union):
            _fields_ = [("ki", KEYBDINPUT), ("mi", MOUSEINPUT), ("hi", HARDWAREINPUT)]

        class INPUT(ctypes.Structure):
            _anonymous_ = ("u",)
            _fields_ = [("type", wintypes.DWORD), ("u", _INPUTunion)]

        self._KEYBDINPUT = KEYBDINPUT
        self._INPUT = INPUT
        self._user32.SendInput.argtypes = [
            wintypes.UINT, ctypes.POINTER(INPUT), ctypes.c_int]
        self._user32.SendInput.restype = wintypes.UINT

    def _key_event(self, vk=0, scan=0, flags=0):
        inp = self._INPUT()
        inp.type = self._INPUT_KEYBOARD
        inp.ki = self._KEYBDINPUT(vk, scan, flags, 0, 0)
        return inp

    def _send(self, inputs):
        arr = (self._INPUT * len(inputs))(*inputs)
        n = self._user32.SendInput(len(inputs), arr, self._ctypes.sizeof(self._INPUT))
        if n != len(inputs):
            raise OSError("SendInput injected %d of %d events" % (n, len(inputs)))

    # -- window / focus -----------------------------------------------------
    def foreground_window(self):
        try:
            return self._user32.GetForegroundWindow()
        except Exception:
            return None

    def _class_name(self, hwnd):
        buf = self._ctypes.create_unicode_buffer(256)
        n = self._user32.GetClassNameW(hwnd, buf, 256)
        return buf.value if n else ""

    def is_no_target(self, hwnd):
        if not hwnd:
            return True
        try:
            return self._class_name(hwnd) in _NO_TARGET_CLASSES
        except Exception:
            return False

    def _pid_of_window(self, hwnd):
        pid = self._wintypes.DWORD()
        self._user32.GetWindowThreadProcessId(hwnd, self._ctypes.byref(pid))
        return pid.value

    def _token_is_elevated(self, hproc):
        """True/False, or None if it can't be determined."""
        if self._advapi32 is None:
            return None
        ctypes = self._ctypes
        wintypes = self._wintypes
        TOKEN_QUERY = 0x0008
        TokenElevation = 20
        hToken = wintypes.HANDLE()
        if not self._advapi32.OpenProcessToken(
                hproc, TOKEN_QUERY, ctypes.byref(hToken)):
            return None
        try:
            elevation = wintypes.DWORD()
            size = wintypes.DWORD()
            ok = self._advapi32.GetTokenInformation(
                hToken, TokenElevation, ctypes.byref(elevation),
                ctypes.sizeof(elevation), ctypes.byref(size))
            if not ok:
                return None
            return bool(elevation.value)
        finally:
            self._kernel32.CloseHandle(hToken)

    def _self_elevated(self):
        if self._advapi32 is None:
            return False
        try:
            hproc = self._kernel32.GetCurrentProcess()  # pseudo-handle
            elev = self._token_is_elevated(hproc)
            return bool(elev)
        except Exception:
            return False

    def is_blocked(self, hwnd):
        """True if UIPI would block us from injecting into hwnd.

        A non-elevated process cannot send input to a higher-integrity (elevated)
        window. If we can't even open the target process we treat it as blocked —
        that access failure is itself the UIPI signal.
        """
        if not hwnd:
            return False
        try:
            if self._we_elevated is None:
                self._we_elevated = self._self_elevated()
            if self._we_elevated:
                return False  # elevated: we can inject anywhere
            pid = self._pid_of_window(hwnd)
            if not pid:
                return False
            PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
            hproc = self._kernel32.OpenProcess(
                PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
            if not hproc:
                return True  # cannot open a higher-integrity process
            try:
                elev = self._token_is_elevated(hproc)
                return bool(elev)  # unknown -> don't over-block
            finally:
                self._kernel32.CloseHandle(hproc)
        except Exception:
            return False

    # -- modifiers ----------------------------------------------------------
    def modifiers_down(self):
        try:
            for vk in (VK_CONTROL, VK_MENU, VK_SHIFT, VK_LWIN, VK_RWIN):
                if self._user32.GetAsyncKeyState(vk) & 0x8000:
                    return True
            return False
        except Exception:
            return False

    # -- clipboard ----------------------------------------------------------
    def clipboard_sequence(self):
        try:
            return self._user32.GetClipboardSequenceNumber()
        except Exception:
            return None

    def _open_clipboard(self, retries=6):
        """OpenClipboard, retrying briefly — another app may hold it momentarily."""
        if self._clip is None:
            return False
        for _ in range(retries):
            try:
                self._clip.OpenClipboard()
                return True
            except Exception:
                time.sleep(0.01)
        return False

    def backup_clipboard(self):
        if self._clip is None:
            return None
        if not self._open_clipboard():
            return None
        data = {}
        try:
            fmt = 0
            while True:
                fmt = self._clip.EnumClipboardFormats(fmt)
                if not fmt:
                    break
                if fmt in _SKIP_CLIPBOARD_FORMATS:
                    continue
                try:
                    data[fmt] = self._clip.GetClipboardData(fmt)
                except Exception:
                    pass  # some formats can't be read by value; skip them
        finally:
            self._clip.CloseClipboard()
        return data

    def restore_clipboard(self, snapshot):
        if snapshot is None or self._clip is None:
            return
        if not self._open_clipboard():
            return
        try:
            self._clip.EmptyClipboard()
            for fmt, val in snapshot.items():
                try:
                    self._clip.SetClipboardData(fmt, val)
                except Exception:
                    pass  # best-effort per format
        finally:
            self._clip.CloseClipboard()

    def set_clipboard_text(self, text):
        if self._clip is None:
            raise RuntimeError("win32clipboard unavailable")
        if not self._open_clipboard():
            raise RuntimeError("could not open clipboard")
        try:
            self._clip.EmptyClipboard()
            self._clip.SetClipboardData(CF_UNICODETEXT, text)
        finally:
            self._clip.CloseClipboard()

    # -- input synthesis ----------------------------------------------------
    def send_paste(self):
        """Synthesize a clean Ctrl+V (physical modifiers already released)."""
        self._send([
            self._key_event(vk=VK_CONTROL),
            self._key_event(vk=VK_V),
            self._key_event(vk=VK_V, flags=self._KEYEVENTF_KEYUP),
            self._key_event(vk=VK_CONTROL, flags=self._KEYEVENTF_KEYUP),
        ])

    def _send_unicode(self, code):
        self._send([
            self._key_event(scan=code, flags=self._KEYEVENTF_UNICODE),
            self._key_event(scan=code,
                            flags=self._KEYEVENTF_UNICODE | self._KEYEVENTF_KEYUP),
        ])

    def _send_vk(self, vk):
        self._send([
            self._key_event(vk=vk),
            self._key_event(vk=vk, flags=self._KEYEVENTF_KEYUP),
        ])

    def type_unicode(self, text, delay=0.0):
        for ch in text:
            if ch == "\r":
                continue
            if ch == "\n":
                self._send_vk(VK_RETURN)
            else:
                code = ord(ch)
                if code > 0xFFFF:  # astral plane -> UTF-16 surrogate pair
                    code -= 0x10000
                    self._send_unicode(0xD800 + (code >> 10))
                    self._send_unicode(0xDC00 + (code & 0x3FF))
                else:
                    self._send_unicode(code)
            if delay:
                time.sleep(delay)


def _make_backend():
    if sys.platform == "win32":
        try:
            return _Win32Backend()
        except Exception as e:  # pragma: no cover
            log.warning("Win32 insertion backend unavailable (%s); "
                        "falling back to pyperclip/pynput", e)
    elif sys.platform == "darwin":
        try:
            return _MacBackend()
        except Exception as e:  # pragma: no cover
            log.warning("macOS insertion backend unavailable (%s); "
                        "falling back to pyperclip/pynput", e)
    return _NullBackend()


# ---------------------------------------------------------------------------
# Policy
# ---------------------------------------------------------------------------
class TextInserter:
    """Insert transcribed text into the focused application.

    Parameters
    ----------
    mode:
        ``"paste"`` (clipboard, default) or ``"keystroke"`` (synthesized typing).
    restore_delay:
        Seconds to wait after Ctrl+V before restoring the clipboard. Raise this for
        heavy apps that consume the clipboard slowly. Restore is additionally
        gated on the clipboard sequence number so a slow paste never causes us to
        clobber newer content the user copied in the meantime.
    key_delay:
        Inter-key delay (seconds) for the keystroke path. Some apps drop very fast
        synthesized input; a small value (e.g. 0.003) makes typing more reliable.
    modifier_timeout:
        Max seconds to wait for physical modifier keys to be released before
        sending the paste/typing. Prevents a held push-to-talk chord from turning
        Ctrl+V into an unintended shortcut.
    on_notice:
        Optional ``callable(str)`` invoked with a human-readable message when a
        dictation cannot be inserted (no target / elevated window / failure). The
        returned :class:`InsertResult` is the primary signal; this callback is a
        convenience so notices work before the history layer is wired.
    backend:
        Injectable platform backend (for tests). Defaults to the platform backend.
    """

    def __init__(self, mode="paste", restore_delay=0.2, *, key_delay=0.0,
                 modifier_timeout=2.0, on_notice=None, backend=None):
        self.mode = mode
        self.restore_delay = restore_delay
        self.key_delay = key_delay
        self.modifier_timeout = modifier_timeout
        self.on_notice = on_notice
        self.backend = backend if backend is not None else _make_backend()

    # -- public -------------------------------------------------------------
    def capture_target(self):
        """Return the current foreground window handle (opaque).

        The controller can call this at hotkey-release time and pass the result to
        :meth:`insert` so a focus change during the (~0.7s) transcription is
        detected. Without it, :meth:`insert` captures the target at call time,
        which still catches focus changes during the modifier-release wait.
        """
        return self.backend.foreground_window()

    def insert(self, text: str, target=None) -> InsertResult:
        """Insert ``text``; return an :class:`InsertResult` describing the outcome.

        ``target`` — optional expected foreground window (from
        :meth:`capture_target`). If focus has moved away from it, insertion is
        aborted with ``NO_TARGET`` rather than landing text in the wrong app.
        """
        if not text:
            return InsertResult.SKIPPED

        expected = target if target is not None else self.backend.foreground_window()

        if self.mode == "keystroke":
            return self._notify(self._do_type(text, expected))
        try:
            result = self._do_paste(text, expected)
        except Exception as e:
            log.warning("paste failed (%s); using keystroke fallback", e)
            try:
                result = self._do_type(text, expected)
            except Exception as e2:
                log.error("keystroke fallback also failed: %s", e2)
                result = InsertResult.FAILED
        return self._notify(result)

    # -- internals ----------------------------------------------------------
    def _wait_for_modifiers(self):
        """Block until physical modifiers are released, or the timeout elapses."""
        deadline = time.monotonic() + self.modifier_timeout
        while self.backend.modifiers_down():
            if time.monotonic() >= deadline:
                log.warning("modifiers still held after %.1fs; proceeding anyway",
                            self.modifier_timeout)
                return False
            time.sleep(0.01)
        return True

    def _guard(self, expected):
        """Return an InsertResult to abort with, or None to proceed.

        Runs the modifier-release wait first (focus can change during it), then
        re-reads the foreground window and checks the no-target / focus-change /
        elevation conditions against that fresh value.
        """
        self._wait_for_modifiers()
        hwnd = self.backend.foreground_window()
        if self.backend.is_no_target(hwnd):
            return InsertResult.NO_TARGET
        if expected is not None and hwnd is not None and hwnd != expected:
            log.info("foreground window changed before insert; aborting")
            return InsertResult.NO_TARGET
        if self.backend.is_blocked(hwnd):
            return InsertResult.BLOCKED
        return None

    def _do_paste(self, text, expected):
        abort = self._guard(expected)
        if abort is not None:
            return abort
        b = self.backend
        snapshot = b.backup_clipboard()
        b.set_clipboard_text(text)
        seq_ours = b.clipboard_sequence()
        b.send_paste()
        time.sleep(self.restore_delay)
        # Only restore if the clipboard still holds our text. If the sequence
        # number advanced, something else wrote the clipboard after us and
        # restoring the old backup would clobber it.
        seq_now = b.clipboard_sequence()
        if seq_ours is None or seq_now is None or seq_now == seq_ours:
            b.restore_clipboard(snapshot)
        else:
            log.info("clipboard changed after paste; skipping restore to avoid clobber")
        return InsertResult.PASTED

    def _do_type(self, text, expected):
        abort = self._guard(expected)
        if abort is not None:
            return abort
        self.backend.type_unicode(text, self.key_delay)
        return InsertResult.TYPED

    def _notify(self, result):
        if self.on_notice is None:
            return result
        msg = {
            InsertResult.NO_TARGET:
                "No text field in focus — nothing was pasted.",
            InsertResult.BLOCKED:
                "Can't paste into an admin window. Run Rekounts as "
                "administrator to dictate there.",
            InsertResult.FAILED:
                "Couldn't insert the dictated text.",
        }.get(result)
        if msg:
            try:
                self.on_notice(msg)
            except Exception:
                pass
        return result
