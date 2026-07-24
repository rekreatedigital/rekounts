"""_MacBackend: Quartz/AppKit faked so the macOS insertion path runs anywhere.

The fakes model exactly the surface the backend touches: keyboard-event
creation/flags/posting and unicode typing (Quartz), and a general pasteboard
with items, types, data and a changeCount (AppKit). TextInserter's policy is
then exercised END TO END against the fake — paste, clipboard backup/restore,
sequence-gated restore, modifier wait — the same way the Windows tests do it
with their fake backend.
"""
from rekounts.text_inserter import (
    _KVK_ANSI_V,
    _KVK_RETURN,
    InsertResult,
    TextInserter,
    _MacBackend,
)


# --- fakes -------------------------------------------------------------------

class FakeEvent:
    def __init__(self, keycode, down):
        self.keycode = keycode
        self.down = down
        self.flags = 0
        self.unicode = None


class FakeQuartz:
    kCGEventFlagMaskCommand = 1 << 20
    kCGHIDEventTap = 0
    kCGEventSourceStateHIDSystemState = 1

    def __init__(self):
        self.posted = []
        self.keys_down = set()

    def CGEventCreateKeyboardEvent(self, source, keycode, down):
        return FakeEvent(keycode, down)

    def CGEventSetFlags(self, event, flags):
        event.flags = flags

    def CGEventKeyboardSetUnicodeString(self, event, length, text):
        event.unicode = (length, text)

    def CGEventPost(self, tap, event):
        self.posted.append(event)

    def CGEventSourceKeyState(self, state, keycode):
        return keycode in self.keys_down


class FakePasteboardItem:
    def __init__(self, data=None):
        self._data = dict(data or {})

    # AppKit-shaped surface
    def types(self):
        return list(self._data)

    def dataForType_(self, t):
        return self._data.get(t)

    def setData_forType_(self, payload, t):
        self._data[t] = payload

    @classmethod
    def alloc(cls):
        return cls

    @classmethod
    def init(cls):
        return cls()


class FakePasteboard:
    def __init__(self):
        self._items = []
        self._count = 7

    def pasteboardItems(self):
        return list(self._items)

    def changeCount(self):
        return self._count

    def clearContents(self):
        self._items = []
        self._count += 1

    # Note: like the real NSPasteboard, only clearContents() bumps changeCount;
    # writing into the freshly-cleared generation does not bump it again.
    def writeObjects_(self, items):
        self._items = list(items)
        return True

    def setString_forType_(self, text, t):
        self._items = [FakePasteboardItem({t: text})]
        return True


class FakeApp:
    def __init__(self, pid):
        self._pid = pid

    def processIdentifier(self):
        return self._pid


class FakeAppKit:
    NSPasteboardTypeString = "public.utf8-plain-text"
    NSPasteboardItem = FakePasteboardItem

    def __init__(self, pid=4242):
        self._pb = FakePasteboard()
        self._front = FakeApp(pid)

    class NSPasteboard:
        pass

    def __getattr__(self, name):  # pragma: no cover - defensive
        raise AttributeError(name)


def make_backend(pid=4242):
    q = FakeQuartz()
    ak = FakeAppKit(pid)
    pb = ak._pb
    # NSPasteboard.generalPasteboard() is a class call; bolt the instance on.
    ak.NSPasteboard = type("NSPB", (), {
        "generalPasteboard": staticmethod(lambda: pb)})
    ak.NSWorkspace = type("NSWS", (), {
        "sharedWorkspace": staticmethod(lambda: type("WS", (), {
            "frontmostApplication": staticmethod(lambda: ak._front)})())})
    return _MacBackend(quartz=q, appkit=ak), q, pb


# --- backend primitives --------------------------------------------------------

def test_send_paste_posts_cmd_v_down_then_up():
    b, q, _ = make_backend()
    b.send_paste()
    assert [(e.keycode, e.down) for e in q.posted] == [
        (_KVK_ANSI_V, True), (_KVK_ANSI_V, False)]
    assert all(e.flags == FakeQuartz.kCGEventFlagMaskCommand for e in q.posted)


def test_foreground_window_is_the_frontmost_pid():
    b, _, _ = make_backend(pid=555)
    assert b.foreground_window() == 555
    assert b.is_no_target(555) is False
    assert b.is_no_target(None) is True
    assert b.is_blocked(555) is False


def test_modifiers_down_polls_the_modifier_keycodes():
    b, q, _ = make_backend()
    assert b.modifiers_down() is False
    q.keys_down.add(55)         # left Command held
    assert b.modifiers_down() is True
    q.keys_down = {62}          # right Control held
    assert b.modifiers_down() is True


def test_clipboard_sequence_is_change_count():
    b, _, pb = make_backend()
    before = b.clipboard_sequence()
    b.set_clipboard_text("hello")
    assert b.clipboard_sequence() == before + 1


