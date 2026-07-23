"""Tests for the self-hosted model delivery layer (rekounts/models.py).

The guarantee under test: a fresh user with no Hugging Face cache reaches a
working model with ZERO huggingface.co contact. Downloads resolve to our own
release host, are SHA256-verified, resume after interruption, and install
atomically; an existing HF cache is reused instead of re-downloaded.

Every download here is served by a fake urlopen — no test touches the network.
"""

import hashlib
import io
import json
import urllib.error
import urllib.request

import pytest

from rekounts import models


# --------------------------------------------------------------- test manifest
def _spec_for(blobs):
    return {
        "upstream": "Systran/faster-whisper-tiny-test",
        "files": {
            name: {"size": len(data),
                   "sha256": hashlib.sha256(data).hexdigest()}
            for name, data in blobs.items()
        },
    }


BLOBS = {
    "config.json": b'{"model_type": "whisper"}',
    "model.bin": b"BINARY-WEIGHTS-" * 400,
    "tokenizer.json": b'{"tokenizer": true}',
    "vocabulary.txt": b"hello\nworld\n",
}


@pytest.fixture
def fake_manifest(monkeypatch):
    """Replace the real manifest with one tiny model called 'testmodel'."""
    spec = _spec_for(BLOBS)
    monkeypatch.setattr(models, "MANIFEST", {"testmodel": spec})
    return spec


@pytest.fixture
def served(monkeypatch):
    """Fake urlopen serving BLOBS by asset name, honoring Range for resume.

    Records every requested URL so a test can assert what was contacted.
    """
    state = {"urls": [], "ranges": [], "fail_first": 0, "truncate_at": None,
             "ignore_range": False}

    class FakeResp(io.BytesIO):
        def __init__(self, data, status):
            super().__init__(data)
            self.status = status

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def fake_urlopen(req, timeout=None):
        url = req.full_url
        state["urls"].append(url)
        if state["fail_first"] > 0:
            state["fail_first"] -= 1
            raise urllib.error.URLError("simulated network failure")
        asset = url.rsplit("/", 1)[-1]
        filename = asset.split("--", 1)[1]
        data = BLOBS[filename]
        start, status = 0, 200
        rng = req.headers.get("Range")
        state["ranges"].append((asset, rng))
        if rng and not state["ignore_range"]:
            start = int(rng.split("=")[1].split("-")[0])
            data, status = data[start:], 206
        if state["truncate_at"] is not None:
            data = data[: state["truncate_at"]]
            state["truncate_at"] = None
        return FakeResp(data, status)

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    return state


# ------------------------------------------------------- real-manifest integrity
def test_real_manifest_entries_are_complete_and_well_formed():
    assert models.MANIFEST, "manifest must not be empty"
    for name, spec in models.MANIFEST.items():
        assert spec["upstream"], f"{name} has no upstream provenance"
        assert set(spec["files"]) == set(models.MODEL_FILENAMES), (
            f"{name} must carry exactly the four CT2 files")
        for filename, meta in spec["files"].items():
            assert meta["size"] > 0
            assert len(meta["sha256"]) == 64, f"{name}/{filename} bad hash length"
            int(meta["sha256"], 16)  # hex-only


def test_every_download_url_points_at_our_host_and_never_hugging_face():
    """The quality bar, as an assertion: nothing the app fetches is on HF."""
    for name in models.MANIFEST:
        for filename, url in models.model_urls(name).items():
            assert url.startswith(models.MODEL_HOST), url
            assert "huggingface" not in url.lower(), url
            assert url.endswith(models.asset_name(name, filename))


def test_manifest_has_the_models_the_config_defaults_reference():
    from rekounts.config import DEFAULTS
    assert DEFAULTS["model"] in models.MANIFEST
    assert DEFAULTS["stream_model"] in models.MANIFEST


def test_human_size_reads_naturally():
    assert models.human_size(512) == "512 bytes"
    assert models.human_size(147_882_941).endswith("MB")
    assert models.human_size(1_530_571_735).endswith("GB")


# --------------------------------------------------------------------- download
def test_download_fetches_verifies_and_installs_every_file(tmp_path, fake_manifest, served):
    dest = tmp_path / "testmodel"
    models.download_model("testmodel", fake_manifest, dest)

    for filename, data in BLOBS.items():
        assert (dest / filename).read_bytes() == data
    assert models.is_installed("testmodel", tmp_path)
    # No leftover partials, and the lock records what was verified.
    assert not list(dest.glob("*.part"))
    lock = json.loads((dest / models._LOCK_FILE).read_text())
    assert lock["files"] == {n: m["sha256"] for n, m in fake_manifest["files"].items()}


