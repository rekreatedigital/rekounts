"""Reproduction harness for the Win32 keystroke-injection corruption bug.

Why this exists
---------------
The shipped keystroke path (``_Win32Backend.type_unicode``) sent **one SendInput
call per character**. A long transcript is therefore a multi-second stream of
thousands of independent injections, and the OS input queue stays wide open
between them. Anything the user physically does mid-burst — most naturally
re-pressing the dictation hotkey, which holds Ctrl+Win — interleaves into the
stream and combines with the characters that have not been sent yet. The
result the owner reported: the first words arrive intact, the rest degrades
into control codes and stray symbols.

This harness makes that mechanism observable and measurable without needing a
human to fumble the hotkey at the right moment:

  * a real top-level Win32 EDIT control is the receiver (a genuine target with
    a genuine message pump — not a mock),
  * an injector thread types a passage through either the legacy per-character
    loop or the current backend,
  * an "abuser" thread waits until the receiver has actually accepted N
    characters, then holds a physical-looking modifier down for a while.

Triggering on *observed progress* rather than a sleep makes the reproduction
deterministic on any machine, whether or not the app's keyboard hook is
installed to slow the burst down.

Usage
-----
    python tools/injection_harness.py --mode legacy    # shows the corruption
    python tools/injection_harness.py --mode current   # shows the fix holding

    --clean         no mid-burst abuse (baseline: both modes must be perfect)
    --words N       length of the generated passage
    --trigger N     start the abuse after N characters have landed
    --hold MS       how long to hold the modifier down

Exit code is 0 when the received text matches what was sent, 1 otherwise, so
the two runs can be scripted into before/after evidence.
"""

import argparse
import ctypes
import sys
import threading
import time
from ctypes import wintypes

# --- window / control style bits -------------------------------------------
WS_OVERLAPPEDWINDOW = 0x00CF0000
WS_VISIBLE = 0x10000000
WS_VSCROLL = 0x00200000
ES_MULTILINE = 0x0004
ES_AUTOVSCROLL = 0x0040
SW_SHOW = 5
PM_REMOVE = 0x0001
WM_SETTEXT = 0x000C

VK_CONTROL = 0x11
VK_SHIFT = 0x10
VK_MENU = 0x12
VK_LWIN = 0x5B
VK_ESCAPE = 0x1B

_MODIFIERS = {
    "ctrl": (VK_CONTROL,),
    "shift": (VK_SHIFT,),
    "alt": (VK_MENU,),
    # The real dictation chord. Held Win+<letter> fires OS shortcuts that can
    # yank focus away mid-run, so this is opt-in rather than the default.
    "ctrlwin": (VK_CONTROL, VK_LWIN),
}


# ---------------------------------------------------------------------------
# The passage
# ---------------------------------------------------------------------------
_SENTENCES = [
    "The quick brown fox jumps over the lazy dog while the team reviews the "
    "quarterly numbers one more time.",
    "Please schedule the follow up call for Tuesday afternoon and copy the "
    "operations group on the invitation.",
    "We agreed that the migration should happen after the release freeze lifts "
    "rather than during the busy week.",
    "Send the revised draft to legal, then loop back with me once they have "
    "signed off on the wording.",
    "Recording quality matters more than raw model size for short utterances "
    "in a noisy open plan office.",
]


def build_passage(words):
    """A deterministic passage of roughly ``words`` words."""
    out = []
    count = 0
    i = 0
    while count < words:
        s = _SENTENCES[i % len(_SENTENCES)]
        out.append(s)
        count += len(s.split())
        i += 1
    return " ".join(out)


