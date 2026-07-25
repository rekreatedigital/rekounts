import json
from pathlib import Path

from rekounts.paths import config_path as _config_path

DEFAULTS = {
    # PTT is a single non-modifier key: holding a modifier (ctrl/alt/win) while
    # live-typing turns the streamed letters into shortcuts. F8 is safe to hold.
    "ptt_hotkey": "f8",
    "toggle_hotkey": "ctrl+alt+space",
    "microphone": None,          # None = system default input device
    # 'small' is the default speech model for new installs. Two reasons:
    #   * Accuracy: across the published Whisper benchmarks 'small' is a clear
    #     step up from 'base' on natural and accented speech (fewer dropped/
    #     mangled words) - the gap that matters most to this app's users.
    #   * Latency headroom: measured on a Ryzen 7 7800X3D (int8) 'small' runs at
    #     ~0.2x real time - a ~10s dictation transcribes in ~2s. That's a fast
    #     CPU, so older machines will be proportionally slower (still well under
    #     real time for 'small'); 'base' stays the pick for weak CPUs. 'medium'
    #     and the GPU-only large models are ~3-4x slower again on CPU.
    # These are ranked from CPU latency + the literature; confirm the accuracy
    # ordering on YOUR voice with tools/asr_bench.py (see the README's Accuracy
    # guide - clean TTS clips can't tell the models apart, real speech can).
    "model": "small",
    # Device for the transcription model. The Settings UI offers two:
    #   "cpu"  - default; no GPU libraries needed, works everywhere.
    #   "auto" - probe for a GPU that can actually transcribe (load AND a tiny
    #            inference, in a throwaway subprocess so a broken GPU can never
    #            crash the app), else CPU. Costs a little first-load time.
    # Power users can also set "cuda" here by hand to force the GPU (needs the
    # nvidia-*-cu12 CUDA libs; see README). It still falls back to CPU if the
    # model can't even load, but - unlike "auto" - it won't protect you from a
    # GPU that loads yet fails at inference, so prefer "auto".
    "device": "cpu",
    "language": "en",            # or "auto"
    "strip_fillers": True,
    "auto_capitalize": True,
    "fix_punctuation_spacing": True,
    "collapse_repeats": True,    # collapse accidental stutters ("the the" -> "the")
    # Drop hedge phrases ("you know", "I mean", "like", "right") only when
    # punctuation marks them as asides (", you know,"), so "I like it" and
    # "turn right" are never touched. On by default for the same reason
    # strip_fillers is: clean text out of the box is the product.
    "strip_discourse_fillers": True,
    "insertion_mode": "paste",   # or "keystroke"
    # Keystroke mode only. Synthesized keystrokes provably cannot deliver a long
    # transcript intact (SendInput queues events that are dispatched against the
    # live keyboard/focus state - see rekounts/text_inserter.py), so anything
    # past ~100 characters is handed over via the clipboard, which is then put
    # back. Turn OFF to always type literally: the escape hatch for apps that
    # silently ignore Ctrl+V, where a paste cannot be detected as refused.
    "long_text_via_paste": True,
    "launch_on_startup": False,
    # --- pipeline quality (feat/pipeline-quality) ---------------------------
    # Pre-roll: keep a short rolling audio buffer so the first syllable isn't
    # clipped when a recording starts. RAM only, never written to disk. OFF by
    # default because it holds the mic stream open continuously (Windows keeps
    # the mic-in-use indicator lit the whole time) - not something to enable
    # silently in a privacy-first app. Users who notice clipped first words can
    # turn it on.
    "preroll_enabled": False,
    "preroll_seconds": 0.5,      # how much lead-in audio to retain when enabled
    # Safety cap for toggle-mode recordings the user forgets to stop. On local
    # CPU an over-long clip becomes a multi-minute transcription freeze. 10 min
    # is far longer than a normal dictation but still bounds the worst case; the
    # app warns ~30s before it fires. Set 0 to disable the cap.
    "max_recording_seconds": 600,
    # Drop Whisper's silence/noise hallucinations - the YouTube-caption outros
    # ("Thanks for watching, see you in the next one.") it was trained on. Two
    # gates, both required before anything is removed: the transcript (or the
    # trailing segment) must be caption boilerplate in EVERY clause, and for a
    # tail the decoder must itself report it heard no speech there. A genuine
    # sentence that merely starts that way is untouched.
    "filter_hallucinations": True,
    # Beam search width. 1 = greedy (fastest); 5 = noticeably more accurate for a
    # modest CPU cost. Accuracy matters more than ~100 ms for dictation.
    "beam_size": 5,
    # Show the minimal monochrome dictation pill overlay (bottom-center, follows
    # the monitor the mouse is on). Togglable at runtime from the tray menu.
    "show_pill": True,
    # --- Dashboard / local history (feat/dashboard-history) ---
    # Privacy: when False, History.add() is a no-op — nothing is written to disk.
    "history_enabled": True,
    # Local account profile (no auth, no network — display only).
    "profile_display_name": "",
    "profile_avatar_path": "",
    # --- unified hotkey (feat/hotkey-reliability) ---
    # Unified dictation hotkey (hold = push-to-talk, double-tap = hands-free,
    # tap-while-recording = stop). Supersedes ptt_hotkey/toggle_hotkey, which are
    # kept above for backward-compat and migrated into this key on first load.
    # "win" = the Windows key (pynput cmd). Default Ctrl+Win matches Wispr Flow.
    "hotkey": "ctrl+win",
    # --- unified Hub (feat/unified-hub) ---
    # Subtle start/stop/error audio cues (see rekounts/sounds.py). Generated
    # tones via stdlib winsound — nothing bundled, nothing downloaded. Silently
    # no-ops where no audio backend is available.
    #
    # ON by default deliberately: the start cue is the only feedback that the
    # hold-to-talk gesture actually took while your eyes are on the text field,
    # and a missed start costs a whole re-dictation. The cues are quiet enough
    # to live with (fix/minimal-sounds), and one switch in the Hub's Audio
    # section turns them off entirely for anyone who wants silence.
    "sound_effects": True,
    # Cue volume as peak amplitude, 0..1. The Hub offers three levels
    # (sounds.VOLUME_SOFT / _NORMAL / _LOUD) and snaps the dropdown to the
    # nearest, but any value in between is honored if you hand-edit it here.
    # Read live on every cue — no restart, no rebuild.
    "sound_volume": 0.09,
    # Tray balloon notifications ("Settings applied.", mic changes, errors).
    # Persisted by the Hub; TrayApp.notify() is the intended consumer.
    "show_notifications": True,
    # --- update check (feat/icon-installer-updates) ---
    # OFF by default, and it must stay that way: docs/privacy.md promises that
    # the app only reaches the network when you click something, so the one
    # exception has to be a thing the user switched on themselves. When on, the
    # tray asks GitHub for the newest RELEASE once, ~10s after launch, and stays
    # quiet unless there is actually a newer version. See rekounts/ui/tray.py.
    "auto_check_updates": False,
    # --- scratchpad (feat/scratchpad) ---
    # The floating sticky note you can dictate into, opened from the tray menu.
    # ON by default, but nothing appears on screen until the user opens it — the
    # setting only decides whether the tray offers it at all. Turning it off
    # hides an open pad (its text is kept; see rekounts/scratchpad_store.py).
    "scratchpad_enabled": True,
}

