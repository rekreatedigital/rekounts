"""Feedback and bug reports, with nothing on the other end.

Rekounts has no backend, so "send feedback" cannot mean "post it somewhere".
This works exactly like the update check in ``rekounts/ui/tray.py``: the user
clicks, the app hands a prefilled URL to a tool they already have, and the app
itself transmits nothing. One sentence, same as the precedent — *user-initiated,
opens a browser or a mail client, sends no payload of its own.*

Two channels, because the audiences differ:

* a **GitHub issue** — public, searchable, and repliable, but it needs a GitHub
  account;
* a **mailto: link** to :data:`SUPPORT_EMAIL` — needs no account, works for
  everyone.

The user picks; the app does not guess.

This module is also where the "never" list is enforced. The diagnostics block is
built from settings and versions only. It never contains dictation text,
scratchpad content, dictionary entries or history rows — those are simply not
read here — and every string that does go in is passed through :func:`scrub`,
which removes the home path, the Windows user name and the machine name. The
user sees the finished block before anything moves (see
``rekounts/ui/feedback_dialog.py``: it has Copy and Save, and deliberately no
Send).

Nothing here imports Qt, so the block can be built and tested without a display.
"""

import getpass
import logging
import os
import platform
import re
import sys
from pathlib import Path
from urllib.parse import quote

# Safe to import at module level: text_inserter's own top-level imports are
# stdlib only (the Win32/Quartz layers load lazily inside their backends), so
# this keeps the "nothing here imports Qt, and nothing here loads a native
# runtime early" promise above.
from rekounts.text_inserter import describe_delivery

log = logging.getLogger(__name__)

# The one place the support address is written. The owner sets the final value;
# everything else — the Settings row, the tray entry, the tests — reads it from
# here.
SUPPORT_EMAIL = "feedback@rekounts.com"

ISSUE_URL = "https://github.com/{slug}/issues/new"

# Browsers accept far longer, but a URL that a mail client silently truncates
# loses the end of the report, so both are bounded and the diagnostics block is
# trimmed to fit rather than being cut off mid-sentence by someone else.
# Outlook and the Windows mail handler start dropping the tail somewhere around
# 2 000 characters; GitHub's issue form is comfortable well past 8 000.
MAX_ISSUE_URL = 7000
MAX_MAILTO_URL = 1900
TRIM_MARK = "\n…(trimmed to fit the link)"

SUBJECT = "Rekounts feedback"

# What the user is asked, in the order that makes a report useful. Left as plain
# prose rather than a form: this lands in a GitHub textarea or an email body,
# and neither is a place to fight with markdown.
REPORT_TEMPLATE = """\
What happened?


What did you expect to happen instead?


Steps to reproduce it:
1.
2.
3.
"""


# ============================================================== scrubbing
# Placeholders are the shape a Windows user already recognises, so a scrubbed
# path still reads as a path rather than as damage.
HOME_PLACEHOLDER = "%USERPROFILE%"
USER_PLACEHOLDER = "<user>"
MACHINE_PLACEHOLDER = "<machine>"

# `C:\\Users\\Ryan\\...` -> `C:\\Users\\<user>\\...`, for any drive and any name.
# Catches a path belonging to somebody OTHER than the person running the app
# (an old profile quoted in a log line), which the identity replacements below
# would miss.
_WIN_USER_PATH_RE = re.compile(r"(?i)([A-Z]:\\Users\\)[^\\/:*?\"<>|\r\n]+")
_POSIX_USER_PATH_RE = re.compile(r"(?i)(/(?:Users|home)/)[^/\s]+")

# A one-character name would match half the alphabet inside ordinary words; the
# word-boundary anchor is not enough protection at that length.
_MIN_IDENTITY_LEN = 2


def _path_replacements() -> list[tuple[str, str]]:
    """(real path, placeholder) for this machine's own folders, longest first.

    Longest first matters: ``%APPDATA%`` lives *inside* ``%USERPROFILE%``, and
    substituting the shorter one first would leave the longer path half
    rewritten. Each folder keeps its own placeholder rather than collapsing
    into one, so a scrubbed path still reads as the place it actually is.
    """
    out = []
    try:
        out.append((str(Path.home()), HOME_PLACEHOLDER))
    except Exception:                                        # pragma: no cover
        log.debug("could not resolve the home directory for scrubbing")
    for name in ("USERPROFILE", "HOME", "APPDATA", "LOCALAPPDATA", "TEMP"):
        value = os.environ.get(name)
        if value:
            out.append((value, HOME_PLACEHOLDER if name in ("USERPROFILE", "HOME")
                        else f"%{name}%"))
    # Both separators: Qt and pathlib hand back forward slashes in places where
    # Windows itself uses backslashes.
    out += [(path.replace("\\", "/"), mark) for path, mark in list(out)
            if "\\" in path]
    seen, ordered = set(), []
    for path, mark in sorted(out, key=lambda pair: len(pair[0]), reverse=True):
        path = path.rstrip("\\/")
        if len(path) > 3 and path.lower() not in seen:
            seen.add(path.lower())
            ordered.append((path, mark))
    return ordered