def test_clipboard_backup_and_restore_round_trip():
    b, _, pb = make_backend()
    pb._items = [FakePasteboardItem({"public.utf8-plain-text": "keep me",
                                     "public.rtf": b"rtf-bytes"})]
    snapshot = b.backup_clipboard()
    b.set_clipboard_text("dictated")
    assert pb._items[0].dataForType_("public.utf8-plain-text") == "dictated"
    b.restore_clipboard(snapshot)
    restored = pb._items[0]
    assert restored.dataForType_("public.utf8-plain-text") == "keep me"
    assert restored.dataForType_("public.rtf") == b"rtf-bytes"


def test_type_unicode_chunks_and_sends_return_for_newlines():
    b, q, _ = make_backend()
    b.type_unicode("ab\ncd")
    typed = [e for e in q.posted if e.unicode is not None and e.down]
    returns = [e for e in q.posted if e.keycode == _KVK_RETURN and e.down]
    assert [e.unicode[1] for e in typed] == ["ab", "cd"]
    assert len(returns) == 1


def test_type_unicode_counts_utf16_units_for_astral_chars():
    b, q, _ = make_backend()
    b.type_unicode("🎤")             # one char, two UTF-16 units
    typed = [e for e in q.posted if e.unicode is not None and e.down]
    assert typed[0].unicode == (2, "🎤")


def test_long_text_is_chunked():
    b, q, _ = make_backend()
    b.type_unicode("x" * 45)
    typed = [e for e in q.posted if e.unicode is not None and e.down]
    assert [len(e.unicode[1]) for e in typed] == [20, 20, 5]


# --- TextInserter policy over the mac backend ---------------------------------

def make_inserter(**kw):
    backend, q, pb = make_backend()
    ins = TextInserter(mode="paste", restore_delay=0, modifier_timeout=0.05,
                       backend=backend, **kw)
    return ins, backend, q, pb


def test_full_paste_flow_restores_the_clipboard():
    ins, b, q, pb = make_inserter()
    pb._items = [FakePasteboardItem({"public.utf8-plain-text": "before"})]
    result = ins.insert("dictated text")
    assert result == InsertResult.PASTED
    # Cmd+V was synthesized...
    assert [(e.keycode, e.down) for e in q.posted if e.unicode is None] == [
        (_KVK_ANSI_V, True), (_KVK_ANSI_V, False)]
    # ...and the user's clipboard came back afterwards.
    assert pb._items[0].dataForType_("public.utf8-plain-text") == "before"


def test_restore_is_skipped_when_something_else_wrote_the_clipboard():
    ins, b, q, pb = make_inserter()
    pb._items = [FakePasteboardItem({"public.utf8-plain-text": "before"})]

    real_send = b.send_paste

    def send_and_clobber():
        real_send()
        # A real user copy = clearContents (bumps changeCount) + write.
        pb.clearContents()
        pb.setString_forType_("user copied this mid-paste",
                              "public.utf8-plain-text")

    b.send_paste = send_and_clobber
    assert ins.insert("dictated") == InsertResult.PASTED
    assert (pb._items[0].dataForType_("public.utf8-plain-text")
            == "user copied this mid-paste")


def test_focus_change_between_capture_and_insert_aborts():
    ins, b, q, pb = make_inserter()
    target = ins.capture_target()
    b._ak._front = FakeApp(9999)       # another app came to the front
    assert ins.insert("text", target=target) == InsertResult.NO_TARGET
    assert q.posted == []              # nothing synthesized into the wrong app


def test_held_ptt_modifiers_are_waited_out_before_paste():
    ins, b, q, pb = make_inserter()
    q.keys_down = {55, 59}             # Cmd+Ctrl held (the default mac hotkey)
    waited = []

    real_send = b.send_paste

    def send_checking():
        waited.append(not b.modifiers_down())
        real_send()

    b.send_paste = send_checking
    # Timeout is tiny (0.05s) so the wait gives up and proceeds; the point is
    # that the guard consulted modifiers_down before sending.
    assert ins.insert("hi") == InsertResult.PASTED
    assert waited == [False]           # still held -> proceeded after timeout

    q.keys_down = set()
    waited.clear()
    assert ins.insert("hi") == InsertResult.PASTED
    assert waited == [True]            # released -> clean Cmd+V


def test_keystroke_mode_types_through_the_backend():
    backend, q, pb = make_backend()
    ins = TextInserter(mode="keystroke", modifier_timeout=0,
                       backend=backend)
    assert ins.insert("ok") == InsertResult.TYPED
    assert [e.unicode[1] for e in q.posted if e.unicode and e.down] == ["ok"]


def test_empty_text_is_skipped():
    ins, b, q, pb = make_inserter()
    assert ins.insert("") == InsertResult.SKIPPED
    assert q.posted == []
