"""Generate the Rekounts icon — ``assets/icon.ico``, ``assets/icon.icns`` and
the installer's header.

The icon is committed to the repo (the build must not depend on anything being
generated at package time), but it is *generated*, never hand-drawn, so it can be
reproduced byte-for-byte from source:

    .venv\\Scripts\\python tools\\make_icon.py

The mark itself is the one already used by the website favicon
(``rekounts-site/public/favicon.svg``): four rounded bars — a little level
meter — in the near-white the UI uses for text, on the same charcoal rounded
tile as the dictation pill and the dashboard surfaces. The geometry below is
that SVG transcribed into a 32-unit coordinate space, one entry per element, so
the two stay comparable by eye. **If the favicon changes, change it here too** —
this file is the icon's source, and the SVG is the design of record.

Why not parse the SVG? Rendering it would pull in a whole SVG stack (cairosvg,
resvg, QtSvg) purely to draw six rectangles, and none of that would let us tune
the small sizes, which is the part that actually matters. Pillow is a build-time
dependency of this one script — nothing the app imports at runtime.

Each size is drawn at its own resolution (``_SUPERSAMPLE``× then downsampled with
Lanczos) rather than resized from one big master, so the 16 px entry — the one
Explorer, the taskbar and the tray show most — gets its edges from a render at
that size instead of from a blurry shrink of a 256 px image.
"""
from __future__ import annotations

import struct
import sys
from io import BytesIO
from pathlib import Path

try:
    from PIL import Image, ImageDraw
except ImportError:                                          # pragma: no cover
    raise SystemExit(
        "Pillow is required to regenerate the icon:  python -m pip install pillow"
    ) from None

REPO_ROOT = Path(__file__).resolve().parent.parent
ICON_PATH = REPO_ROOT / "assets" / "icon.ico"
ICNS_PATH = REPO_ROOT / "assets" / "icon.icns"
WIZARD_DIR = REPO_ROOT / "installer"

# The sizes Windows actually asks for: 16/20/24/32/40/48 across the DPI scales
# Explorer and the taskbar use, 64/128 for medium and large icon views, and 256
# for extra-large / the Alt-Tab and Start tiles.
SIZES = (16, 20, 24, 32, 40, 48, 64, 128, 256)

# The header image in the installer wizard. Inno Setup takes a set of .bmp files
# (no alpha channel, so they are flattened onto the wizard's white) and picks the
# nearest to the display's scaling; these are three of the sizes its docs list,
# covering 100%, 175% and 250%. Matched by the wildcard in installer/rekounts.iss.
WIZARD_SIZES = ((55, 55), (92, 97), (138, 140))
_WIZARD_BACKGROUND = (255, 255, 255)

# --- the mark, in the favicon's own 32-unit coordinate space -----------------
_VIEWBOX = 32.0
_TILE_FILL = (0x1A, 0x1C, 0x22, 0xFF)      # #1a1c22 — pill / dashboard charcoal
_TILE_STROKE = (0x3A, 0x3E, 0x48, 0xFF)    # #3a3e48 — the hairline edge
_BAR_FILL = (0xE8, 0xEA, 0xED, 0xFF)       # #e8eaed — UI near-white
_TILE_RADIUS = 9.0                         # rx on the SVG's rounded rect
_STROKE_WIDTH = 1.0
# x, y, width, height — the four <rect> bars, verbatim. Their corner radius is
# half their width in the SVG (rx=1.3, width=2.6), i.e. fully rounded caps.
_BARS = (
    (8.0, 13.0, 2.6, 6.0),
    (13.0, 9.0, 2.6, 14.0),
    (18.0, 11.0, 2.6, 10.0),
    (23.0, 14.0, 2.6, 4.0),
)

# Drawing at 8× and downsampling is what antialiases the tile's rounded corners
# and the bars' caps: Pillow's shape primitives have hard edges of their own.
_SUPERSAMPLE = 8

# ...but 8× a 1024 px icon (the .icns needs one) is an 8192² RGBA buffer, a
# quarter of a gigabyte to draw six rectangles. Cap the intermediate instead.
# 2048 is chosen so every size the .ico uses (≤256) keeps the full 8× and the
# committed .ico stays byte-for-byte reproducible; only the two large .icns
# entries drop to 4× and 2×, where the extra samples buy nothing visible anyway
# because the geometry is huge relative to a pixel.
_MAX_SUPERSAMPLED_PX = 2048


