"""The scratchpad's persistence layer — deliberately Qt-free, so is this file.

The contract worth defending: a user's note survives restarts, and NOTHING the
file can contain is allowed to stop the app from starting. Every corruption case
below must degrade to "you have a blank note", never to an exception.
"""
import json

import pytest

from rekounts.scratchpad_store import (MAX_HTML_BYTES, ScratchpadStore,
                                       _valid_geometry,
                                       default_scratchpad_path)


@pytest.fixture
def store(tmp_path):
    return ScratchpadStore(path=tmp_path / "scratchpad.json")


# ------------------------------------------------------------- round trip
def test_round_trips_html_and_geometry(store):
    html = "<p>a <b>bold</b> note</p>"
    assert store.save(html, [10, 20, 300, 400]) is True
    loaded = store.load()
    assert loaded["html"] == html
    assert loaded["geometry"] == [10, 20, 300, 400]


def test_missing_file_is_a_blank_note(store):
    assert store.load() == {"html": "", "geometry": None}


def test_save_creates_the_parent_directory(tmp_path):
    store = ScratchpadStore(path=tmp_path / "nested" / "deep" / "scratchpad.json")
    assert store.save("<p>hi</p>") is True
    assert store.load()["html"] == "<p>hi</p>"


def test_default_path_lives_beside_the_other_user_data():
    from rekounts.paths import app_data_dir
    assert default_scratchpad_path().parent == app_data_dir()
    assert default_scratchpad_path().name == "scratchpad.json"


# --------------------------------------------------------------- corruption
@pytest.mark.parametrize("contents", [
    "not json at all",
    "",
    "[1, 2, 3]",          # valid JSON, wrong shape
    '"just a string"',
    "{",
])
def test_unparseable_or_wrong_shape_degrades_to_blank(store, contents):
    store.path.parent.mkdir(parents=True, exist_ok=True)
    store.path.write_text(contents, encoding="utf-8")
    assert store.load() == {"html": "", "geometry": None}


def test_non_string_html_is_dropped_not_returned(store):
    store.path.parent.mkdir(parents=True, exist_ok=True)
    store.path.write_text(json.dumps({"html": {"nope": 1}}), encoding="utf-8")
    assert store.load()["html"] == ""


def test_utf8_bom_is_accepted(store):
    """Notepad and PowerShell's Out-File both add one — same as config.py."""
    store.path.parent.mkdir(parents=True, exist_ok=True)
    store.path.write_text(json.dumps({"html": "<p>x</p>"}), encoding="utf-8-sig")
    assert store.load()["html"] == "<p>x</p>"


def test_unicode_survives_the_round_trip(store):
    note = "<p>café — naïve 日本語 🎤</p>"
    store.save(note)
    assert store.load()["html"] == note


# ---------------------------------------------------------------- geometry
@pytest.mark.parametrize("value", [
    None, [], [1, 2, 3], [1, 2, 3, 4, 5], "1,2,3,4",
    [0, 0, 0, 100],            # zero width
    [0, 0, 100, -5],           # negative height
    ["a", "b", "c", "d"],
    [None, 1, 2, 3],
])
def test_bad_geometry_is_rejected(value):
    assert _valid_geometry(value) is None


def test_geometry_accepts_negative_origin():
    """A monitor left of the primary one has negative x — that is legitimate."""
    assert _valid_geometry([-1920, -100, 300, 400]) == [-1920, -100, 300, 400]


def test_corrupt_geometry_still_yields_the_html(store):
    store.path.parent.mkdir(parents=True, exist_ok=True)
    store.path.write_text(json.dumps({"html": "<p>keep me</p>",
                                      "geometry": "garbage"}), encoding="utf-8")
    loaded = store.load()
    assert loaded["html"] == "<p>keep me</p>"
    assert loaded["geometry"] is None


# -------------------------------------------------------------- durability
def test_oversize_note_is_refused_and_the_previous_one_survives(store):
    store.save("<p>the good note</p>")
    assert store.save("x" * (MAX_HTML_BYTES + 1)) is False
    assert store.load()["html"] == "<p>the good note</p>"


def test_failed_write_leaves_the_previous_note_intact(store, monkeypatch):
    """An interrupted save must not truncate what was already there."""
    import os
    store.save("<p>original</p>")
    monkeypatch.setattr(os, "replace",
                        lambda *a, **k: (_ for _ in ()).throw(OSError("disk full")))
    assert store.save("<p>replacement</p>") is False
    assert store.load()["html"] == "<p>original</p>"


def test_failed_write_cleans_up_its_temp_file(store, monkeypatch):
    import os
    monkeypatch.setattr(os, "replace",
                        lambda *a, **k: (_ for _ in ()).throw(OSError("nope")))
    store.save("<p>x</p>")
    assert not store.path.with_name(store.path.name + ".tmp").exists()


def test_unreadable_file_does_not_raise(store, monkeypatch):
    from pathlib import Path
    store.save("<p>x</p>")
    monkeypatch.setattr(Path, "read_text",
                        lambda *a, **k: (_ for _ in ()).throw(OSError("locked")))
    assert store.load() == {"html": "", "geometry": None}
