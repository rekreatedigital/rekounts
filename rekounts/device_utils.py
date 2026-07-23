"""Microphone enumeration and name -> device-index resolution.

`list_microphones()` is THE canonical mic list for the whole app: the Settings
dropdown and the tray Microphone submenu must both use it so they can never
disagree. Everything here is pure apart from the optional sounddevice query, so
it is testable with faked device/host-API tables.

Why this module exists
----------------------
PortAudio enumerates every audio endpoint once per *host API*. On a real
Windows box that means the same physical mic shows up 3-5 times:

    idx  host API              name
      1  MME                   'Headset Microphone (3- SteelSer'   <- truncated
     15  Windows DirectSound   'Headset Microphone (3- SteelSeries Arctis Nova 5)'
     39  Windows WASAPI        'Headset Microphone (3- SteelSeries Arctis Nova 5)'
     44  Windows WDM-KS        'Headset Microphone (SteelSeries Arctis Nova 5)'

MME additionally truncates names to 31 characters, so deduping by exact name
cannot collapse those rows. The fix is to pick ONE host API and list only its
input endpoints, then drop the handful of well-known pseudo-devices.

Which host API, measured on the dev box (opening each input device at the
16 kHz faster-whisper expects):

    MME                    ok=6  fail=0
    Windows DirectSound    ok=6  fail=0
    ASIO                   ok=0  fail=1   Invalid sample rate
    Windows WASAPI         ok=0  fail=5   Invalid sample rate
    Windows WDM-KS         ok=0  fail=7   Unanticipated host error

So DirectSound, not WASAPI. PortAudio's WASAPI and WDM-KS backends hand the
rate straight to the driver and 16 kHz is not a native capture rate on modern
hardware; MME and DirectSound go through the Windows mixer, which resamples.
DirectSound wins over MME only because MME truncates the names.
"""

import logging

log = logging.getLogger(__name__)

# RMS thresholds for the Test-mic button.
_SILENT_BELOW = 0.005
_QUIET_BELOW = 0.15

# Host APIs we are willing to enumerate, best first. The first two are the only
# ones that can actually record at 16 kHz (see the module docstring); the last
# two are kept purely so an exotic PortAudio build still yields *something*
# rather than an empty microphone list.
#
# * Windows DirectSound - shared-mode, mixer-resampled, and reports the full
#                         endpoint name. The right default for dictation.
# * MME                 - also mixer-resampled so it works, but truncates names
#                         to 31 chars, which is what produced the duplicate
#                         "Headset Microphone (3- SteelSer" entries.
# * Windows WASAPI      - same endpoints and full names, but PortAudio opens it
#                         in shared mode at the *device's* native rate only, so
#                         a 16 kHz stream fails outright.
# * Windows WDM-KS      - kernel streaming: driver pins rather than user
#                         endpoints (stray "Wave"/"Point" entries), exclusive
#                         mode, and 16 kHz fails here too.
#
# ASIO is deliberately absent: an ASIO entry ("Realtek ASIO", "ASIO4ALL v2") is
# a *driver*, not a Windows capture endpoint. Opening one typically seizes the
# hardware exclusively, and it rejects 16 kHz as well.
_HOSTAPI_PREFERENCE = (
    "windows directsound",
    "mme",
    "windows wasapi",
    "windows wdm-ks",
)

# Host APIs that must never contribute a microphone, whatever else happens.
_EXCLUDED_HOSTAPIS = ("asio",)

# Aggregate/pseudo endpoints synthesised by Windows itself. They are not real
# hardware - each is a "whatever the system default is" alias, which is what
# our own "System default" entry already means.
#
#   MME          -> "Microsoft Sound Mapper - Input" / "- Output"
#   DirectSound  -> "Primary Sound Capture Driver" / "Primary Sound Driver"
#
# Matched as prefixes so truncated MME spellings are caught too. Deliberately
# NOT excluded: virtual endpoints the user installed on purpose (NVIDIA
# Broadcast, EMEET Virtual Audio, VB-Cable, VoiceMeeter) - those are real,
# selectable choices.
_PSEUDO_DEVICE_PREFIXES = (
    "microsoft sound mapper",
    "primary sound capture driver",
    "primary sound driver",
)

