"""Device enumeration and name -> index resolution.

The fake tables below mirror the shape of a real Windows box (the dev machine
carries SteelSeries / EMEET / NVIDIA Broadcast endpoints): every endpoint is
repeated once per host API, MME truncates names to 31 characters, and the
system pseudo-devices sit at the head of the MME and DirectSound blocks.
"""

from rekounts.device_utils import (
    canonical_microphone_name, classify_level, list_microphones,
    resolve_input_device)

DEVICES = [
    {"name": "System Thing", "max_input_channels": 0},
    {"name": "Microphone (ME6S)", "max_input_channels": 2},
    {"name": "EMEET SmartCam", "max_input_channels": 1},
    {"name": "EMEET SmartCam", "max_input_channels": 1},  # duplicate name, 2 host APIs
]

# --- realistic multi-host-API table -----------------------------------------
HOSTAPIS = [
    {"name": "MME"},                     # 0
    {"name": "Windows DirectSound"},     # 1
    {"name": "ASIO"},                    # 2
    {"name": "Windows WASAPI"},          # 3
    {"name": "Windows WDM-KS"},          # 4
]

FULL_HEADSET = "Headset Microphone (3- SteelSeries Arctis Nova 5)"
MME_HEADSET = "Headset Microphone (3- SteelSer"      # PortAudio MME 31-char cut
FULL_OFFICECORE = "Microphone (EMEET OfficeCore M0 Plus)"
MME_OFFICECORE = "Microphone (EMEET OfficeCore M0"


def _d(name, hostapi, max_in=2, max_out=0):
    return {"name": name, "hostapi": hostapi,
            "max_input_channels": max_in, "max_output_channels": max_out}


VIRTUAL = "EMEET Virtual Audio (EMEET Virtual Camera)"

# Index-stable table; the comment column is the real device index.
REAL = [
    _d("Microsoft Sound Mapper - Input", 0),                    # 0  pseudo
    _d(MME_HEADSET, 0),                                         # 1
    _d("Microphone (NVIDIA Broadcast)", 0),                     # 2
    _d(MME_OFFICECORE, 0),                                      # 3
    _d("Speakers (Realtek)", 0, max_in=0, max_out=2),           # 4  output only
    _d("Primary Sound Capture Driver", 1),                      # 5  pseudo
    _d(FULL_HEADSET, 1),                                        # 6
    _d(VIRTUAL, 1),                                             # 7
    _d("Microphone (NVIDIA Broadcast)", 1),                     # 8
    _d(FULL_OFFICECORE, 1),                                     # 9
    _d("Realtek ASIO", 2),                                      # 10 ASIO driver
    _d(VIRTUAL, 3),                                             # 11
    _d("Microphone (NVIDIA Broadcast)", 3),                     # 12
    _d(FULL_HEADSET, 3),                                        # 13
    _d(FULL_OFFICECORE, 3),                                     # 14
    _d("Microphone (RTX-Audio Point)", 4),                      # 15 WDM-KS pin
    _d("Microphone (Steam Streaming Microphone Wave)", 4),      # 16 WDM-KS pin
    _d(FULL_HEADSET, 4),                                        # 17
]

DIRECTSOUND_BLOCK = [FULL_HEADSET, VIRTUAL, "Microphone (NVIDIA Broadcast)",
                     FULL_OFFICECORE]


# ------------------------------------------------------------ list_microphones
def test_lists_one_entry_per_endpoint_from_the_best_host_api():
    # 15 input-capable rows collapse to the 4 DirectSound endpoints.
    assert list_microphones(REAL, HOSTAPIS) == DIRECTSOUND_BLOCK


def test_names_are_full_length_never_the_mme_truncation():
    names = list_microphones(REAL, HOSTAPIS)
    assert MME_HEADSET not in names
    assert MME_OFFICECORE not in names


def test_pseudo_devices_and_asio_are_excluded():
    names = list_microphones(REAL, HOSTAPIS)
    for bad in ("Microsoft Sound Mapper - Input", "Primary Sound Capture Driver",
                "Realtek ASIO"):
        assert bad not in names


def test_deliberately_installed_virtual_endpoints_are_kept():
    names = list_microphones(REAL, HOSTAPIS)
    assert "Microphone (NVIDIA Broadcast)" in names
    assert VIRTUAL in names


def test_output_only_devices_are_excluded():
    assert "Speakers (Realtek)" not in list_microphones(REAL, HOSTAPIS)


def test_ordering_is_stable_device_index_order():
    assert list_microphones(REAL, HOSTAPIS) == list_microphones(REAL, HOSTAPIS)
    # DirectSound block runs 6, 7, 8, 9 -> that exact order comes back.
    assert list_microphones(REAL, HOSTAPIS)[0] == REAL[6]["name"]


def test_wasapi_is_not_chosen_even_though_its_names_are_full():
    # WASAPI cannot open a 16 kHz capture stream, so DirectSound wins despite
    # both carrying the same full endpoint names.
    assert list_microphones(REAL, HOSTAPIS) == DIRECTSOUND_BLOCK
    assert "Microphone (RTX-Audio Point)" not in list_microphones(REAL, HOSTAPIS)


def test_falls_back_to_wasapi_only_when_no_mixer_api_exists():
    # Last resort: better an unusual host API than an empty microphone list.
    apis = [{"name": "Windows WASAPI"}]
    devices = [dict(d, hostapi=0) for d in REAL if d["hostapi"] == 3]
    assert list_microphones(devices, apis) == [
        VIRTUAL, "Microphone (NVIDIA Broadcast)", FULL_HEADSET, FULL_OFFICECORE]


