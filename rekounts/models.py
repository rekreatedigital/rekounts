"""Speech-model delivery from Rekounts's own host — never Hugging Face.

The shipped app must never contact huggingface.co. Models are hosted as GitHub
Release assets on a dedicated public repo and installed into the app's OWN
directory (`%APPDATA%\\Rekounts\\models\\<name>`), pointed at by an absolute
path so no faster-whisper code path can reach the network (see
transcriber.load_model_offline_first).

This module is the single source of truth mapping a model NAME to its files,
sizes, SHA256 hashes and download URLs — the `MANIFEST` below. It is the
coordination interface with the model-selection work (feat/transcription-
accuracy): that side decides WHICH models ship by adding entries here; this side
owns the delivery mechanism that reads them. Adding a model is one manifest entry
plus one `scripts/publish_models.py <name>` run.

The files are Systran's MIT-licensed CTranslate2 conversions of OpenAI's
(MIT-licensed) Whisper weights; the license notice travels with every release
(see scripts/publish_models.py and docs/model-license.md).

Deliberately dependency-free (stdlib only, no faster-whisper / huggingface_hub
import) so it is cheap to unit-test and can run before Qt at startup.
"""

import hashlib
import json
import logging
import os
import shutil
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path

from rekounts.paths import models_dir

log = logging.getLogger(__name__)

# --------------------------------------------------------------------- manifest
# Our own host. Model files live as release assets so downloads work even while
# the app repo itself is private. Asset names are `<model>--<file>` (unique per
# release); the URL for any file is derived in file_url() so the manifest stays
# compact and one host/tag change re-points everything.
MODEL_HOST = "https://github.com/ryankyleocampo-github/talkativeai-models/releases/download"
# Default release tag holding the model assets. A model may override it (a new
# model can ship in its own release) via a "tag" key in its manifest entry.
DEFAULT_RELEASE_TAG = "models-v1"

# Every faster-whisper CTranslate2 model is exactly these four files. Kept as a
# module constant because it is the same for every model and drives both install
# verification and the publish script.
MODEL_FILENAMES = ("config.json", "model.bin", "tokenizer.json", "vocabulary.txt")


# name -> spec. `upstream` is the Hugging Face repo the files are converted from
# (provenance + used by the migration path and the publish script; NOT contacted
# by the app). `files` carries the exact size and SHA256 of each asset so a
# download is verified byte-for-byte before it is trusted.
MANIFEST = {
    "base": {
        "upstream": "Systran/faster-whisper-base",
        "files": {
            "config.json":    {"size": 2309,      "sha256": "56a6d8110d311f19c8f0471e562832c7527f146b567275bfca59fcf7c184da9a"},  # noqa: E501
            "model.bin":      {"size": 145217532, "sha256": "d01c3014881c9c6f3133c182f3d2887eb6ca1c789a7538c5c007196857a0a6a9"},  # noqa: E501
            "tokenizer.json": {"size": 2203239,   "sha256": "fb7b63191e9bb045082c79fd742a3106a12c99513ab30df4a0d47fa6cb6fd0ab"},  # noqa: E501
            "vocabulary.txt": {"size": 459861,    "sha256": "34ce3fe1c5041027b3f8d42912270993f986dbc4bb34cf27f951e34a1e453913"},  # noqa: E501
        },
    },
    "small": {
        "upstream": "Systran/faster-whisper-small",
        "files": {
            "config.json":    {"size": 2370,      "sha256": "b55496ac7940a7ae47d2c01eab40edfd8701feec1229d9cce3b40014383fb828"},  # noqa: E501
            "model.bin":      {"size": 483546902, "sha256": "3e305921506d8872816023e4c273e75d2419fb89b24da97b4fe7bce14170d671"},  # noqa: E501
            "tokenizer.json": {"size": 2203239,   "sha256": "fb7b63191e9bb045082c79fd742a3106a12c99513ab30df4a0d47fa6cb6fd0ab"},  # noqa: E501
            "vocabulary.txt": {"size": 459861,    "sha256": "34ce3fe1c5041027b3f8d42912270993f986dbc4bb34cf27f951e34a1e453913"},  # noqa: E501
        },
    },
    "medium": {
        "upstream": "Systran/faster-whisper-medium",
        "files": {
            "config.json":    {"size": 2257,       "sha256": "3622a2ddc41ec0e0fd4e68c13c6830f03b90c38d89aaad184de02c8c642cf807"},  # noqa: E501
            "model.bin":      {"size": 1527906378, "sha256": "9b45e1009dcc4ab601eff815b61d80e60ce3fd8c74c1a14f4a282258286b51ae"},  # noqa: E501
            "tokenizer.json": {"size": 2203239,    "sha256": "fb7b63191e9bb045082c79fd742a3106a12c99513ab30df4a0d47fa6cb6fd0ab"},  # noqa: E501
            "vocabulary.txt": {"size": 459861,     "sha256": "34ce3fe1c5041027b3f8d42912270993f986dbc4bb34cf27f951e34a1e453913"},  # noqa: E501
        },
    },
}