# A configured name must be at least this long before we will treat it as a
# truncated prefix of a real device (see resolve_input_device). Short strings
# match far too many devices to guess safely.
_MIN_LEGACY_PREFIX = 12


# ------------------------------------------------------------------ helpers
def _is_pseudo_device(name) -> bool:
    """True for Windows' synthetic 'default device' aliases."""
    low = (name or "").strip().lower()
    return any(low.startswith(p) for p in _PSEUDO_DEVICE_PREFIXES)


def _hostapi_name(device, hostapis) -> str:
    """Lowercased host-API name for a device row ('' when unknown)."""
    if not hostapis:
        return ""
    idx = device.get("hostapi")
    if not isinstance(idx, int) or not 0 <= idx < len(hostapis):
        return ""
    return (hostapis[idx].get("name") or "").strip().lower()


def _is_excluded_hostapi(api: str) -> bool:
    return any(bad in api for bad in _EXCLUDED_HOSTAPIS)


def _selectable(device, hostapis) -> bool:
    """Input-capable, real hardware, on a host API we allow."""
    if device.get("max_input_channels", 0) <= 0:
        return False
    if not (device.get("name") or "").strip():
        return False
    if _is_pseudo_device(device.get("name")):
        return False
    return not _is_excluded_hostapi(_hostapi_name(device, hostapis))


def _query(devices, hostapis):
    """Fill in missing tables from sounddevice. Never raises."""
    if devices is not None and hostapis is not None:
        return devices, hostapis
    try:
        import sounddevice as sd
        if devices is None:
            devices = [dict(d) for d in sd.query_devices()]
        if hostapis is None:
            hostapis = [dict(h) for h in sd.query_hostapis()]
    except Exception as e:                                  # pragma: no cover
        log.warning("could not query audio devices: %s", e)
        return (devices or []), (hostapis or [])
    return devices, hostapis


# -------------------------------------------------------------- public API
def list_microphones(devices=None, hostapis=None):
    """Return the canonical microphone list: ``list[str]`` of FULL device names.

    Contract (relied on by the Settings dropdown and the tray submenu):

    * One entry per real capture endpoint, with its complete, untruncated name
      - the same string Windows shows in its Sound settings.
    * Names are exactly what must be stored in ``config["microphone"]`` and are
      resolvable by :func:`resolve_input_device`.
    * "System default" is NOT included; that choice is ``None`` in config and
      each UI adds its own entry for it.
    * Order is stable: device-index order within the chosen host API, which is
      Windows' own enumeration order.
    * Never raises and never returns ``None`` - ``[]`` means "no mic found".

    How the list is built: all input-capable devices from the single best
    available host API (see ``_HOSTAPI_PREFERENCE``), minus Windows' pseudo
    endpoints (see ``_PSEUDO_DEVICE_PREFIXES``), minus ASIO drivers. If none of
    the preferred host APIs yields anything - a non-Windows box, or an unusual
    PortAudio build - it falls back to every non-ASIO input device deduped by
    name, which is still better than nothing.

    `devices` / `hostapis` are lists of dicts shaped like
    ``sounddevice.query_devices()`` / ``query_hostapis()``; both are queried
    live when omitted.

    Note: PortAudio caches its device table at initialisation, so a mic plugged
    in after the app started may not appear until restart. That is a PortAudio
    limitation, not a caching layer of ours - each call re-reads the table.
    """
    devices, hostapis = _query(devices, hostapis)

    usable = [d for d in devices if _selectable(d, hostapis)]

    for preferred in _HOSTAPI_PREFERENCE:
        picked = [d for d in usable if _hostapi_name(d, hostapis) == preferred]
        if picked:
            return _unique_names(picked)

    # Fallback: no recognised host API (or no hostapi table at all). Take
    # everything that survived the exclusions and dedupe by name.
    return _unique_names(usable)


