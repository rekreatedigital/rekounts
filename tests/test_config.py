import json
from rekounts.config import Config, DEFAULTS


def test_defaults_when_file_missing(tmp_path):
    cfg = Config(path=tmp_path / "config.json")
    assert cfg.data == DEFAULTS
    assert cfg.get("model") == DEFAULTS["model"]


def test_save_then_load_roundtrip(tmp_path):
    p = tmp_path / "config.json"
    cfg = Config(path=p)
    cfg.set("model", "medium")
    cfg.save()
    reloaded = Config(path=p)
    assert reloaded.get("model") == "medium"


def test_corrupt_file_recovers_to_defaults(tmp_path):
    p = tmp_path / "config.json"
    p.write_text("{not valid json", encoding="utf-8")
    cfg = Config(path=p)
    assert cfg.get("model") == DEFAULTS["model"]
    # corrupt file was rewritten as valid defaults
    assert json.loads(p.read_text(encoding="utf-8"))["model"] == DEFAULTS["model"]


def test_unknown_key_backfilled_from_defaults(tmp_path):
    p = tmp_path / "config.json"
    p.write_text(json.dumps({"model": "medium"}), encoding="utf-8")
    cfg = Config(path=p)
    assert cfg.get("model") == "medium"      # preserved
    assert cfg.get("ptt_hotkey") == DEFAULTS["ptt_hotkey"]  # backfilled


# --- unified-hotkey migration ---

def test_fresh_config_gets_default_hotkey(tmp_path):
    cfg = Config(path=tmp_path / "config.json")
    assert cfg.get("hotkey") == "ctrl+win"


def test_legacy_default_ptt_upgrades_to_new_default(tmp_path):
    # A config still on the OLD f8 default should adopt the new Ctrl+Win default.
    p = tmp_path / "config.json"
    p.write_text(json.dumps({"ptt_hotkey": "f8"}), encoding="utf-8")
    cfg = Config(path=p)
    assert cfg.get("hotkey") == "ctrl+win"


def test_custom_legacy_ptt_is_preserved(tmp_path):
    # A user who customized their PTT key keeps it as the unified hotkey.
    p = tmp_path / "config.json"
    p.write_text(json.dumps({"ptt_hotkey": "f9"}), encoding="utf-8")
    cfg = Config(path=p)
    assert cfg.get("hotkey") == "f9"


def test_explicit_hotkey_not_overwritten_by_migration(tmp_path):
    p = tmp_path / "config.json"
    p.write_text(json.dumps({"hotkey": "ctrl+alt+d", "ptt_hotkey": "f9"}),
                 encoding="utf-8")
    cfg = Config(path=p)
    assert cfg.get("hotkey") == "ctrl+alt+d"


def test_migration_is_persisted(tmp_path):
    p = tmp_path / "config.json"
    p.write_text(json.dumps({"ptt_hotkey": "f9"}), encoding="utf-8")
    Config(path=p)  # triggers migration + save
    reloaded = json.loads(p.read_text(encoding="utf-8"))
    assert reloaded["hotkey"] == "f9"


def test_bom_config_loads_without_data_loss(tmp_path):
    # Notepad and PowerShell's Out-File write a UTF-8 BOM; it must not be
    # treated as corruption (which used to silently reset every setting).
    p = tmp_path / "config.json"
    p.write_bytes(b"\xef\xbb\xbf" + json.dumps({"model": "medium"}).encode("utf-8"))
    cfg = Config(path=p)
    assert cfg.get("model") == "medium"
    assert not (tmp_path / "config.json.bak").exists()


def test_corrupt_config_is_backed_up_not_destroyed(tmp_path):
    p = tmp_path / "config.json"
    p.write_text("{not valid json", encoding="utf-8")
    cfg = Config(path=p)
    assert cfg.get("model") == DEFAULTS["model"]   # falls back to defaults
    bak = tmp_path / "config.json.bak"
    assert bak.exists()
    assert "not valid json" in bak.read_text(encoding="utf-8")