# Name of the small JSON marker written into an installed model dir once every
# file has been verified. Its presence + a match against the current manifest is
# what "installed" means — so a half-finished download (files present, marker
# absent) is correctly treated as not installed and resumed.
_LOCK_FILE = ".manifest.json"


class ModelUnavailable(Exception):
    """Raised when a model name is not in the manifest and is not an existing
    local directory — i.e. there is nothing we know how to fetch."""


class ModelVerificationError(Exception):
    """A downloaded/migrated file did not match its manifest SHA256 or size."""


@dataclass
class Progress:
    """One progress tick, passed to an optional on_progress callback.

    `phase` is "download" | "migrate" | "verify". `bytes_done`/`bytes_total` are
    for the WHOLE model (summed across files) so a caller can render a single
    percentage. `file` names the file currently being worked on.
    """
    model: str
    phase: str
    file: str
    bytes_done: int
    bytes_total: int

    @property
    def fraction(self) -> float:
        return (self.bytes_done / self.bytes_total) if self.bytes_total else 0.0


# ------------------------------------------------------------------ manifest API
def is_known(name: str) -> bool:
    return name in MANIFEST


def model_spec(name: str) -> dict:
    try:
        return MANIFEST[name]
    except KeyError:
        raise ModelUnavailable(
            f"unknown model {name!r}; known models: {', '.join(sorted(MANIFEST))}")


def model_total_bytes(name: str) -> int:
    return sum(f["size"] for f in model_spec(name)["files"].values())


def human_size(num_bytes: int) -> str:
    """Compact human size for notifications/README, e.g. '145 MB', '1.5 GB'."""
    step = 1000.0
    for unit in ("bytes", "KB", "MB", "GB"):
        if num_bytes < step or unit == "GB":
            if unit in ("bytes", "KB"):
                return f"{int(num_bytes)} {unit}"
            return f"{num_bytes:.0f} {unit}" if num_bytes >= 100 else f"{num_bytes:.1f} {unit}"
        num_bytes /= step
    return f"{num_bytes:.0f} GB"


def asset_name(model: str, filename: str) -> str:
    """Release-asset name for a model file. Flat namespace on the release, so the
    model name is folded in: 'small' + 'model.bin' -> 'small--model.bin'."""
    return f"{model}--{filename}"


def file_url(model: str, filename: str) -> str:
    """Public download URL for one model file on our host."""
    tag = model_spec(model).get("tag", DEFAULT_RELEASE_TAG)
    return f"{MODEL_HOST}/{tag}/{asset_name(model, filename)}"


def model_urls(model: str) -> dict:
    """{filename: url} for every file of a model — handy for tests/log capture
    proving downloads resolve to our host and never to huggingface.co."""
    return {fn: file_url(model, fn) for fn in model_spec(model)["files"]}


# ------------------------------------------------------------ hashing / checking
def sha256_file(path: Path, chunk: int = 1 << 20) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(chunk), b""):
            h.update(block)
    return h.hexdigest()


def _sizes_match(model_dir: Path, spec: dict) -> bool:
    """Fast presence/size check for every manifest file (no hashing)."""
    for filename, meta in spec["files"].items():
        p = model_dir / filename
        try:
            if p.stat().st_size != meta["size"]:
                return False
        except OSError:
            return False
    return True


def _manifest_signature(spec: dict) -> dict:
    """The part of a spec that identifies exactly-these-bytes: filename -> sha256.
    Written into the lock file so a manifest change (new hashes) invalidates a
    previously-installed copy and forces a refresh."""
    return {fn: meta["sha256"] for fn, meta in spec["files"].items()}