def test_falls_back_to_mme_when_only_mme_present():
    apis = [{"name": "MME"}]
    devices = [d for d in REAL if d["hostapi"] == 0]
    assert list_microphones(devices, apis) == [
        MME_HEADSET, "Microphone (NVIDIA Broadcast)", MME_OFFICECORE]


def test_unknown_host_apis_still_yield_a_deduped_list():
    # e.g. ALSA on a non-Windows box: no preferred API matches, so the
    # fallback path dedupes by name across everything non-ASIO.
    apis = [{"name": "ALSA"}]
    devices = [_d("hw:0 USB Mic", 0), _d("hw:0 USB Mic", 0), _d("Line In", 0)]
    assert list_microphones(devices, apis) == ["hw:0 USB Mic", "Line In"]


def test_missing_hostapi_table_does_not_crash():
    assert list_microphones(DEVICES, []) == ["Microphone (ME6S)", "EMEET SmartCam"]


def test_no_input_devices_returns_empty_list():
    assert list_microphones([_d("Speakers", 3, max_in=0, max_out=2)], HOSTAPIS) == []


# ------------------------------------------------------- resolve_input_device
def test_none_returns_none_for_system_default():
    assert resolve_input_device(None, DEVICES) is None


def test_exact_name_resolves_to_index():
    assert resolve_input_device("Microphone (ME6S)", DEVICES) == 1


def test_duplicate_name_returns_first_input_capable_index():
    assert resolve_input_device("EMEET SmartCam", DEVICES) == 2


def test_missing_name_returns_none_default():
    assert resolve_input_device("Nonexistent Mic", DEVICES) is None


def test_name_matching_output_only_device_is_skipped():
    # "System Thing" has 0 input channels -> not selectable -> default
    assert resolve_input_device("System Thing", DEVICES) is None


def test_exact_match_prefers_the_directsound_copy_of_an_endpoint():
    # FULL_HEADSET exists on DirectSound (6), WASAPI (13) and WDM-KS (17).
    # Only the DirectSound one can actually open at 16 kHz.
    assert resolve_input_device(FULL_HEADSET, REAL, HOSTAPIS) == 6


def test_legacy_truncated_mme_name_resolves_to_the_full_endpoint():
    # The config-in-the-wild case: a 31-char MME name saved by wave 1.
    idx = resolve_input_device(MME_HEADSET, REAL, HOSTAPIS)
    assert idx == 6
    assert REAL[idx]["name"] == FULL_HEADSET


def test_legacy_truncated_name_still_works_without_a_hostapi_table():
    # No host-API info -> exact match on the MME row itself wins; it is a real
    # capture device, so dictation keeps working.
    assert resolve_input_device(MME_HEADSET, REAL) == 1


def test_legacy_truncated_name_prefix_matches_when_mme_row_is_gone():
    # MME block dropped (e.g. list rebuilt after a driver change).
    devices = [d for d in REAL if d["hostapi"] != 0]
    idx = resolve_input_device(MME_HEADSET, devices, HOSTAPIS)
    assert devices[idx]["name"] == FULL_HEADSET


def test_second_legacy_truncated_name_resolves_too():
    idx = resolve_input_device(MME_OFFICECORE, REAL, HOSTAPIS)
    assert REAL[idx]["name"] == FULL_OFFICECORE


def test_pseudo_device_names_never_resolve():
    for bad in ("Microsoft Sound Mapper - Input", "Primary Sound Capture Driver"):
        assert resolve_input_device(bad, REAL, HOSTAPIS) is None


def test_asio_driver_never_resolves():
    assert resolve_input_device("Realtek ASIO", REAL, HOSTAPIS) is None


def test_short_names_do_not_prefix_match():
    # "Mic" must not silently grab "Microphone (NVIDIA Broadcast)".
    assert resolve_input_device("Mic", REAL, HOSTAPIS) is None


def test_ambiguous_prefix_picks_the_best_ranked_candidate_deterministically():
    # "Microphone (EMEET" prefixes two distinct endpoints; resolution must be
    # deterministic rather than raising or returning None.
    devices = [_d("Microphone (EMEET PIXY)", 3),
               _d("Microphone (EMEET OfficeCore M0 Plus)", 1),
               _d("Microphone (EMEET PIXY)", 1)]
    # DirectSound (host API 1) outranks WASAPI, then lowest index wins.
    assert resolve_input_device("Microphone (EMEET", devices, HOSTAPIS) == 1


# --------------------------------------------------- canonical_microphone_name
def test_canonical_name_passes_through_a_listed_name():
    assert canonical_microphone_name(FULL_HEADSET, REAL, HOSTAPIS) == FULL_HEADSET


def test_canonical_name_upgrades_a_legacy_truncated_name():
    assert canonical_microphone_name(MME_HEADSET, REAL, HOSTAPIS) == FULL_HEADSET


def test_canonical_name_of_system_default_is_none():
    assert canonical_microphone_name(None, REAL, HOSTAPIS) is None


def test_canonical_name_of_an_unplugged_mic_is_none():
    assert canonical_microphone_name("Microphone (Gone)", REAL, HOSTAPIS) is None


# --------------------------------------------------------------- level buckets
def test_classify_level_loud_quiet_silent():
    assert classify_level(0.5) == "loud"
    assert classify_level(0.03) == "quiet"
    assert classify_level(0.0005) == "silent"
