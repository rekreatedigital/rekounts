"""The committed icon asset, and how the app finds it.

``assets/icon.ico`` is generated (``tools/make_icon.py``) but committed, so the
build never depends on regenerating it. That makes the file itself worth
guarding: a truncated or re-saved-by-hand .ico still opens fine in most viewers
while quietly having lost the 16 px entry Explorer and the tray actually draw.
"""
import struct
import sys
from pathlib import Path

import pytest

from rekounts.ui.branding import APP_USER_MODEL_ID, icon_path, set_app_user_model_id

REPO_ROOT = Path(__file__).resolve().parent.parent
ICON = REPO_ROOT / "assets" / "icon.ico"

# What tools/make_icon.py is expected to emit. Kept here as a literal rather than
# imported from the generator so the test fails if the generator's SIZES change
# without anyone regenerating the committed file.
EXPECTED_SIZES = (16, 20, 24, 32, 40, 48, 64, 128, 256)


def _entries(path: Path):
    """(width, height, payload) per image in the .ico, parsed from the bytes."""
    blob = path.read_bytes()
    reserved, kind, count = struct.unpack_from("<HHH", blob, 0)
    assert (reserved, kind) == (0, 1), "not an .ico (bad ICONDIR header)"
    out = []
    for i in range(count):
        w, h, _colors, _res, _planes, _bpp, length, offset = struct.unpack_from(
            "<BBBBHHII", blob, 6 + i * 16)
        out.append((w or 256, h or 256, blob[offset:offset + length]))
    return out


def test_icon_asset_is_committed():
    assert ICON.is_file(), "assets/icon.ico is missing — run tools/make_icon.py"


def test_icon_carries_every_size_the_build_promises():
    assert tuple(w for w, _h, _p in _entries(ICON)) == EXPECTED_SIZES


def test_every_entry_is_square_and_non_empty():
    for w, h, payload in _entries(ICON):
        assert w == h, f"{w}x{h} entry is not square"
        assert len(payload) > 0, f"{w}px entry has no image data"


def test_small_entries_are_bitmaps_and_large_ones_are_png():
    """The mix is deliberate — see tools/make_icon.py.

    A PNG-compressed 16 px entry is legal on Windows 10 but is the one thing old
    GDI icon-drawing paths can fail to render; an uncompressed 256 px entry is
    ~256 KB on its own. Locking the split in stops a future regeneration from
    silently flipping either way.
    """
    for w, _h, payload in _entries(ICON):
        is_png = payload[:8] == b"\x89PNG\r\n\x1a\n"
        assert is_png == (w > 64), f"{w}px entry has the wrong storage format"


def test_the_app_resolves_the_icon_from_a_source_checkout():
    found = icon_path()
    assert found is not None
    assert found == ICON


def test_a_frozen_app_looks_inside_the_bundle(monkeypatch, tmp_path):
    """PyInstaller unpacks datas under sys._MEIPASS, not next to the package."""
    bundled = tmp_path / "assets" / "icon.ico"
    bundled.parent.mkdir()
    bundled.write_bytes(ICON.read_bytes())
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path), raising=False)
    assert icon_path() == bundled


def test_a_missing_asset_is_reported_as_missing_not_guessed(monkeypatch, tmp_path):
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path), raising=False)
    assert icon_path() is None


def test_setting_the_app_user_model_id_never_raises():
    # Cosmetic (taskbar grouping); it must not be able to stop the app starting.
    assert set_app_user_model_id() is sys.platform.startswith("win")
    assert APP_USER_MODEL_ID.startswith("RekreateDigital.")


# --- the Qt side. Offscreen so the suite stays headless. --------------------
pytest.importorskip("PySide6.QtWidgets")


@pytest.fixture(scope="module")
def _qt_app():
    import os

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6 import QtWidgets
    yield QtWidgets.QApplication.instance() or QtWidgets.QApplication([])


def test_qt_loads_the_asset_with_all_of_its_sizes(_qt_app):
    from rekounts.ui.branding import app_icon

    icon = app_icon()
    assert not icon.isNull()
    available = {size.width() for size in icon.availableSizes()}
    assert {16, 32, 256}.issubset(available)


def test_a_missing_asset_falls_back_to_a_drawn_mark(_qt_app, monkeypatch):
    """A blank tray icon is unrecoverable for the user — there is nothing to
    right-click — so a missing file must still produce something visible."""
    import rekounts.ui.branding as branding

    monkeypatch.setattr(branding, "icon_path", lambda: None)
    icon = branding.app_icon()
    assert not icon.isNull()
    assert not icon.pixmap(64, 64).isNull()