# ---------------------------------------------------------------------------
# Receiver window
# ---------------------------------------------------------------------------
class Receiver:
    """A real top-level EDIT control that collects whatever gets typed at it.

    A stock EDIT is deliberate: it is an ordinary Win32 text surface with the
    ordinary translate/dispatch path, so what lands in it is what would land in
    Notepad's edit area.
    """

    def __init__(self, user32, kernel32):
        self.user32 = user32
        self.kernel32 = kernel32
        self.hwnd = None

    def create(self):
        u = self.user32
        u.CreateWindowExW.argtypes = [
            wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD,
            ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
            wintypes.HWND, wintypes.HMENU, wintypes.HINSTANCE, wintypes.LPVOID]
        u.CreateWindowExW.restype = wintypes.HWND
        self.kernel32.GetModuleHandleW.restype = wintypes.HMODULE
        self.kernel32.GetModuleHandleW.argtypes = [wintypes.LPCWSTR]

        hinst = self.kernel32.GetModuleHandleW(None)
        self.hwnd = u.CreateWindowExW(
            0, "EDIT", "rekounts injection harness",
            WS_OVERLAPPEDWINDOW | WS_VISIBLE | WS_VSCROLL
            | ES_MULTILINE | ES_AUTOVSCROLL,
            120, 120, 900, 500, None, None, hinst, None)
        if not self.hwnd:
            raise ctypes.WinError(ctypes.get_last_error())
        u.ShowWindow(self.hwnd, SW_SHOW)
        return self.hwnd

    def focus(self):
        """Make the receiver the foreground window and give it keyboard focus.

        Windows only hands foreground to a process that already has it, so the
        AttachThreadInput dance is the standard way to make this reliable when
        the caller is a console process.
        """
        u = self.user32
        u.SetForegroundWindow.argtypes = [wintypes.HWND]
        u.GetWindowThreadProcessId.argtypes = [
            wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
        u.GetWindowThreadProcessId.restype = wintypes.DWORD

        for attempt in range(20):
            u.SetForegroundWindow(self.hwnd)
            u.SetFocus(self.hwnd)
            if u.GetForegroundWindow() == self.hwnd:
                return True
            # Attach our input queue to the current foreground thread's, which
            # lifts the foreground lock for the duration.
            fg = u.GetForegroundWindow()
            if fg:
                cur = self.kernel32.GetCurrentThreadId()
                other = u.GetWindowThreadProcessId(fg, None)
                if other and other != cur:
                    u.AttachThreadInput(cur, other, True)
                    u.SetForegroundWindow(self.hwnd)
                    u.SetFocus(self.hwnd)
                    u.AttachThreadInput(cur, other, False)
            if u.GetForegroundWindow() == self.hwnd:
                return True
            self.pump()
            time.sleep(0.05)
        return u.GetForegroundWindow() == self.hwnd

    def clear(self):
        self.user32.SendMessageW(self.hwnd, WM_SETTEXT, 0, "")

    def text_length(self):
        return self.user32.GetWindowTextLengthW(self.hwnd)

    def text(self):
        n = self.user32.GetWindowTextLengthW(self.hwnd)
        buf = ctypes.create_unicode_buffer(n + 2)
        self.user32.GetWindowTextW(self.hwnd, buf, n + 2)
        return buf.value

    def pump(self):
        """Drain pending messages. TranslateMessage is what turns the injected
        VK_PACKET key events into the WM_CHARs the EDIT control consumes."""
        msg = wintypes.MSG()
        while self.user32.PeekMessageW(ctypes.byref(msg), None, 0, 0, PM_REMOVE):
            self.user32.TranslateMessage(ctypes.byref(msg))
            self.user32.DispatchMessageW(ctypes.byref(msg))

    def pump_until(self, done, drain=0.75):
        """Pump until ``done`` is set, then keep pumping through a drain window
        so trailing injected events are all accounted for."""
        while not done.is_set():
            self.pump()
            time.sleep(0.001)
        end = time.monotonic() + drain
        while time.monotonic() < end:
            self.pump()
            time.sleep(0.001)

    def destroy(self):
        if self.hwnd:
            self.user32.DestroyWindow(self.hwnd)
            self.hwnd = None


# ---------------------------------------------------------------------------
# Injectors
# ---------------------------------------------------------------------------
def legacy_type_unicode(backend, text, delay=0.0):
    """The shipped v0.3.0 loop, verbatim: one SendInput call per character.

    Reimplemented here rather than imported so the "before" half of the
    evidence stays runnable after the backend is fixed — and so the fix is free
    to delete the per-character primitives it no longer needs.
    """
    from rekounts.text_inserter import VK_RETURN

    def send_unit(code):
        backend._send([
            backend._key_event(scan=code, flags=backend._KEYEVENTF_UNICODE),
            backend._key_event(
                scan=code,
                flags=backend._KEYEVENTF_UNICODE | backend._KEYEVENTF_KEYUP),
        ])

    for ch in text:
        if ch == "\r":
            continue
        if ch == "\n":
            backend._send([
                backend._key_event(vk=VK_RETURN),
                backend._key_event(vk=VK_RETURN,
                                   flags=backend._KEYEVENTF_KEYUP),
            ])
        else:
            code = ord(ch)
            if code > 0xFFFF:
                code -= 0x10000
                # Note the shipped bug this reproduces: the two halves of a
                # surrogate pair went out as two separate SendInput calls.
                send_unit(0xD800 + (code >> 10))
                send_unit(0xDC00 + (code & 0x3FF))
            else:
                send_unit(code)
        if delay:
            time.sleep(delay)


def steal_focus(thief, receiver, trigger_chars, stop):
    """Take the foreground away once the receiver has accepted N chars.

    This is the owner's "I started dictating here, then alt-tabbed" case: the
    injector keeps firing into whatever is focused *now*, so the tail of the
    message lands in a window the user never dictated into.
    """
    while not stop.is_set():
        if receiver.text_length() >= trigger_chars:
            break
        time.sleep(0.0005)
    if stop.is_set():
        return
    thief.focus()


def abuse(user32, backend, receiver, trigger_chars, hold_ms, vks, stop):
    """Hold a modifier down once the receiver has actually accepted N chars.

    Gating on observed progress (rather than sleeping a guessed interval) is
    what makes this reproduce identically on a fast machine and on a slow one
    with the app's keyboard hook installed.
    """
    while not stop.is_set():
        if receiver.text_length() >= trigger_chars:
            break
        time.sleep(0.0005)
    if stop.is_set():
        return
    for vk in vks:
        backend._send([backend._key_event(vk=vk)])
    time.sleep(hold_ms / 1000.0)
    for vk in reversed(vks):
        backend._send([backend._key_event(
            vk=vk, flags=backend._KEYEVENTF_KEYUP)])
    if VK_MENU in vks:
        # Tapping Alt over a top-level window arms the system menu and the
        # window then sits in a modal loop that never returns to our pump.
        # That is an artifact of the harness's bare EDIT window, not of the
        # code under test, so dismiss it.
        backend._send([backend._key_event(vk=VK_ESCAPE)])
        backend._send([backend._key_event(
            vk=VK_ESCAPE, flags=backend._KEYEVENTF_KEYUP)])


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------
def first_divergence(expected, got):
    for i in range(min(len(expected), len(got))):
        if expected[i] != got[i]:
            return i
    if len(expected) != len(got):
        return min(len(expected), len(got))
    return -1


def report(mode, expected, got, abused):
    idx = first_divergence(expected, got)
    ok = idx == -1
    print()
    print("=" * 72)
    print(" mode          : %s" % mode)
    print(" mid-burst abuse: %s" % ("yes" if abused else "no (baseline)"))
    print(" sent          : %d chars" % len(expected))
    print(" received      : %d chars" % len(got))
    if ok:
        print(" RESULT        : IDENTICAL - no corruption")
    else:
        print(" RESULT        : CORRUPTED - diverges at char %d" % idx)
        print(" intact prefix : %d chars (%.1f%% of the message)"
              % (idx, 100.0 * idx / max(len(expected), 1)))
        lo = max(0, idx - 40)
        print()
        print(" expected around the divergence:")
        print("   %r" % expected[lo:idx + 60])
        print(" actually received:")
        print("   %r" % got[lo:idx + 60])
        lost = len(expected) - len(got)
        if lost:
            print()
            print(" characters lost outright: %d" % lost)
    print("=" * 72)
    return ok


# ---------------------------------------------------------------------------
def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--mode", choices=("legacy", "current"), default="legacy",
                   help="legacy = shipped per-character loop; "
                        "current = whatever _Win32Backend.type_unicode does now")
    p.add_argument("--words", type=int, default=220,
                   help="approximate passage length (default: 220)")
    p.add_argument("--trigger", type=int, default=120,
                   help="press the modifier after this many chars have landed")
    p.add_argument("--hold", type=int, default=400,
                   help="how long to hold the modifier down, in ms")
    p.add_argument("--modifier", choices=sorted(_MODIFIERS), default="ctrl",
                   help="which chord to hold; 'ctrlwin' is the real dictation "
                        "hotkey but can fire OS shortcuts that steal focus")
    p.add_argument("--clean", action="store_true",
                   help="no mid-burst abuse - baseline run, must always pass")
    p.add_argument("--steal-focus", action="store_true",
                   help="instead of holding a modifier, hand the foreground to a "
                        "second window mid-burst (the alt-tab-while-dictating case)")
    p.add_argument("--key-delay", type=float, default=0.0,
                   help="inter-key delay in seconds (the app ships 0.0)")
    p.add_argument("--no-paste", action="store_true",
                   help="force literal keystrokes for long text instead of the "
                        "clipboard handoff, to measure that path on its own")
    args = p.parse_args(argv)

    if sys.platform != "win32":
        print("This harness reproduces a Win32-only defect; nothing to do here.")
        return 0

    from rekounts.text_inserter import _Win32Backend

    user32 = ctypes.WinDLL("user32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    user32.GetWindowTextLengthW.argtypes = [wintypes.HWND]
    user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    user32.SendMessageW.argtypes = [wintypes.HWND, wintypes.UINT,
                                    wintypes.WPARAM, wintypes.LPCWSTR]

    backend = _Win32Backend()
    passage = build_passage(args.words)

    receiver = Receiver(user32, kernel32)
    receiver.create()
    thief = None
    if args.steal_focus:
        thief = Receiver(user32, kernel32)
        thief.create()
        # A top-level EDIT shows its window title AS its text, which would then
        # read back as "leaked" content. Start it genuinely empty.
        thief.clear()
    try:
        if not receiver.focus():
            print("Could not take foreground focus; run this from an interactive "
                  "desktop session (not over a headless/remote shell).")
            return 2
        receiver.clear()
        receiver.pump()

        done = threading.Event()
        stop = threading.Event()

        outcome = {}

        def inject():
            try:
                if args.mode == "legacy":
                    legacy_type_unicode(backend, passage, args.key_delay)
                else:
                    # Drive the real production path, not just the backend:
                    # the modifier wait and the between-chunk focus gate live
                    # in TextInserter, so testing the backend alone would prove
                    # nothing about what the app actually does.
                    from rekounts.text_inserter import TextInserter
                    ins = TextInserter(mode="keystroke", key_delay=args.key_delay,
                                       modifier_timeout=3.0, backend=backend,
                                       clipboard_fallback=False,
                                       long_text_via_paste=not args.no_paste)
                    outcome["result"] = ins.insert(passage)
            finally:
                done.set()
                stop.set()

        threads = [threading.Thread(target=inject, daemon=True)]
        if args.steal_focus:
            threads.append(threading.Thread(
                target=steal_focus,
                args=(thief, receiver, args.trigger, stop),
                daemon=True))
        elif not args.clean:
            vks = _MODIFIERS[args.modifier]
            threads.append(threading.Thread(
                target=abuse,
                args=(user32, backend, receiver, args.trigger, args.hold,
                      vks, stop),
                daemon=True))

        print("Typing %d chars into the harness window (%s mode)..."
              % (len(passage), args.mode))
        started = time.monotonic()
        for t in threads:
            t.start()
        receiver.pump_until(done)
        elapsed = time.monotonic() - started
        for t in threads:
            t.join(timeout=2.0)

        got = receiver.text()
        print(" burst duration: %.2fs (%.3f ms/char)"
              % (elapsed, 1000.0 * elapsed / max(len(passage), 1)))
        if "result" in outcome:
            print(" insert() outcome: %s" % outcome["result"])
        ok = report(args.mode, passage, got,
                    abused=not (args.clean and not args.steal_focus))
        if thief is not None:
            leaked = thief.text()
            print()
            if leaked:
                print(" LEAKED into the window the user switched to: %d chars"
                      % len(leaked))
                print("   %r..." % leaked[:80])
            else:
                print(" Nothing leaked into the window the user switched to.")
        return 0 if ok else 1
    finally:
        # Never leave a modifier stuck down if we bailed mid-hold.
        for vk in (VK_CONTROL, VK_SHIFT, VK_MENU, VK_LWIN):
            try:
                backend._send([backend._key_event(
                    vk=vk, flags=backend._KEYEVENTF_KEYUP)])
            except Exception:
                pass
        receiver.destroy()
        if thief is not None:
            thief.destroy()


if __name__ == "__main__":
    sys.exit(main())