def test_download_only_ever_requests_our_host(tmp_path, fake_manifest, served):
    models.download_model("testmodel", fake_manifest, tmp_path / "testmodel")
    assert served["urls"], "expected some downloads"
    for url in served["urls"]:
        assert url.startswith(models.MODEL_HOST)
        assert "huggingface.co" not in url


def test_a_corrupted_download_is_rejected_not_installed(tmp_path, fake_manifest, monkeypatch):
    """A byte-mangling mirror must never be trusted, however many times we retry."""
    class FakeResp(io.BytesIO):
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def corrupt_urlopen(req, timeout=None):
        filename = req.full_url.rsplit("--", 1)[-1]
        return FakeResp(b"X" * len(BLOBS[filename]))

    monkeypatch.setattr(urllib.request, "urlopen", corrupt_urlopen)
    monkeypatch.setattr(models.time, "sleep", lambda *_: None)
    dest = tmp_path / "testmodel"
    with pytest.raises(RuntimeError):
        models.download_model("testmodel", fake_manifest, dest)
    assert not models.is_installed("testmodel", tmp_path)


def test_download_retries_a_transient_network_failure(tmp_path, fake_manifest, served,
                                                      monkeypatch):
    monkeypatch.setattr(models.time, "sleep", lambda *_: None)
    served["fail_first"] = 2          # two failures, then success
    models.download_model("testmodel", fake_manifest, tmp_path / "testmodel")
    assert models.is_installed("testmodel", tmp_path)


def test_an_interrupted_download_resumes_instead_of_restarting(tmp_path, fake_manifest,
                                                               served):
    """A half-written .part is continued with a Range request, not thrown away."""
    dest = tmp_path / "testmodel"
    dest.mkdir(parents=True)
    full = BLOBS["model.bin"]
    (dest / "model.bin.part").write_bytes(full[:1000])   # simulate an interruption

    models.download_model("testmodel", fake_manifest, dest)

    assert (dest / "model.bin").read_bytes() == full
    # It must have asked for the REMAINDER, not the whole file again.
    sent = dict(state for state in served["ranges"] if state[0].endswith("model.bin"))
    assert sent["testmodel--model.bin"] == "bytes=1000-"


def test_a_server_ignoring_range_still_produces_a_correct_file(tmp_path, fake_manifest,
                                                               served):
    """If the host answers 200 to a Range request we must restart the file, not
    append to the partial and corrupt it."""
    dest = tmp_path / "testmodel"
    dest.mkdir(parents=True)
    (dest / "model.bin.part").write_bytes(BLOBS["model.bin"][:1000])
    served["ignore_range"] = True

    models.download_model("testmodel", fake_manifest, dest)
    assert (dest / "model.bin").read_bytes() == BLOBS["model.bin"]


def test_progress_is_reported_and_reaches_completion(tmp_path, fake_manifest, served):
    seen = []
    models.download_model("testmodel", fake_manifest, tmp_path / "testmodel",
                          on_progress=seen.append)
    assert seen
    assert {p.phase for p in seen} == {"download"}
    assert seen[-1].bytes_done == models.model_total_bytes("testmodel")
    assert seen[-1].fraction == pytest.approx(1.0)


# ------------------------------------------------------------------ is_installed
def test_files_without_a_lock_file_do_not_count_as_installed(tmp_path, fake_manifest):
    """A half-finished install must be redone, not silently trusted."""
    dest = tmp_path / "testmodel"
    dest.mkdir(parents=True)
    for filename, data in BLOBS.items():
        (dest / filename).write_bytes(data)
    assert not models.is_installed("testmodel", tmp_path)


def test_a_changed_manifest_invalidates_a_previous_install(tmp_path, fake_manifest, served):
    models.download_model("testmodel", fake_manifest, tmp_path / "testmodel")
    assert models.is_installed("testmodel", tmp_path)
    # Ship new weights under the same name -> the old copy is no longer valid.
    bumped = json.loads(json.dumps(fake_manifest))
    bumped["files"]["model.bin"]["sha256"] = "0" * 64
    models.MANIFEST["testmodel"] = bumped
    assert not models.is_installed("testmodel", tmp_path)


def test_a_truncated_file_fails_the_size_check(tmp_path, fake_manifest, served):
    dest = tmp_path / "testmodel"
    models.download_model("testmodel", fake_manifest, dest)
    (dest / "model.bin").write_bytes(b"short")
    assert not models.is_installed("testmodel", tmp_path)


