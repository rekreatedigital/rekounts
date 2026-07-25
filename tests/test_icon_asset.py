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


# --- the macOS bundle icon --------------------------------------------------
# assets/icon.icns is what Rekounts-macos.spec hands to BUNDLE(icon=...). Nobody
# on this project can open it in Finder to check it, so the bytes are checked
# here instead — and checked the way a wrong one fails: PyInstaller accepts any
# file path without looking, and a malformed .icns produces a bundle with a blank
# generic icon and no build warning at all.
ICNS = REPO_ROOT / "assets" / "icon.icns"

# The set Apple's own iconutil emits from a complete .iconset, in order.
EXPECTED_ICNS = (
    ("icp4", 16), ("icp5", 32), ("ic11", 32), ("ic12", 64), ("ic07", 128),
    ("ic13", 256), ("ic08", 256), ("ic14", 512), ("ic09", 512), ("ic10", 1024),
)


def _icns_chunks(path: Path):
    """(OSType, declared chunk length, payload) each, parsed from the bytes."""
    blob = path.read_bytes()
    assert blob[:4] == b"icns", "not an .icns (bad magic)"
    declared = struct.unpack_from(">I", blob, 4)[0]
    assert declared == len(blob), (
        f"the header claims {declared} bytes but the file is {len(blob)} — "
        "macOS reads the header, so a truncated file is a silent blank icon")
    out, offset = [], 8
    while offset < len(blob):
        ostype = blob[offset:offset + 4].decode("ascii")
        length = struct.unpack_from(">I", blob, offset + 4)[0]
        assert length >= 8, f"{ostype} chunk length {length} is impossible"
        out.append((ostype, length, blob[offset + 8:offset + length]))
        offset += length
    assert offset == len(blob), "chunk lengths do not tile the file exactly"
    return out


def test_the_macos_icon_is_committed():
    assert ICNS.is_file(), "assets/icon.icns is missing — run tools/make_icon.py"


def test_the_icns_carries_every_ostype_the_bundle_needs():
    assert [t for t, _len, _p in _icns_chunks(ICNS)] == [
        t for t, _size in EXPECTED_ICNS]


def test_each_icns_chunk_holds_a_png_of_the_size_its_ostype_promises():
    """The width comes out of the PNG's IHDR, not out of the OSType.

    An ic09 chunk holding a 256 px image is legal bytes and a soft Retina Dock
    icon — the exact mistake that is invisible without a Mac to look at.
    """
    for (ostype, _length, payload), (_expected_type, size) in zip(
            _icns_chunks(ICNS), EXPECTED_ICNS):
        assert payload[:8] == b"\x89PNG\r\n\x1a\n", f"{ostype} is not a PNG"
        width, height = struct.unpack_from(">II", payload, 16)
        assert (width, height) == (size, size), (
            f"{ostype} should be {size}px, holds {width}x{height}")


def test_the_spec_points_at_the_icns_and_not_at_the_windows_ico():
    """Regression guard for what this asset is FOR: the spec shipped with
    icon=None, so the bundle had no icon, and a .ico there would be ignored
    without a warning."""
    spec = (REPO_ROOT / "Rekounts-macos.spec").read_text(encoding="utf-8")
    assert 'icon=os.path.join("assets", "icon.icns")' in spec


def test_the_entitlements_plist_is_present_and_minimal():
    """Signing needs the owner's Apple account, so this file is never exercised
    by a build — which is exactly why its content is worth pinning. An extra
    entitlement added casually is attack surface nobody would notice."""
    import plistlib
    path = REPO_ROOT / "packaging" / "entitlements.plist"
    assert path.is_file(), "packaging/entitlements.plist is missing"
    with path.open("rb") as fh:
        entitlements = plistlib.load(fh)
    assert set(entitlements) == {
        "com.apple.security.cs.allow-unsigned-executable-memory",
        "com.apple.security.cs.disable-library-validation",
        "com.apple.security.device.audio-input",
    }
    assert all(value is True for value in entitlements.values())
    # A sandboxed build cannot listen for a global hotkey or synthesize
    # keystrokes into other apps, which is the whole app.
    assert "com.apple.security.app-sandbox" not in entitlements


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
