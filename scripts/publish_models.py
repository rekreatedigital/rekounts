"""Publish speech models to Rekounts's own release host. MAINTAINER TOOL.

Adding or refreshing a model is one command:

    python scripts/publish_models.py base            # fetch, verify, upload
    python scripts/publish_models.py --all
    python scripts/publish_models.py turbo --hashes  # manifest entry for a NEW model
    python scripts/publish_models.py base --dry-run  # do everything except upload

What it does, per model:

  1. Obtains the upstream files — from your local Hugging Face cache when it
     already has them (default, free) or by downloading from Hugging Face.
  2. Computes the SHA256 and size of every file.
  3. Verifies them against `MANIFEST` in rekounts/models.py, and REFUSES to
     upload on any mismatch. For a model not yet in the manifest it prints the
     entry to paste in (`--hashes`), so the hashes users verify against are
     always the ones actually published.
  4. Creates the release if needed and uploads each file as `<model>--<file>`,
     together with `LICENSE-MODELS.txt` — the MIT notices the redistribution
     requires (docs/model-license.md).

This script is the ONLY thing here that talks to huggingface.co. It runs on a
maintainer's machine; the shipped app never does.

Requires the `gh` CLI, authenticated with write access to the host repo.
"""

import argparse
import hashlib
import os
import shutil
import subprocess
import sys
import tempfile
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from rekounts import models  # noqa: E402

# Owner/repo holding the release assets, derived from the manifest's host URL so
# there is still exactly one place to change it.
HOST_REPO = models.MODEL_HOST.split("https://github.com/", 1)[-1].split("/releases")[0]
HF_TEMPLATE = "https://huggingface.co/{repo}/resolve/main/{filename}"
LICENSE_ASSET = "LICENSE-MODELS.txt"


def run(cmd, **kw):
    print("  $", " ".join(cmd))
    return subprocess.run(cmd, check=True, text=True, **kw)


def sha256_and_size(path: Path):
    h = hashlib.sha256()
    size = 0
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            h.update(block)
            size += len(block)
    return h.hexdigest(), size


# ------------------------------------------------------------------ acquisition
def from_hf_cache(upstream: str, work: Path) -> dict | None:
    """Copy the four files out of the local HF cache, if it has a full snapshot."""
    found = models._hf_snapshot_files(upstream, models.hf_cache_dir())
    if not found:
        return None
    print(f"  using local Hugging Face cache for {upstream}")
    out = {}
    for filename, src in found.items():
        dst = work / filename
        shutil.copyfile(src, dst)
        out[filename] = dst
    return out


def from_huggingface(upstream: str, work: Path) -> dict:
    """Download the four files from Hugging Face (maintainer side only)."""
    out = {}
    for filename in models.MODEL_FILENAMES:
        url = HF_TEMPLATE.format(repo=upstream, filename=filename)
        dst = work / filename
        print(f"  downloading {url}")
        with urllib.request.urlopen(url, timeout=120) as resp, open(dst, "wb") as fh:
            shutil.copyfileobj(resp, fh)
        out[filename] = dst
    return out


def acquire(upstream: str, work: Path, prefer_cache: bool = True) -> dict:
    if prefer_cache:
        cached = from_hf_cache(upstream, work)
        if cached:
            return cached
    return from_huggingface(upstream, work)


# -------------------------------------------------------------------- verifying
def describe(name: str, files: dict) -> dict:
    """{filename: {size, sha256}} for the acquired files."""
    out = {}
    for filename in models.MODEL_FILENAMES:
        digest, size = sha256_and_size(files[filename])
        out[filename] = {"size": size, "sha256": digest}
        print(f"    {filename:16} {size:>12,} bytes  {digest}")
    return out


def manifest_snippet(name: str, upstream: str, described: dict) -> str:
    lines = [f'    "{name}": {{',
             f'        "upstream": "{upstream}",',
             '        "files": {']
    for filename, meta in described.items():
        lines.append(
            f'            "{filename}":{" " * max(1, 16 - len(filename))}'
            f'{{"size": {meta["size"]}, "sha256": "{meta["sha256"]}"}},  # noqa: E501')
    lines += ['        },', '    },']
    return "\n".join(lines)


def verify_against_manifest(name: str, described: dict) -> bool:
    expected = models.MANIFEST[name]["files"]
    ok = True
    for filename, meta in described.items():
        want = expected.get(filename)
        if want is None:
            print(f"  !! {filename} is not in the manifest entry for {name}")
            ok = False
        elif want["sha256"] != meta["sha256"] or want["size"] != meta["size"]:
            print(f"  !! {filename} does NOT match the manifest\n"
                  f"       manifest: {want['size']:>12,}  {want['sha256']}\n"
                  f"       upstream: {meta['size']:>12,}  {meta['sha256']}")
            ok = False
    return ok


# -------------------------------------------------------------------- uploading
def release_exists(tag: str) -> bool:
    return subprocess.run(["gh", "release", "view", tag, "--repo", HOST_REPO],
                          capture_output=True, text=True).returncode == 0