# -------------------------------------------------------------- HF-cache migration
def _build_fake_hf_cache(root, upstream, blobs, revision="abc123"):
    """Reproduce huggingface_hub's on-disk layout (snapshots/<rev>/<file>)."""
    snap = root / f"models--{upstream.replace('/', '--')}" / "snapshots" / revision
    snap.mkdir(parents=True)
    for name, data in blobs.items():
        (snap / name).write_bytes(data)
    return snap


def test_an_existing_hugging_face_cache_is_reused_not_redownloaded(
        tmp_path, fake_manifest, served, monkeypatch):
    cache = tmp_path / "hfcache"
    _build_fake_hf_cache(cache, fake_manifest["upstream"], BLOBS)
    monkeypatch.setattr(models, "hf_cache_dir", lambda: cache)

    root = tmp_path / "models"
    path = models.ensure_model("testmodel", root=root)

    assert models.is_installed("testmodel", root)
    assert (path / "model.bin").read_bytes() == BLOBS["model.bin"]
    assert served["urls"] == [], "migration must not download anything"


def test_migration_copies_rather_than_moves_the_shared_cache(tmp_path, fake_manifest,
                                                             monkeypatch):
    """The HF cache may be shared with other tools — it must survive intact."""
    cache = tmp_path / "hfcache"
    snap = _build_fake_hf_cache(cache, fake_manifest["upstream"], BLOBS)
    monkeypatch.setattr(models, "hf_cache_dir", lambda: cache)

    models.ensure_model("testmodel", root=tmp_path / "models")
    for name, data in BLOBS.items():
        assert (snap / name).read_bytes() == data


def test_migration_reports_progress_under_the_migrate_phase(tmp_path, fake_manifest,
                                                            monkeypatch):
    cache = tmp_path / "hfcache"
    _build_fake_hf_cache(cache, fake_manifest["upstream"], BLOBS)
    monkeypatch.setattr(models, "hf_cache_dir", lambda: cache)
    seen = []
    models.ensure_model("testmodel", on_progress=seen.append, root=tmp_path / "models")
    assert {p.phase for p in seen} == {"migrate"}


def test_a_corrupt_hf_cache_falls_through_to_a_clean_download(
        tmp_path, fake_manifest, served, monkeypatch):
    cache = tmp_path / "hfcache"
    bad = dict(BLOBS)
    bad["model.bin"] = b"Z" * len(BLOBS["model.bin"])   # right size, wrong bytes
    _build_fake_hf_cache(cache, fake_manifest["upstream"], bad)
    monkeypatch.setattr(models, "hf_cache_dir", lambda: cache)

    root = tmp_path / "models"
    path = models.ensure_model("testmodel", root=root)

    assert (path / "model.bin").read_bytes() == BLOBS["model.bin"]
    assert served["urls"], "a corrupt cache must be replaced by a real download"


def test_an_incomplete_hf_snapshot_is_ignored(tmp_path, fake_manifest, served, monkeypatch):
    cache = tmp_path / "hfcache"
    partial = {k: v for k, v in BLOBS.items() if k != "vocabulary.txt"}
    _build_fake_hf_cache(cache, fake_manifest["upstream"], partial)
    monkeypatch.setattr(models, "hf_cache_dir", lambda: cache)

    models.ensure_model("testmodel", root=tmp_path / "models")
    assert served["urls"], "an incomplete cache must not be trusted"


def test_hf_cache_dir_honors_the_standard_environment_overrides(monkeypatch):
    monkeypatch.setenv("HF_HUB_CACHE", r"D:\somewhere\hub")
    assert str(models.hf_cache_dir()).endswith("hub")
    monkeypatch.delenv("HF_HUB_CACHE")
    monkeypatch.setenv("HF_HOME", r"D:\hfhome")
    assert models.hf_cache_dir().name == "hub"


# ------------------------------------------------------------------- ensure_model
def test_ensure_is_a_no_op_once_installed(tmp_path, fake_manifest, served):
    root = tmp_path / "models"
    models.ensure_model("testmodel", root=root)
    calls = len(served["urls"])
    models.ensure_model("testmodel", root=root)          # second launch
    assert len(served["urls"]) == calls, "a warm start must not re-fetch"


def test_an_unknown_model_raises_rather_than_guessing(tmp_path):
    with pytest.raises(models.ModelUnavailable):
        models.ensure_model("no-such-model", root=tmp_path)


def test_a_local_directory_is_accepted_verbatim(tmp_path):
    """Power users may point config at their own converted model."""
    custom = tmp_path / "my-own-model"
    custom.mkdir()
    assert models.ensure_model(str(custom), root=tmp_path) == custom