def is_installed(name: str, root: Path | None = None) -> bool:
    """True when `name` is present, complete and matches the current manifest.

    Trusts a verified install via the lock file + a size check rather than
    re-hashing gigabytes on every startup; the hashes were checked when the lock
    was written (install/migrate). A missing/mismatched lock, a changed manifest
    signature, or a wrong file size all read as not-installed.
    """
    spec = MANIFEST.get(name)
    if spec is None:
        return False
    model_dir = (root or models_dir()) / name
    lock = model_dir / _LOCK_FILE
    try:
        recorded = json.loads(lock.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    if recorded.get("files") != _manifest_signature(spec):
        return False
    return _sizes_match(model_dir, spec)


def installed_path(name: str, root: Path | None = None) -> Path | None:
    """The install directory if `name` is installed, else None."""
    if is_installed(name, root):
        return (root or models_dir()) / name
    return None


def _write_lock(model_dir: Path, name: str, spec: dict) -> None:
    payload = {
        "name": name,
        "upstream": spec.get("upstream"),
        "files": _manifest_signature(spec),
    }
    (model_dir / _LOCK_FILE).write_text(
        json.dumps(payload, indent=2), encoding="utf-8")


def _verify_file(path: Path, meta: dict, name: str, filename: str) -> None:
    actual = path.stat().st_size
    if actual != meta["size"]:
        raise ModelVerificationError(
            f"{name}/{filename}: size {actual} != expected {meta['size']}")
    digest = sha256_file(path)
    if digest != meta["sha256"]:
        raise ModelVerificationError(
            f"{name}/{filename}: sha256 mismatch (got {digest})")


# ---------------------------------------------------------- Hugging Face migration
def hf_cache_dir() -> Path:
    """Where huggingface_hub keeps its cache, honoring its env overrides so a
    user with a relocated cache is still migrated instead of re-downloaded."""
    for env in ("HF_HUB_CACHE", "HUGGINGFACE_HUB_CACHE"):
        val = os.environ.get(env)
        if val:
            return Path(val)
    home = os.environ.get("HF_HOME")
    if home:
        return Path(home) / "hub"
    return Path.home() / ".cache" / "huggingface" / "hub"


def _hf_snapshot_files(upstream: str, cache_root: Path) -> dict | None:
    """{filename: Path} for a cached HF snapshot of `upstream`, or None.

    Layout: <cache>/models--<org>--<repo>/snapshots/<rev>/<file> where each file
    is a symlink into ../../blobs. Picks the newest snapshot that actually has
    all four model files. Never touches the network — it only reads the cache.
    """
    org_repo = upstream.replace("/", "--")
    snapshots = cache_root / f"models--{org_repo}" / "snapshots"
    if not snapshots.is_dir():
        return None
    candidates = sorted(
        (d for d in snapshots.iterdir() if d.is_dir()),
        key=lambda d: d.stat().st_mtime, reverse=True)
    for snap in candidates:
        files = {}
        for filename in MODEL_FILENAMES:
            f = snap / filename
            # resolve() follows the symlink into blobs/ to the real file.
            if f.exists():
                files[filename] = f.resolve()
        if len(files) == len(MODEL_FILENAMES):
            return files
    return None


def migrate_from_hf_cache(name, spec, dest, on_progress=None, cache_root=None):
    """Reuse an existing Hugging Face-cached copy instead of downloading.

    Copies (never moves — the cache may be shared with other tools) each file
    into our own dir, verifying its SHA256 as it goes. Returns True on success,
    False when no complete matching snapshot is cached. A file present but with
    the wrong hash aborts the migration (returns False) so we fall through to a
    clean download rather than trusting a mismatched cache.
    """
    cache_root = cache_root or hf_cache_dir()
    snap_files = _hf_snapshot_files(spec["upstream"], cache_root)
    if not snap_files:
        return False
    total = model_total_bytes(name)
    done = 0
    dest.mkdir(parents=True, exist_ok=True)
    try:
        for filename, meta in spec["files"].items():
            src = snap_files.get(filename)
            if src is None or not src.exists():
                return False
            if src.stat().st_size != meta["size"]:
                log.info("HF cache %s/%s size mismatch; not migrating", name, filename)
                return False
            tmp = dest / (filename + ".part")
            shutil.copyfile(src, tmp)
            _verify_file(tmp, meta, name, filename)
            os.replace(tmp, dest / filename)
            done += meta["size"]
            if on_progress:
                on_progress(Progress(name, "migrate", filename, done, total))
        _write_lock(dest, name, spec)
        log.info("migrated %s from the Hugging Face cache (no download)", name)
        return True
    except (OSError, ModelVerificationError) as e:
        log.info("HF-cache migration of %s failed (%s); will download", name, e)
        _cleanup_parts(dest)
        return False


# --------------------------------------------------------------------- download
_RETRIES = 4
_TIMEOUT = 60
_CHUNK = 1 << 20  # 1 MiB


def _http_download(url, part_path, expected_size, on_bytes):
    """Download `url` to `part_path`, resuming if a partial `.part` exists.

    Uses an HTTP Range request so an interrupted download continues from where
    it stopped instead of restarting. `on_bytes(n)` is called with each newly
    written chunk length for progress. Returns nothing; raises on HTTP/IO error.
    """
    have = part_path.stat().st_size if part_path.exists() else 0
    if have > expected_size:
        # A stale/corrupt partial bigger than the target — start over.
        part_path.unlink()
        have = 0
    if have == expected_size:
        return
    headers = {"User-Agent": "Rekounts-model-downloader"}
    if have:
        headers["Range"] = f"bytes={have}-"
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
        # If the server ignored the Range (200 not 206), restart from zero.
        mode = "ab"
        if have and resp.status == 200:
            have = 0
            mode = "wb"
        with open(part_path, mode) as fh:
            while True:
                block = resp.read(_CHUNK)
                if not block:
                    break
                fh.write(block)
                on_bytes(len(block))


def download_model(name, spec, dest, on_progress=None):
    """Download every file of `name` into `dest`, verify it, install atomically.

    Per-file resume + retry: each file downloads to `<file>.part` (resumable via
    Range), is SHA256-verified, then renamed into place; the lock file is written
    only after ALL files pass, so an interrupted run resumes instead of being
    trusted. Raises on unrecoverable network error or a hash that never matches.
    """
    dest.mkdir(parents=True, exist_ok=True)
    total = model_total_bytes(name)
    done = 0
    for filename, meta in spec["files"].items():
        final = dest / filename
        if final.exists() and final.stat().st_size == meta["size"]:
            done += meta["size"]  # already fetched on a previous run
            continue
        url = file_url(name, filename)
        part = dest / (filename + ".part")
        base_done = done

        # Progress is read from the partial file's real size rather than summed
        # from the chunks, so it stays correct across a resume and across a
        # server that ignored our Range header and restarted the file.
        def _on_bytes(_n, _base=base_done, _part=part, _fn=filename):
            if not on_progress:
                return
            try:
                written = _part.stat().st_size
            except OSError:
                written = 0
            on_progress(Progress(name, "download", _fn, _base + written, total))

        last_err = None
        for attempt in range(1, _RETRIES + 1):
            try:
                _http_download(url, part, meta["size"], _on_bytes)
                _verify_file(part, meta, name, filename)
                break
            except ModelVerificationError as e:
                # A corrupt download won't fix itself by resuming — discard and
                # retry from scratch.
                last_err = e
                log.warning("%s/%s failed verification (%s); retrying clean",
                            name, filename, e)
                part.unlink(missing_ok=True)
            except (urllib.error.URLError, OSError, TimeoutError) as e:
                last_err = e
                log.warning("%s/%s download attempt %d/%d failed: %s",
                            name, filename, attempt, _RETRIES, e)
                time.sleep(min(2 ** attempt, 10))
        else:
            raise RuntimeError(
                f"could not download {name}/{filename} from {url}: {last_err}")
        os.replace(part, final)
        done = base_done + meta["size"]
        if on_progress:
            on_progress(Progress(name, "download", filename, done, total))
    _write_lock(dest, name, spec)
    log.info("downloaded %s into %s", name, dest)


def _cleanup_parts(model_dir: Path) -> None:
    try:
        for p in model_dir.glob("*.part"):
            p.unlink(missing_ok=True)
    except OSError:
        pass


# --------------------------------------------------------------------- ensure
def ensure_model(name, on_progress=None, root=None):
    """Return the local directory for `name`, fetching it if necessary.

    The one entry point the app uses. Order: already installed -> reuse the
    Hugging Face cache if present (migration, no download) -> download from our
    host. Guarantees an absolute directory the transcriber can point WhisperModel
    at with zero network access. Raises ModelUnavailable for an unknown name.
    """
    if name not in MANIFEST:
        # A power user may put a raw local directory path in config; honor it.
        p = Path(name)
        if p.is_dir():
            return p
        raise ModelUnavailable(
            f"unknown model {name!r}; known models: {', '.join(sorted(MANIFEST))}")

    spec = MANIFEST[name]
    root = root or models_dir()
    dest = root / name
    if is_installed(name, root):
        return dest
    root.mkdir(parents=True, exist_ok=True)
    if migrate_from_hf_cache(name, spec, dest, on_progress):
        return dest
    download_model(name, spec, dest, on_progress)
    return dest