def ensure_release(tag: str, dry_run: bool) -> None:
    if release_exists(tag):
        print(f"  release {tag} exists")
        return
    print(f"  creating release {tag} on {HOST_REPO}")
    if dry_run:
        return
    run(["gh", "release", "create", tag, "--repo", HOST_REPO,
         "--title", f"Speech models ({tag})",
         "--notes",
         "Speech models for Rekounts, served from this repo so the app never "
         "contacts huggingface.co.\n\n"
         "These are SYSTRAN's MIT-licensed CTranslate2 conversions of OpenAI's "
         "MIT-licensed Whisper models, redistributed unmodified. See "
         f"{LICENSE_ASSET} for the required notices.\n\n"
         "Each asset is named `<model>--<file>`. The app verifies every file "
         "against a SHA256 recorded in `rekounts/models.py` before use."])


def upload(name: str, files: dict, tag: str, dry_run: bool) -> None:
    staged = []
    work = files[models.MODEL_FILENAMES[0]].parent
    for filename, path in files.items():
        asset = work / models.asset_name(name, filename)
        if path != asset:
            os.replace(path, asset)
        staged.append(str(asset))
    print(f"  uploading {len(staged)} assets to {tag}")
    if dry_run:
        for s in staged:
            print(f"    (dry-run) {Path(s).name}")
        return
    run(["gh", "release", "upload", tag, "--repo", HOST_REPO, "--clobber", *staged])


def upload_license(tag: str, dry_run: bool) -> None:
    """Ship the MIT notices with the binaries, as the licenses require."""
    src = Path(__file__).resolve().parent.parent / "docs" / "model-license.md"
    with tempfile.TemporaryDirectory() as td:
        dst = Path(td) / LICENSE_ASSET
        shutil.copyfile(src, dst)
        print(f"  uploading {LICENSE_ASSET}")
        if dry_run:
            return
        run(["gh", "release", "upload", tag, "--repo", HOST_REPO, "--clobber", str(dst)])


# ------------------------------------------------------------------------- main
def publish(name: str, args) -> int:
    known = name in models.MANIFEST
    if not known and not args.hashes:
        print(f"!! {name} is not in MANIFEST. Run with --hashes to print its entry, "
              f"add it to rekounts/models.py, then publish.")
        return 1
    upstream = (models.MANIFEST[name]["upstream"] if known else args.upstream)
    if not upstream:
        print(f"!! no upstream repo known for {name}; pass --upstream <org/repo>")
        return 1

    print(f"\n=== {name}  ({upstream}) ===")
    with tempfile.TemporaryDirectory(prefix=f"publish-{name}-") as td:
        work = Path(td)
        files = acquire(upstream, work, prefer_cache=not args.no_cache)
        print("  hashing:")
        described = describe(name, files)

        if args.hashes:
            print(f"\n  manifest entry for rekounts/models.py:\n\n"
                  f"{manifest_snippet(name, upstream, described)}\n")
            if not known:
                return 0

        if not verify_against_manifest(name, described):
            print(f"!! refusing to publish {name}: upstream does not match the "
                  f"manifest. If upstream legitimately changed, update MANIFEST "
                  f"(--hashes) in the same commit that republishes.")
            return 1
        # ASCII only: this prints to a Windows console (cp1252) where a fancy
        # glyph raises UnicodeEncodeError and kills the publish run.
        print("  verified against manifest: OK")

        tag = models.MANIFEST[name].get("tag", models.DEFAULT_RELEASE_TAG)
        ensure_release(tag, args.dry_run)
        upload(name, files, tag, args.dry_run)
        upload_license(tag, args.dry_run)

    print(f"  {name} published to {HOST_REPO} ({tag})")
    for filename, url in models.model_urls(name).items():
        print(f"    {filename:16} {url}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("models", nargs="*", help="model names from the manifest")
    ap.add_argument("--all", action="store_true", help="publish every manifest model")
    ap.add_argument("--hashes", action="store_true",
                    help="print the manifest entry (for adding a new model)")
    ap.add_argument("--upstream", help="upstream HF repo, for a model not yet in "
                                       "the manifest (with --hashes)")
    ap.add_argument("--no-cache", action="store_true",
                    help="always download from Hugging Face, ignore the local cache")
    ap.add_argument("--dry-run", action="store_true",
                    help="fetch and verify, but do not create or upload anything")
    args = ap.parse_args()

    names = list(models.MANIFEST) if args.all else args.models
    if not names:
        ap.error("name at least one model, or pass --all")

    if not args.dry_run and not shutil.which("gh"):
        print("!! the gh CLI is required to upload releases")
        return 1

    print(f"host repo: {HOST_REPO}")
    failures = 0
    for name in names:
        try:
            failures += publish(name, args)
        except subprocess.CalledProcessError as e:
            print(f"!! {name}: command failed ({e})")
            failures += 1
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