# The previous push-to-talk default. Configs still on this value are upgraded to
# the new unified default; a custom ptt_hotkey is preserved instead.
_OLD_PTT_DEFAULT = "f8"


def _migrate_hotkey(raw: dict, merged: dict) -> None:
    """Fill the new unified "hotkey" from a legacy config, in place.

    A user who customized ptt_hotkey (e.g. "f9") keeps it; a user still on the
    old "f8" default is upgraded to the new Ctrl+Win default. A config that
    already has "hotkey" is left untouched.
    """
    if "hotkey" in raw:
        return
    legacy = raw.get("ptt_hotkey")
    if legacy and legacy != _OLD_PTT_DEFAULT:
        merged["hotkey"] = legacy


def default_config_path() -> Path:
    return _config_path()


class Config:
    def __init__(self, path: Path | None = None):
        self.path = Path(path) if path else default_config_path()
        self.data = self._load()

    def _load(self) -> dict:
        try:
            # utf-8-sig transparently accepts a UTF-8 BOM (Notepad and
            # PowerShell's Out-File both add one) as well as plain UTF-8.
            raw = json.loads(self.path.read_text(encoding="utf-8-sig"))
            if not isinstance(raw, dict):
                raise ValueError("config root is not an object")
            merged = {**DEFAULTS, **raw}
        except (FileNotFoundError, ValueError, json.JSONDecodeError, OSError):
            # Never silently destroy a config we merely failed to parse: a
            # hand-edit with a stray comma is recoverable, an overwrite is not.
            self._backup_corrupt()
            merged = dict(DEFAULTS)
            self.data = merged
            self.save()
            return merged
        _migrate_hotkey(raw, merged)
        # backfill any missing keys (and migrations) and persist if changed
        if merged != raw:
            self.data = merged
            self.save()
        return merged

    def _backup_corrupt(self):
        """Preserve an unparseable config file as config.json.bak (best-effort)."""
        try:
            if self.path.exists():
                self.path.replace(self.path.with_name(self.path.name + ".bak"))
        except OSError:
            pass

    def get(self, key):
        return self.data.get(key, DEFAULTS.get(key))

    def set(self, key, value):
        self.data[key] = value

    def save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self.data, indent=2), encoding="utf-8")