def _supersample_for(size: int) -> int:
    return max(2, min(_SUPERSAMPLE, _MAX_SUPERSAMPLED_PX // size))

# At and below this size the bars are snapped to whole device pixels instead of
# being antialiased down with everything else. A bar is 2.6/32 of the width, so
# at 16 px it lands on 1.3 physical pixels — downsampling smears four of those
# into one grey blob and the waveform stops reading as a waveform. Snapping
# costs a little geometric fidelity and buys back a legible icon at the size
# Explorer's list view, the taskbar and the tray all use. The tile behind them
# is still rendered supersampled, so its rounded corners stay smooth.
_HINT_AT_OR_BELOW = 32


def _round_half_up(value: float) -> int:
    """Python's ``round`` is banker's rounding; hinting wants the ordinary kind.

    With ``round``, x=6.5 and x=11.5 (two bar edges at 16 px) go to 6 and 12 —
    opposite directions for the same fraction, which unevens the gaps.
    """
    from math import floor
    return floor(value + 0.5)


def _draw_hinted_bars(img: Image.Image, size: int) -> None:
    """Paint the bars as crisp whole-pixel rectangles, in place."""
    scale = size / _VIEWBOX
    draw = ImageDraw.Draw(img)
    # One width for all four: rounding each bar's own edges independently makes
    # neighbouring bars come out 1 px and 2 px wide off the same 2.6 design width.
    bar_w = max(1, _round_half_up(_BARS[0][2] * scale))
    for x, y, w, h in _BARS:
        bar_h = max(1, _round_half_up(h * scale))
        left = _round_half_up(x * scale)
        # Every bar is centred on the same axis in the design; deriving the top
        # from that centre keeps them centred after rounding, which stacking
        # rounded tops and rounded heights does not.
        centre_y = (y + h / 2.0) * scale
        top = _round_half_up(centre_y - bar_h / 2.0)
        # Pillow's rectangle bounds are inclusive, hence the -1 on each far edge.
        draw.rectangle((left, top, left + bar_w - 1, top + bar_h - 1),
                       fill=_BAR_FILL)


def _render(size: int) -> Image.Image:
    """The mark rendered as one RGBA image ``size``×``size``."""
    hinted = size <= _HINT_AT_OR_BELOW
    ss = size * _supersample_for(size)
    scale = ss / _VIEWBOX
    img = Image.new("RGBA", (ss, ss), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    # The SVG's stroke straddles the rect's path (x=1..31 with stroke-width 1),
    # so the painted tile actually spans 0.5..31.5 and its outer radius is
    # rx + half the stroke. Reproducing that keeps the transparent corner margin
    # identical to the favicon's.
    half = _STROKE_WIDTH / 2.0
    left, top = (1.0 - half) * scale, (1.0 - half) * scale
    right, bottom = (31.0 + half) * scale, (31.0 + half) * scale
    draw.rounded_rectangle(
        (left, top, right, bottom),
        radius=(_TILE_RADIUS + half) * scale,
        fill=_TILE_FILL,
        outline=_TILE_STROKE,
        width=max(1, round(_STROKE_WIDTH * scale)),
    )

    if not hinted:
        for x, y, w, h in _BARS:
            draw.rounded_rectangle(
                (x * scale, y * scale, (x + w) * scale, (y + h) * scale),
                radius=(w / 2.0) * scale,
                fill=_BAR_FILL,
            )

    out = img.resize((size, size), Image.Resampling.LANCZOS)
    if hinted:
        _draw_hinted_bars(out, size)
    return out


# Entries at or below this size are stored as uncompressed DIBs, larger ones as
# PNG. That is the layout Windows' own icons use: PNG compression only pays off
# on the big entries (a 256 px DIB is ~256 KB on its own), while every legacy
# GDI path that might draw the small ones is guaranteed to understand a DIB.
_PNG_ABOVE = 64


def _dib_bytes(frame: Image.Image) -> bytes:
    """``frame`` as the headerless DIB an .ico entry expects.

    Two deviations from a normal .bmp, both required by the icon format: the
    14-byte BITMAPFILEHEADER is stripped, and ``biHeight`` is doubled because an
    icon's DIB nominally stores a colour bitmap stacked on top of a 1-bit AND
    mask. At 32 bits per pixel the alpha channel *is* the mask, so no mask data
    follows — only the field is doubled. (This is what Pillow's own .ico writer
    does; it is reproduced here because Pillow cannot mix DIB and PNG entries in
    one file.)
    """
    buf = BytesIO()
    frame.save(buf, "dib")
    blob = buf.getvalue()
    return blob[:8] + struct.pack("<i", frame.height * 2) + blob[12:]


def _png_bytes(frame: Image.Image) -> bytes:
    buf = BytesIO()
    frame.save(buf, "png", optimize=True)
    return buf.getvalue()


def build(path: Path = ICON_PATH) -> Path:
    """Write the multi-resolution .ico and return where it went.

    The container is assembled here rather than through ``Image.save(..., "ICO")``
    for two reasons: Pillow refuses to emit any entry larger than the image it is
    called on (so a `sizes` list is silently truncated), and it stores every entry
    in a single format.
    """
    payloads = []
    for size in SIZES:
        frame = _render(size)
        blob = _png_bytes(frame) if size > _PNG_ABOVE else _dib_bytes(frame)
        payloads.append((size, blob))

    header = struct.pack("<HHH", 0, 1, len(payloads))       # reserved, type=icon, count
    offset = len(header) + 16 * len(payloads)
    directory, images = b"", b""
    for size, blob in payloads:
        directory += struct.pack(
            "<BBBBHHII",
            0 if size >= 256 else size,   # bWidth  (0 spells 256)
            0 if size >= 256 else size,   # bHeight
            0,                            # bColorCount (0 = truecolour)
            0,                            # bReserved
            1,                            # wPlanes
            32,                           # wBitCount
            len(blob),
            offset,
        )
        images += blob
        offset += len(blob)

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(header + directory + images)
    return path


# --- macOS: the .icns the .app bundle needs ---------------------------------
#
# ``BUNDLE(icon=...)`` in Rekounts-macos.spec needs a real .icns. A Windows .ico
# there is not an error, it is simply ignored — which is why the groundwork spec
# carried ``icon=None`` and a note saying an .icns was "part of the
# hardware-verification pass". It is not: the format is fully specified and
# needs no Mac to write, so it is generated here from the same ``_render`` as
# every other size, and the Mac hour is spent on things that actually need a Mac.
#
# The container is trivially simple: b"icns", the total file length as a 4-byte
# big-endian integer, then one chunk per image — a 4-byte OSType, a 4-byte
# big-endian length that INCLUDES the 8-byte chunk header, and the payload.
#
# Every payload below is a PNG. All ten of these OSTypes accept PNG data on
# macOS 10.7+, and this is exactly the set Apple's own ``iconutil`` emits from a
# complete ``.iconset`` — so the file is indistinguishable from one built on a
# Mac, which is the property that matters when nobody here has one.
#
# NOT included: the legacy ``is32``/``il32``/``ic##`` RLE-plus-mask pairs for
# pre-10.7 systems. LSMinimumSystemVersion in the spec is 12.0.
_ICNS_TYPES = (
    (b"icp4", 16),     # 16x16
    (b"icp5", 32),     # 32x32
    (b"ic11", 32),     # 16x16@2x
    (b"ic12", 64),     # 32x32@2x
    (b"ic07", 128),    # 128x128
    (b"ic13", 256),    # 128x128@2x
    (b"ic08", 256),    # 256x256
    (b"ic14", 512),    # 256x256@2x
    (b"ic09", 512),    # 512x512
    (b"ic10", 1024),   # 512x512@2x (Retina "1024")
)
_ICNS_MAGIC = b"icns"


def build_icns(path: Path = ICNS_PATH) -> Path:
    """Write the macOS icon bundle and return where it went.

    Sizes are rendered once each and reused across the OSTypes that want the
    same pixel dimensions (ic11/icp5 are both 32 px, ic13/ic08 both 256, …), so
    a 256 px chunk and its @2x twin are the same bytes — as they are in an
    iconutil-built file.
    """
    rendered = {}
    chunks = b""
    for ostype, size in _ICNS_TYPES:
        if size not in rendered:
            rendered[size] = _png_bytes(_render(size))
        blob = rendered[size]
        chunks += ostype + struct.pack(">I", len(blob) + 8) + blob

    total = len(_ICNS_MAGIC) + 4 + len(chunks)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(_ICNS_MAGIC + struct.pack(">I", total) + chunks)
    return path


def describe_icns(path: Path = ICNS_PATH) -> list[tuple[str, int, int]]:
    """Parse the .icns back: ``(OSType, pixel width, byte length)`` each.

    Reading our own output back is the check worth having — the same reason
    :func:`describe` exists. The width is read out of the PNG's IHDR rather than
    assumed from the OSType, so a chunk labelled ``ic09`` that actually holds a
    256 px image (the mistake that makes a Retina Dock icon look soft) is caught.
    """
    blob = path.read_bytes()
    if blob[:4] != _ICNS_MAGIC:
        raise ValueError("not an .icns (bad magic)")
    declared = struct.unpack_from(">I", blob, 4)[0]
    if declared != len(blob):
        raise ValueError(
            f"header says {declared} bytes, file is {len(blob)}")
    out, offset = [], 8
    while offset < len(blob):
        ostype = blob[offset:offset + 4]
        length = struct.unpack_from(">I", blob, offset + 4)[0]
        payload = blob[offset + 8:offset + length]
        if payload[:8] != b"\x89PNG\r\n\x1a\n":
            raise ValueError(f"{ostype.decode()} chunk is not a PNG")
        # IHDR width: 8 bytes signature, 4 length, 4 "IHDR", then the width.
        width = struct.unpack_from(">I", payload, 16)[0]
        out.append((ostype.decode("ascii"), width, len(payload)))
        offset += length
    return out


def build_wizard_images(directory: Path = WIZARD_DIR) -> list[Path]:
    """Write the installer's header bitmaps and return their paths."""
    written = []
    for width, height in WIZARD_SIZES:
        # Square mark in a possibly-non-square frame, with a little breathing
        # room: Inno draws these hard against the wizard's text, and a mark that
        # touches its own edges reads as a mistake.
        side = min(width, height) - 4
        canvas = Image.new("RGB", (width, height), _WIZARD_BACKGROUND)
        mark = _render(side)
        canvas.paste(mark, ((width - side) // 2, (height - side) // 2), mark)
        out = directory / f"wizard-small-{width}x{height}.bmp"
        directory.mkdir(parents=True, exist_ok=True)
        canvas.save(out, format="BMP")
        written.append(out)
    return written


def describe(path: Path = ICON_PATH) -> list[tuple[int, int, str, int]]:
    """Parse the .ico back: ``(width, height, "PNG"|"BMP", byte length)`` each.

    Reading our own output back is the check that means something: the file is
    hand-assembled above, and ``tests/test_icon_asset.py`` uses this to assert the
    committed .ico really does carry every size the build claims it does.
    """
    blob = path.read_bytes()
    _reserved, _type, count = struct.unpack_from("<HHH", blob, 0)
    entries = []
    for i in range(count):
        w, h, _colors, _r, _planes, _bpp, length, offset = struct.unpack_from(
            "<BBBBHHII", blob, 6 + i * 16)
        # 0 in the byte-wide dimension fields is how an .ico spells 256.
        w, h = w or 256, h or 256
        payload = blob[offset:offset + length]
        kind = "PNG" if payload[:8] == b"\x89PNG\r\n\x1a\n" else "BMP"
        entries.append((w, h, kind, length))
    return entries


def main() -> int:
    out = build()
    print(f"wrote {out.relative_to(REPO_ROOT)}  ({out.stat().st_size:,} bytes)")
    for w, h, kind, length in describe(out):
        print(f"  {w:>3}x{h:<3}  {kind}  {length:>7,} bytes")
    icns = build_icns()
    print(f"wrote {icns.relative_to(REPO_ROOT)}  ({icns.stat().st_size:,} bytes)")
    for ostype, width, length in describe_icns(icns):
        print(f"  {ostype}  {width:>4}px  {length:>7,} bytes")
    for bmp in build_wizard_images():
        print(f"wrote {bmp.relative_to(REPO_ROOT)}  ({bmp.stat().st_size:,} bytes)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