def _identity_tokens() -> list[tuple[str, str]]:
    """(name, placeholder) pairs for the person and the machine."""
    names = []
    for value in (os.environ.get("USERNAME"), os.environ.get("USER")):
        if value:
            names.append((value, USER_PLACEHOLDER))
    try:
        names.append((getpass.getuser(), USER_PLACEHOLDER))
    except Exception:                                        # pragma: no cover
        log.debug("could not resolve the user name for scrubbing")
    for value in (os.environ.get("COMPUTERNAME"), platform.node()):
        if value:
            names.append((value, MACHINE_PLACEHOLDER))
    seen, out = set(), []
    for name, placeholder in sorted(names, key=lambda p: len(p[0]), reverse=True):
        key = name.lower()
        if len(name) >= _MIN_IDENTITY_LEN and key not in seen:
            seen.add(key)
            out.append((name, placeholder))
    return out


def _ireplace(text: str, needle: str, replacement: str) -> str:
    return re.sub(re.escape(needle), replacement.replace("\\", "\\\\"),
                  text, flags=re.IGNORECASE)


def scrub(text: str) -> str:
    """Remove this machine's identity from ``text``.

    Handles the home directory (in either slash flavour), any other
    ``C:\\Users\\somebody`` path, the Windows user name and the machine name.
    Everything the app puts in a diagnostics block goes through here, and so
    does every log line, because a log line is the one place a real path turns
    up without anyone deciding to put it there.
    """
    if not text:
        return ""
    out = str(text)
    for path, placeholder in _path_replacements():
        out = _ireplace(out, path, placeholder)
    out = _WIN_USER_PATH_RE.sub(r"\1" + USER_PLACEHOLDER, out)
    out = _POSIX_USER_PATH_RE.sub(r"\1" + USER_PLACEHOLDER, out)
    for name, placeholder in _identity_tokens():
        out = re.sub(rf"(?i)\b{re.escape(name)}\b", placeholder, out)
    return out


# =========================================================== diagnostics
def _app_build() -> str:
    from rekounts import __version__
    kind = "installed build" if getattr(sys, "frozen", False) else "from source"
    return f"Rekounts {__version__} ({kind})"


def _python_build() -> str:
    bits = "64-bit" if sys.maxsize > 2 ** 32 else "32-bit"
    return f"{platform.python_version()} ({bits})"


def _qt_version() -> str:
    """PySide6's version — but only if Qt is ALREADY loaded.

    Read out of ``sys.modules`` rather than imported: importing Qt pulls in an
    OpenMP runtime that must not load before the speech model (see
    ARCHITECTURE.md), and a diagnostics helper is no place to break that rule.
    """
    module = sys.modules.get("PySide6")
    return getattr(module, "__version__", "") if module else ""


def _setting(config, key) -> str:
    if config is None:
        return ""
    try:
        value = config.get(key)
    except Exception:                                        # pragma: no cover
        log.debug("could not read %r for diagnostics", key)
        return ""
    return "" if value is None else str(value)


def _insertion(config) -> str:
    """How a dictation actually reaches the cursor, as one line.

    Was ``_setting(config, "insertion_mode")`` under the label "Insert text by",
    which was the name of a Settings row. Two things made that wrong:

      * The row is gone. A diagnostics block that quotes UI a reader cannot find
        sends them hunting through Settings for something that isn't there.
      * It named one of the TWO keys that decide this. ``keystroke`` means
        "pastes" or "types" depending on ``long_text_via_paste``, which are
        opposite behaviours — and the 2026-07-28 Notepad bug was diagnosed from
        a report showing only the first half.

    The sentence itself comes from text_inserter, beside the policy it
    describes, so it cannot drift from what the code does.
    """
    try:
        mode = config.get("insertion_mode")
        long_text = config.get("long_text_via_paste")
    except Exception:
        log.debug("could not read the insertion settings for diagnostics")
        return ""
    return "" if mode is None else describe_delivery(mode, long_text)


def diagnostic_fields(config=None) -> list[tuple[str, str]]:
    """The (label, value) pairs that make up the block, before scrubbing.

    Settings and versions only. Note what is *not* here: the microphone name,
    which routinely contains the owner's name ("Ryan's AirPods"), and the data
    folder, which is the home path spelled out. Neither is worth a privacy
    footnote, and a report rarely needs either.
    """
    fields = [
        ("App", _app_build()),
        ("System", platform.platform()),
        ("Python", _python_build()),
        ("Qt", _qt_version()),
        ("Model", _setting(config, "model")),
        ("Processing", _setting(config, "device")),
        ("Text insertion", _insertion(config)),
        ("Language", _setting(config, "language")),
    ]
    return [(label, value) for label, value in fields if value]