def _unique_names(devices):
    """Names in order, first occurrence wins."""
    seen, out = set(), []
    for d in devices:
        name = d["name"]
        if name not in seen:
            seen.add(name)
            out.append(name)
    return out


def resolve_input_device(name, devices, hostapis=None):
    """Resolve a configured microphone NAME to a device index.

    Returns ``None`` - meaning "use the system default" - when `name` is None
    or nothing sensible matches.

    Candidates come from two kinds of match:

    1. **Exact match**: the device whose name is exactly `name`.
    2. **Legacy truncated name**: configs written before the app filtered by
       host API can hold an MME name truncated to 31 characters, e.g.
       ``'Headset Microphone (3- SteelSer'``. When `name` is at least
       ``_MIN_LEGACY_PREFIX`` characters, devices whose full name *starts with*
       it also count.

    All candidates are ranked together by ``(host-API preference, exact before
    prefix, device index)``. Exact-first still holds for every name the app
    itself writes, because those are always names from the chosen host API and
    so win on the first key already. Ranking host API above exactness is what
    upgrades a legacy MME config: ``'Headset Microphone (3- SteelSer'`` matches
    the MME row exactly, but that row is a truncated duplicate of a DirectSound
    endpoint, and pinning the user to a truncated name forever is the wrong
    answer. With no `hostapis` table every rank ties, so the old
    "first exact input-capable match" behaviour is what remains.

    Only *selectable* devices are ever considered, so a name can never resolve
    to an output-only row, a Windows pseudo-device ("Microsoft Sound Mapper -
    Input", "Primary Sound Capture Driver") or an ASIO driver - those fall
    through to ``None`` and the system default instead.

    `devices` / `hostapis` are lists of dicts shaped like
    ``sounddevice.query_devices()`` / ``query_hostapis()``. `hostapis` is
    optional; without it, host-API ranking and ASIO exclusion are skipped.
    """
    if name is None:
        return None

    allow_prefix = len(name) >= _MIN_LEGACY_PREFIX
    candidates = []          # (is_prefix_only, index, device)
    for i, d in enumerate(devices):
        if not _selectable(d, hostapis):
            continue
        if d["name"] == name:
            candidates.append((0, i, d))
        elif allow_prefix and d["name"].startswith(name):
            candidates.append((1, i, d))
    if not candidates:
        return None

    prefix_names = sorted({d["name"] for kind, _, d in candidates if kind})
    if len(prefix_names) > 1:
        log.warning("configured microphone %r is an ambiguous prefix of %s; "
                    "using the best-ranked", name, prefix_names)

    kind, index, device = min(
        candidates,
        key=lambda c: (_hostapi_rank(c[2], hostapis), c[0], c[1]))
    if kind:
        log.info("configured microphone %r matched %r by prefix (legacy "
                 "truncated name)", name, device["name"])
    return index


def canonical_microphone_name(name, devices=None, hostapis=None):
    """Map a stored config name onto the entry :func:`list_microphones` shows.

    Returns the matching full name, or ``None`` for "system default" / no
    match. Use this for radio checkmarks and dropdown selection so a config
    holding a legacy truncated MME name still highlights the right mic instead
    of silently showing nothing selected.
    """
    if name is None:
        return None
    devices, hostapis = _query(devices, hostapis)
    names = list_microphones(devices, hostapis)
    if name in names:
        return name
    if len(name) < _MIN_LEGACY_PREFIX:
        return None
    for candidate in names:
        if candidate.startswith(name):
            return candidate
    return None


def _hostapi_rank(device, hostapis) -> int:
    """Position in _HOSTAPI_PREFERENCE; unknown/unavailable sorts last."""
    api = _hostapi_name(device, hostapis)
    if api in _HOSTAPI_PREFERENCE:
        return _HOSTAPI_PREFERENCE.index(api)
    return len(_HOSTAPI_PREFERENCE)


def classify_level(rms: float) -> str:
    """Bucket a post-gain RMS level for user-facing feedback."""
    if rms < _SILENT_BELOW:
        return "silent"
    if rms < _QUIET_BELOW:
        return "quiet"
    return "loud"
