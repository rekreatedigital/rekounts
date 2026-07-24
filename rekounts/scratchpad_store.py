"""Persistence for the Scratchpad: its text and where it sits on screen.

Deliberately Qt-free. The pad itself is a widget that cannot be imported before
the speech model loads (see the import-order note in ``rekounts/__main__.py``),
but "what did the user write, and where was the window" is plain data — keeping
it here means it can be read, written and tested without Qt in the process.

Format: one small JSON object at ``%APPDATA%/Rekounts/scratchpad.json``.

    {"html": "<...Qt rich text...>", "geometry": [x, y, w, h]}

Why HTML for the note body: the pad offers bold/italic/underline/strikethrough
and bullet lists, so the stored form has to carry character and block formatting.
``QTextEdit.toHtml()`` / ``setHtml()`` is Qt's own round-trip for exactly that —
it is a documented pair, needs no third-party dependency, and stays inspectable
in a text editor if anything ever goes wrong. (A Qt-binary ``QTextDocument``
stream would be smaller but opaque and version-fragile; plain text would throw
away the formatting the toolbar exists to create.)

Everything degrades rather than raises: a missing, unreadable or corrupt file
means "you have a blank note", never a crash on startup. Losing a scratchpad is
bad; failing to open the app because of one is worse.
"""

import json
import logging
import os
from pathlib import Path

from rekounts.paths import scratchpad_path as _scratchpad_path

log = logging.getLogger(__name__)

# A hard ceiling on what we will write back. The note is something a person
# types and dictates into, so this is orders of magnitude above any real use —
# it exists so a runaway append loop can't grow an unbounded file in %APPDATA%.
MAX_HTML_BYTES = 4_000_000


def default_scratchpad_path() -> Path:
    return _scratchpad_path()


def _valid_geometry(value):
    """``[x, y, w, h]`` of four ints with a positive size, else None.

    Geometry is restored by move()/resize(), so a garbage value would put the
    window somewhere unusable (or at zero size, which reads as "the pad didn't
    open"). Anything not obviously sane is dropped and the caller falls back to
    its default placement.
    """
    if not isinstance(value, (list, tuple)) or len(value) != 4:
        return None
    try:
        x, y, w, h = (int(v) for v in value)
    except (TypeError, ValueError):
        return None
    if w <= 0 or h <= 0:
        return None
    return [x, y, w, h]


class ScratchpadStore:
    """Reads and writes the note file. One instance, owned by the pad."""

    def __init__(self, path: Path | None = None):
        self.path = Path(path) if path else default_scratchpad_path()

    def load(self) -> dict:
        """``{"html": str, "geometry": [x, y, w, h] | None}``. Never raises."""
        blank = {"html": "", "geometry": None}
        try:
            # utf-8-sig for the same reason config.py uses it: a hand-edit saved
            # from Notepad arrives with a BOM.
            raw = json.loads(self.path.read_text(encoding="utf-8-sig"))
        except FileNotFoundError:
            return blank
        except (ValueError, OSError) as e:
            log.warning("could not read the scratchpad file (%s); "
                        "starting with an empty note", e)
            return blank
        if not isinstance(raw, dict):
            log.warning("scratchpad file is not a JSON object; ignoring it")
            return blank
        html = raw.get("html")
        return {
            "html": html if isinstance(html, str) else "",
            "geometry": _valid_geometry(raw.get("geometry")),
        }

    def save(self, html: str, geometry=None) -> bool:
        """Write the note. True if it landed. Never raises.

        Written to a sibling temp file and then ``os.replace``d over the real
        one, so an interrupted write (or a full disk) leaves the previous note
        intact instead of truncating it to nothing.
        """
        html = html or ""
        payload = {"html": html, "geometry": _valid_geometry(geometry)}
        try:
            encoded = json.dumps(payload, indent=2)
        except (TypeError, ValueError):
            log.exception("scratchpad contents could not be encoded")
            return False
        if len(encoded.encode("utf-8")) > MAX_HTML_BYTES:
            log.warning("scratchpad is over %d bytes; not saving this revision",
                        MAX_HTML_BYTES)
            return False

        tmp = self.path.with_name(self.path.name + ".tmp")
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp.write_text(encoded, encoding="utf-8")
            os.replace(tmp, self.path)
            return True
        except OSError as e:
            log.warning("could not save the scratchpad: %s", e)
            try:
                tmp.unlink()
            except OSError:
                pass
            return False