def format_fields(fields) -> str:
    width = max((len(label) for label, _ in fields), default=0)
    return "\n".join(f"{label + ':':<{width + 2}}{value}" for label, value in fields)


def collect(config=None, log_lines: int = 0) -> str:
    """The diagnostics block, scrubbed and ready to show the user.

    ``log_lines`` appends that many lines from the end of the log file. It is
    opt-in — the caller passes 0 unless the user ticked the box — because the
    log is the one part of this that the app did not compose on purpose.
    """
    text = format_fields(diagnostic_fields(config))
    if log_lines > 0:
        tail = log_tail(log_lines)
        if tail:
            count = len(tail.splitlines())
            text += f"\n\nLast {count} log lines (paths removed):\n{tail}"
    return scrub(text)


# ================================================================== the log
LOG_TAIL_LINES = 40
LOG_TAIL_CHARS = 4000
# How much of the file's tail is read to find those lines. The log rotates at
# 1 MB, and reading all of it to keep the last 40 lines would be silly.
_LOG_READ_BYTES = 64_000


def log_path() -> Path:
    from rekounts import paths
    return paths.logs_dir() / "rekounts.log"


def log_tail(lines: int = LOG_TAIL_LINES, max_chars: int = LOG_TAIL_CHARS) -> str:
    """The last ``lines`` log lines, scrubbed and capped — or "" if unreadable.

    Doubly bounded on purpose: a line count so the block stays readable, and a
    character count so one enormous traceback line cannot blow past the URL
    limit on its own. Nothing here is allowed to raise; a missing or locked log
    file just means the report goes without it.
    """
    path = log_path()
    try:
        size = path.stat().st_size
        with open(path, "rb") as fh:
            if size > _LOG_READ_BYTES:
                fh.seek(size - _LOG_READ_BYTES)
                fh.readline()          # drop the partial line the seek landed in
            raw = fh.read()
    except Exception as e:
        log.debug("could not read the log for diagnostics: %s", e)
        return ""
    # errors="replace": the log is written by another module, and a report must
    # not fail because one line arrived in an unexpected encoding.
    text = raw.decode("utf-8", errors="replace")
    tail = "\n".join(text.splitlines()[-lines:])
    if len(tail) > max_chars:
        tail = "…" + tail[-max_chars:]
    return scrub(tail)


# ==================================================================== links
def _query(pairs) -> str:
    """Percent-encode a query string, spaces as %20.

    ``quote`` rather than ``urlencode``: ``urlencode`` writes spaces as ``+``,
    which is correct for a form post and wrong inside a ``mailto:`` body, where
    a mail client shows the plus signs verbatim.
    """
    return "&".join(f"{key}={quote(value, safe='')}"
                    for key, value in pairs if value)


def _fit(build, body: str, limit: int) -> str:
    """``build(body)``, with ``body`` trimmed until the URL fits ``limit``.

    Trimming the body and letting ``build`` re-wrap it keeps the result
    well-formed — a code fence still closes, a mail body still ends in a
    newline — instead of chopping the finished URL and corrupting the last
    percent-escape.
    """
    url = build(body)
    if len(url) <= limit:
        return url
    low, high = 0, len(body)
    while low < high:
        mid = (low + high + 1) // 2
        if len(build(body[:mid] + TRIM_MARK)) <= limit:
            low = mid
        else:
            high = mid - 1
    return build(body[:low] + TRIM_MARK)


def github_issue_url(diagnostics: str, slug: str, *, title: str = SUBJECT,
                     template: str = REPORT_TEMPLATE,
                     limit: int = MAX_ISSUE_URL) -> str:
    """A prefilled "new issue" page. Opening it posts nothing.

    GitHub fills the form from the query string and waits — the user still
    reads it, edits it, and presses **Submit** themselves. Everything before
    that happens in their browser.
    """
    base = ISSUE_URL.format(slug=slug)

    def build(block: str) -> str:
        body = template
        if block:
            body += f"\n\nDiagnostics (from Rekounts, and reviewed by me):\n\n```\n{block}\n```\n"
        return f"{base}?{_query([('title', title), ('body', body)])}"

    return _fit(build, scrub(diagnostics), limit)


def mailto_url(diagnostics: str, address: str = SUPPORT_EMAIL, *,
               subject: str = SUBJECT, template: str = REPORT_TEMPLATE,
               limit: int = MAX_MAILTO_URL) -> str:
    """A prefilled email in whatever mail client the machine already uses.

    Same contract as the issue link: the message is composed, not sent. No code
    fence — this lands in a plain-text mail body, where backticks are just
    backticks.
    """
    def build(block: str) -> str:
        body = template
        if block:
            body += f"\n\nDiagnostics (from Rekounts, and reviewed by me):\n\n{block}\n"
        return f"mailto:{quote(address, safe='@')}?{_query([('subject', subject), ('body', body)])}"

    return _fit(build, scrub(diagnostics), limit)
